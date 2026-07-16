"""Unit tests for person hazard policy (PHASE_77)."""

from __future__ import annotations

import copy
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.models.schemas import RobotCommandResponse
from app.services import orchestrator
from app.services import person_hazard as ph


def _fresh_advisory(*, task_id: int = 101, observed_at: str | None = None) -> dict:
    ts = observed_at or datetime.now(timezone.utc).isoformat()
    return {
        "schema_version": "vision-person-hazard-latest.v1",
        "monitor_id": "person_drive",
        "source": "tb3_1_picam",
        "robot_id": "tb3_1",
        "result": "ADVISORY",
        "reason_code": "HUMAN_DETECTED",
        "event": {
            "schema_version": "vision-monitor-event.v1",
            "event_id": "evt-1",
            "event_type": "HUMAN_DETECTED",
            "source": "tb3_1_picam",
            "robot_id": "tb3_1",
            "task_id": task_id,
            "command_id": None,
            "result": "ADVISORY",
            "severity": "CRITICAL",
            "confidence": 0.9,
            "reason_code": "HUMAN_DETECTED",
            "trusted": False,
            "observed_at": ts,
            "data_json": {"source_event_id": "src-1"},
        },
    }


class PersonHazardPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        ph._runtime.clear()
        ph._cooldown_until.clear()

    def test_settings_expose_no_alternate_person_hazard_action(self) -> None:
        self.assertNotIn("person_hazard_action", type(ph.settings).__dataclass_fields__)

    def test_rejects_raw_detection_fields(self) -> None:
        payload = _fresh_advisory()
        payload["event"]["bbox"] = [1, 2, 3, 4]
        with self.assertRaises(ValueError):
            ph.validate_hazard_payload(payload)

    def test_rejects_motion_command_strings(self) -> None:
        payload = _fresh_advisory()
        payload["event"]["note"] = "E_STOP"
        with self.assertRaises(ValueError):
            ph.validate_hazard_payload(payload)

    def test_stale_advisory_skips_evidence(self) -> None:
        old = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
        runtime = ph.MonitorRuntime(robot_id="tb3_1", source="tb3_1_picam", task_id=101)
        conn = MagicMock()
        repo = MagicMock()
        with patch("app.services.person_hazard.evidence_repo", return_value=repo):
            self.assertFalse(ph.process_advisory(conn, runtime, _fresh_advisory(observed_at=old)))
            repo.append.assert_not_called()

    def test_fresh_advisory_creates_evidence_and_estop(self) -> None:
        runtime = ph.MonitorRuntime(robot_id="tb3_1", source="tb3_1_picam", task_id=101)
        conn = MagicMock()
        repo = MagicMock()
        repo.append.side_effect = [11, 22, 33]
        stop_repo = MagicMock()
        with (
            patch("app.services.person_hazard.evidence_repo", return_value=repo),
            patch("app.services.person_hazard.safety_stop_repo", return_value=stop_repo),
            patch("app.services.person_hazard.movement_client.estop", return_value={"ok": True}) as estop,
            patch("app.services.person_hazard.mark_task_needs_attention"),
        ):
            ok = ph.process_advisory(conn, runtime, _fresh_advisory())
        self.assertTrue(ok)
        estop.assert_called_once_with("tb3_1")
        stop_repo.open_from_evidence.assert_called_once_with(22)
        self.assertEqual(repo.append.call_count, 3)
        self.assertFalse(repo.append.call_args_list[0].kwargs.get("trusted", True))

    def test_legacy_alternate_action_cannot_suppress_estop(self) -> None:
        runtime = ph.MonitorRuntime(robot_id="tb3_1", source="tb3_1_picam", task_id=101)
        conn = MagicMock()
        repo = MagicMock()
        repo.append.side_effect = [11, 22, 33]
        stop_repo = MagicMock()
        with (
            patch("app.services.person_hazard.evidence_repo", return_value=repo),
            patch("app.services.person_hazard.safety_stop_repo", return_value=stop_repo),
            patch("app.services.person_hazard.movement_client.estop", return_value={"ok": True}) as estop,
            patch("app.services.person_hazard.mark_task_needs_attention"),
            patch.object(
                ph,
                "settings",
                SimpleNamespace(
                    person_hazard_action="advisory",
                    person_hazard_cooldown_sec=2.0,
                    person_hazard_stale_sec=2.0,
                ),
            ),
        ):
            ok = ph.process_advisory(conn, runtime, _fresh_advisory())
        self.assertTrue(ok)
        estop.assert_called_once_with("tb3_1")
        stop_repo.open_from_evidence.assert_called_once_with(22)

    def test_duplicate_advisory_respects_cooldown(self) -> None:
        runtime = ph.MonitorRuntime(robot_id="tb3_1", source="tb3_1_picam", task_id=101)
        conn = MagicMock()
        repo = MagicMock()
        repo.append.side_effect = [11, 22, 33, 44]
        with (
            patch("app.services.person_hazard.evidence_repo", return_value=repo),
            patch("app.services.person_hazard.safety_stop_repo"),
            patch("app.services.person_hazard.movement_client.estop", return_value={"ok": True}),
            patch("app.services.person_hazard.mark_task_needs_attention"),
        ):
            ph.process_advisory(conn, runtime, _fresh_advisory())
            ph.process_advisory(conn, runtime, _fresh_advisory())
        self.assertEqual(repo.append.call_count, 3)

    def test_enable_failure_is_reported_to_the_dispatcher(self) -> None:
        """A move must not be dispatched unless its monitor was armed."""
        with (
            patch("app.services.person_hazard.put_person_monitor_state", side_effect=ph.VisionUpstreamError("down")),
            patch.object(ph, "settings", person_hazard_enabled=True, person_hazard_target_fps=3),
        ):
            self.assertFalse(ph.enable_monitor("tb3_1", 101, command_id="cmd-1"))
        self.assertIsNone(ph.get_runtime("tb3_1"))

    def test_poll_failure_fails_safe_once_with_untrusted_outage_and_trusted_stop(self) -> None:
        runtime = ph.MonitorRuntime(robot_id="tb3_1", source="tb3_1_picam", task_id=101)
        conn = MagicMock()
        repo = MagicMock()
        repo.append.side_effect = [11, 22, 33]
        stop_repo = MagicMock()
        with (
            patch("app.services.person_hazard.evidence_repo", return_value=repo),
            patch("app.services.person_hazard.safety_stop_repo", return_value=stop_repo),
            patch("app.services.person_hazard.movement_client.estop", return_value={"ok": True}) as estop,
            patch("app.services.person_hazard.mark_task_needs_attention") as hold,
            patch("app.services.person_hazard.fetch_person_hazard_latest", side_effect=ph.VisionUpstreamError("down")),
        ):
            ph.poll_robot(conn, runtime)
            ph.poll_robot(conn, runtime)

        self.assertTrue(runtime.fail_safe_triggered)
        self.assertEqual(repo.append.call_count, 3)
        self.assertFalse(repo.append.call_args_list[0].kwargs["trusted"])
        self.assertTrue(repo.append.call_args_list[1].kwargs["trusted"])
        estop.assert_called_once_with("tb3_1")
        stop_repo.open_from_evidence.assert_called_once_with(22)
        hold.assert_called_once_with(conn, 101, reason="person_monitor_outage", robot_id="tb3_1")

    def test_poll_failure_commits_hold_before_unexpected_estop_error(self) -> None:
        runtime = ph.MonitorRuntime(robot_id="tb3_1", source="tb3_1_picam", task_id=101)
        conn = MagicMock()
        repo = MagicMock()
        repo.append.side_effect = [11, 22, 33]
        stop_repo = MagicMock()

        def unexpected_estop(_robot_id: str):
            self.assertEqual(conn.commit.call_count, 1)
            raise RuntimeError("unexpected movement failure")

        with (
            patch("app.services.person_hazard.evidence_repo", return_value=repo),
            patch("app.services.person_hazard.safety_stop_repo", return_value=stop_repo),
            patch("app.services.person_hazard.movement_client.estop", side_effect=unexpected_estop),
            patch("app.services.person_hazard.mark_task_needs_attention") as hold,
            patch("app.services.person_hazard.fetch_person_hazard_latest", side_effect=ph.VisionUpstreamError("down")),
        ):
            ph.poll_robot(conn, runtime)

        self.assertTrue(runtime.fail_safe_triggered)
        hold.assert_called_once_with(conn, 101, reason="person_monitor_outage", robot_id="tb3_1")
        stop_repo.open_from_evidence.assert_called_once_with(22)
        self.assertEqual(
            [call.kwargs["event_type"] for call in repo.append.call_args_list],
            ["PERSON_MONITOR_HEALTH_FAILURE", "SAFETY_ESTOP_DECISION", "SAFETY_ESTOP_OUTCOME"],
        )
        outcome = repo.append.call_args_list[2].kwargs["data_json"]
        self.assertFalse(outcome["estop_ok"])
        self.assertIn("unexpected movement failure", outcome["estop_error"])
        self.assertEqual(conn.commit.call_count, 2)

    def test_invalid_estop_response_is_recorded_unknown_after_durable_hazard_hold(self) -> None:
        runtime = ph.MonitorRuntime(robot_id="tb3_1", source="tb3_1_picam", task_id=101)
        conn = MagicMock()
        repo = MagicMock()
        repo.append.side_effect = [11, 22, 33]
        stop_repo = MagicMock()
        with (
            patch("app.services.person_hazard.evidence_repo", return_value=repo),
            patch("app.services.person_hazard.safety_stop_repo", return_value=stop_repo),
            patch("app.services.person_hazard.movement_client.estop", return_value=["not", "an", "object"]),
            patch("app.services.person_hazard.mark_task_needs_attention") as hold,
        ):
            ok = ph.process_advisory(conn, runtime, _fresh_advisory())

        self.assertFalse(ok)
        hold.assert_called_once_with(conn, 101, reason="person_hazard", robot_id="tb3_1")
        stop_repo.open_from_evidence.assert_called_once_with(22)
        outcome = repo.append.call_args_list[2].kwargs["data_json"]
        self.assertFalse(outcome["estop_ok"])
        self.assertIn("invalid estop response", outcome["estop_error"])
        self.assertEqual(conn.commit.call_count, 2)

    def test_failed_hold_commit_does_not_poison_monitor_retry_state(self) -> None:
        runtime = ph.MonitorRuntime(robot_id="tb3_1", source="tb3_1_picam", task_id=101)
        conn = MagicMock()
        conn.commit.side_effect = RuntimeError("database commit failed")
        repo = MagicMock()
        repo.append.side_effect = [11, 22]
        with (
            patch("app.services.person_hazard.evidence_repo", return_value=repo),
            patch("app.services.person_hazard.safety_stop_repo"),
            patch("app.services.person_hazard.movement_client.estop") as estop,
            patch("app.services.person_hazard.mark_task_needs_attention"),
        ):
            with self.assertRaisesRegex(RuntimeError, "database commit failed"):
                ph.fail_safe_monitor_outage(
                    conn,
                    "tb3_1",
                    101,
                    detail="poll_failed",
                    runtime=runtime,
                )

        self.assertFalse(runtime.fail_safe_triggered)
        self.assertTrue(runtime.enabled)
        estop.assert_called_once_with("tb3_1")

    def test_poll_once_commits_each_robot_before_next_remote_poll(self) -> None:
        conn = MagicMock()
        runtimes = [
            ph.MonitorRuntime(robot_id="tb3_1", source="tb3_1_picam", task_id=101),
            ph.MonitorRuntime(robot_id="tb3_2", source="tb3_2_picam", task_id=102),
        ]

        def poll(_conn, runtime):
            if runtime.robot_id == "tb3_2":
                self.assertEqual(conn.commit.call_count, 1)

        with (
            patch.object(ph, "settings", person_hazard_enabled=True),
            patch.object(ph, "active_monitors", return_value=runtimes),
            patch.object(ph, "poll_robot", side_effect=poll) as poll_robot,
        ):
            self.assertEqual(ph.poll_once(conn), 2)

        self.assertEqual(poll_robot.call_count, 2)
        self.assertEqual(conn.commit.call_count, 2)

    def test_post_dispatch_enable_failure_immediately_fails_safe(self) -> None:
        conn = MagicMock()
        with (
            patch.object(ph, "enable_monitor", return_value=False),
            patch.object(ph, "fail_safe_monitor_outage") as fail_safe,
        ):
            self.assertFalse(ph.on_move_to_point_dispatched(conn, 101, "tb3_1", "cmd-1"))
        fail_safe.assert_called_once_with(conn, "tb3_1", 101, detail="monitor_enable_failed_after_dispatch")


class OrchestratorPersonMonitorTest(unittest.TestCase):
    def _task(self) -> dict:
        return {
            "task_id": 101,
            "assigned_robot_id": "tb3_1",
            "preset_snapshot": {"_orchestration": {
                "phase": "RUNNING", "step_index": 0,
                "steps": [{"kind": "move_to_point", "status": "pending", "params": {"x": 1, "y": 2}}],
            }},
        }

    def test_enable_failure_before_dispatch_does_not_send_motion(self) -> None:
        task = self._task()
        conn = MagicMock()
        with (
            patch.object(orchestrator, "_task", side_effect=lambda *_: copy.deepcopy(task)),
            patch.object(orchestrator, "task_repo"),
            patch.object(orchestrator.evidence_runtime, "resolve_command_def_id", return_value=1),
            patch.object(orchestrator.command_service, "default_command_id", return_value="cmd-1"),
            patch.object(orchestrator.person_hazard, "arm_physical_motion_monitor", return_value=False) as arm,
            patch.object(orchestrator.command_service, "dispatch_robot_command") as dispatch,
        ):
            with self.assertRaises(HTTPException) as raised:
                orchestrator.dispatch_current_step(conn, 101)
        self.assertEqual(raised.exception.status_code, 503)
        conn.commit.assert_called_once_with()
        dispatch.assert_not_called()
        arm.assert_called_once()
        self.assertEqual(arm.call_args.args[:3], (conn, "tb3_1", 101))
        self.assertEqual(arm.call_args.args[-1], "move_to_point")

    def test_healthy_monitor_allows_motion_dispatch(self) -> None:
        task = self._task()
        conn = MagicMock()
        accepted = RobotCommandResponse(command_id="cmd-1", robot_id="tb3_1", kind="move_to_point", accepted=True)
        with (
            patch.object(orchestrator, "_task", side_effect=lambda *_: copy.deepcopy(task)),
            patch.object(orchestrator, "task_repo"),
            patch.object(orchestrator.evidence_runtime, "resolve_command_def_id", return_value=1),
            patch.object(orchestrator.evidence_runtime, "save_orchestration"),
            patch.object(orchestrator.evidence_runtime, "record_movement_evidence"),
            patch.object(orchestrator.command_service, "default_command_id", return_value="cmd-1"),
            patch.object(orchestrator.person_hazard, "arm_physical_motion_monitor", return_value=True),
            patch.object(orchestrator.command_service, "dispatch_robot_command", return_value=accepted) as dispatch,
        ):
            self.assertEqual(orchestrator.dispatch_current_step(conn, 101), "cmd-1")
        dispatch.assert_called_once()

    def test_every_physical_motion_leg_requires_monitor_arm_before_dispatch(self) -> None:
        accepted = RobotCommandResponse(command_id="cmd-1", robot_id="tb3_1", kind="move_to_point", accepted=True)
        for kind in ("move_to_point", "aruco_align", "dock_transfer", "leave_dock"):
            task = self._task()
            task["preset_snapshot"]["_orchestration"]["steps"][0]["kind"] = kind
            conn = MagicMock()
            with (
                patch.object(orchestrator, "_task", side_effect=lambda *_: copy.deepcopy(task)),
                patch.object(orchestrator, "task_repo"),
                patch.object(orchestrator.evidence_runtime, "resolve_command_def_id", return_value=1),
                patch.object(orchestrator.evidence_runtime, "save_orchestration"),
                patch.object(orchestrator.evidence_runtime, "record_movement_evidence"),
                patch.object(orchestrator.command_service, "default_command_id", return_value="cmd-1"),
                patch.object(orchestrator.person_hazard, "arm_physical_motion_monitor", return_value=True) as arm,
                patch.object(orchestrator.command_service, "dispatch_robot_command", return_value=accepted),
            ):
                orchestrator.dispatch_current_step(conn, 101)
            arm.assert_called_once()
            self.assertEqual(arm.call_args.args[:3], (conn, "tb3_1", 101))
            self.assertEqual(arm.call_args.args[-1], kind)

    def test_monitor_is_retained_for_every_docking_motion_stage(self) -> None:
        """A detection during align/lift/reverse remains covered by one monitor."""
        ph._runtime.clear()
        conn = MagicMock()
        with patch.object(ph, "put_person_monitor_state", return_value={}) as put:
            self.assertTrue(ph.arm_physical_motion_monitor(conn, "tb3_1", 101, "move", "move_to_point"))
            for command_id, kind in (
                ("align", "aruco_align"),
                ("dock", "dock_transfer"),
                ("leave", "leave_dock"),
            ):
                self.assertTrue(ph.arm_physical_motion_monitor(conn, "tb3_1", 101, command_id, kind))
                self.assertEqual(ph.get_runtime("tb3_1").last_leg_kind, kind)
        self.assertEqual(put.call_count, 1)
        self.assertEqual(ph.get_runtime("tb3_1").last_command_id, "leave")

    def test_detection_during_align_lift_and_reverse_still_estops(self) -> None:
        conn = MagicMock()
        repo = MagicMock()
        repo.append.side_effect = range(1, 20)
        stop_repo = MagicMock()
        with (
            patch.object(ph, "put_person_monitor_state", return_value={}),
            patch("app.services.person_hazard.evidence_repo", return_value=repo),
            patch("app.services.person_hazard.safety_stop_repo", return_value=stop_repo),
            patch("app.services.person_hazard.mark_task_needs_attention"),
            patch("app.services.person_hazard.movement_client.estop", return_value={}) as estop,
        ):
            self.assertTrue(ph.arm_physical_motion_monitor(conn, "tb3_1", 101, "move", "move_to_point"))
            for index, (command_id, kind) in enumerate(
                (("align", "aruco_align"), ("lift", "dock_transfer"), ("reverse", "dock_transfer")),
                start=1,
            ):
                self.assertTrue(ph.arm_physical_motion_monitor(conn, "tb3_1", 101, command_id, kind))
                payload = _fresh_advisory()
                payload["event"]["data_json"]["source_event_id"] = f"stage-{index}"
                self.assertTrue(ph.process_advisory(conn, ph.get_runtime("tb3_1"), payload))
                ph._cooldown_until.clear()
        self.assertEqual(estop.call_count, 3)


if __name__ == "__main__":
    unittest.main()
