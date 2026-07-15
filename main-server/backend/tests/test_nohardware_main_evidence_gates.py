"""No-hardware Main evidence gate regression tests."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.models.schemas import RobotCommandResponse
from app.services import evidence_runtime, orchestrator, person_hazard


def _task_with_orchestration(*, step_index: int, steps: list[dict]) -> dict:
    return {
        "task_id": 9001,
        "status": "RUNNING",
        "assigned_robot_id": "tb3_1",
        "item_id": "BOX-A",
        "preset_snapshot": {
            "_orchestration": {
                "phase": "RUNNING",
                "step_index": step_index,
                "cursor": step_index,
                "steps": steps,
                "legs": steps,
            }
        },
    }


def _lift_gate_settings() -> SimpleNamespace:
    return SimpleNamespace(
        lift_load_evidence_enabled=True,
        lift_load_evidence_mode="gate",
        lift_load_evidence_source="global_cam_01",
        lift_load_marker_map={"BOX-A": "20"},
        lift_load_burst_frames=5,
        lift_load_min_pass_frames=1,
        lift_load_sample_interval_ms=80,
        lift_load_max_frame_age_s=2.0,
        lift_load_evidence_max_age_s=5.0,
        lift_load_evidence_clock_skew_s=1.0,
    )


class MainChargeScenarioNoHardwareTest(unittest.TestCase):
    def test_nohardware_charge_scenario_uses_leave_dock_scan_and_charge_aruco_align(self):
        conn = MagicMock()

        def get_location(location_id):
            rows = {
                "CHARGE_01": {
                    "location_id": "CHARGE_01",
                    "slot_id": "CHARGE_01",
                    "type": "charge",
                    "x": -1.0,
                    "y": 0.0,
                    "yaw": 0.0,
                    "marker_id": 3,
                },
                "vehicle_2_approach": {
                    "location_id": "vehicle_2_approach",
                    "slot_id": "vehicle_2_approach",
                    "type": "scan",
                    "x": -0.8,
                    "y": 0.0,
                    "yaw": 1.57,
                    "marker_id": 4,
                },
            }
            return rows.get(location_id)

        with (
            patch.object(evidence_runtime, "settings", SimpleNamespace(movement_active_map_id="robot2_map")),
            patch.object(evidence_runtime, "location_repo") as location_repo,
        ):
            location_repo.return_value.get.side_effect = get_location
            location_repo.return_value.list_by_type.return_value = []

            scenario = evidence_runtime.build_scenario_from_task(
                conn,
                {
                    "task_id": 9100,
                    "task_type": "CHARGE",
                    "assigned_robot_id": "tb3_1",
                    "to_location_id": "CHARGE_01",
                },
            )

        steps = scenario["steps"]
        self.assertGreaterEqual(len(steps), 3)
        self.assertEqual(steps[0]["action_type"], "leave_dock")
        self.assertEqual(steps[1]["action_type"], "move")
        self.assertIn("scan", steps[1]["name"].lower())
        self.assertEqual(steps[1]["waypoint_id"], "vehicle_2_approach")
        self.assertEqual(steps[2]["action_type"], "aruco_align")
        self.assertEqual(steps[2]["params"], {"aruco_marker_id": 4, "final": "charge"})
        self.assertNotEqual(steps[-1]["action_type"], "move", "CHARGE must not end as a generic move without ArUco final alignment")


class MainUnloadEvidenceGateNoHardwareTest(unittest.TestCase):
    def _dispatch_unload_with_evidence(self, evidence_result):
        conn = MagicMock()
        steps = [
            {"kind": "move_to_point", "status": "DONE", "command_id": "cmd-move", "params": {"map_id": "m", "x": 1, "y": 2}},
            {
                "kind": "dock_transfer",
                "status": "pending",
                "command_id": None,
                "params": {"action": "unload", "aruco_marker_id": 7, "level": 1},
            },
        ]
        task = _task_with_orchestration(step_index=1, steps=steps)
        with (
            patch.object(orchestrator, "task_repo") as task_repo,
            patch.object(orchestrator, "robot_repo") as robot_repo,
            patch.object(orchestrator, "evidence_runtime") as runtime,
            patch.object(orchestrator.lift_load_evidence, "evaluate_and_record", return_value=evidence_result) as evaluate,
            patch.object(orchestrator.person_hazard, "arm_physical_motion_monitor", return_value=True),
            patch.object(orchestrator.command_service, "dispatch_robot_command") as dispatch,
        ):
            task_repo.return_value.get.return_value = task
            robot_repo.return_value.exists.return_value = True
            runtime.attach_orchestration.side_effect = lambda row, _conn: row
            runtime.resolve_command_def_id.return_value = 44
            dispatch.return_value = RobotCommandResponse(
                command_id="cmd-unload",
                robot_id="tb3_1",
                kind="dock_transfer",
                accepted=True,
            )
            try:
                result = orchestrator.dispatch_current_step(conn, 9001)
                raised = None
            except HTTPException as exc:
                result = None
                raised = exc
        return result, raised, evaluate, dispatch, runtime

    def test_nohardware_unload_dispatches_only_after_ai_evidence_pass_and_command_satisfying_true(self):
        result, raised, evaluate, dispatch, _ = self._dispatch_unload_with_evidence(
            {"advisory_evidence_id": 501, "result": "PASS", "command_satisfying": True}
        )

        self.assertIsNone(raised)
        self.assertEqual(result, "cmd-unload")
        evaluate.assert_called_once()
        dispatch.assert_called_once()

    def test_nohardware_unload_pre_dispatch_calls_pre_drop_off_evidence_without_nav_param_leak(self):
        conn = MagicMock()
        repo = MagicMock()
        repo.append.return_value = 777
        steps = [
            {"kind": "move_to_point", "status": "DONE", "command_id": "cmd-move", "params": {"map_id": "m", "x": 1, "y": 2}},
            {
                "kind": "dock_transfer",
                "status": "pending",
                "command_id": None,
                "params": {"action": "unload", "aruco_marker_id": 7, "level": 1},
            },
        ]
        task = _task_with_orchestration(step_index=1, steps=steps)
        task.update({"task_type": "INBOUND", "to_floor": 1, "quantity": 1})
        response = {
            "schema_version": "vision-lift-load-evaluate.v1",
            "monitor_id": "lift_evidence",
            "source": "global_cam_01",
            "robot_id": "tb3_1",
            "task_id": 9001,
            "command_id": 44,
            "operation": "PRE_DROP_OFF",
            "vision_zone_id": "storage_lower_static_item_zone",
            "result": "PASS",
            "reason_code": "PRE_DROP_OFF_CLEAR",
            "event": {
                "schema_version": "vision-monitor-event.v1",
                "event_type": "ITEM_PLACEMENT_READY",
                "source": "global_cam_01",
                "robot_id": "tb3_1",
                "task_id": 9001,
                "command_id": 44,
                "result": "PASS",
                "trusted": False,
                "observed_at": datetime.now(timezone.utc).isoformat(),
                "data_json": {
                    "result": "PASS",
                    "expected_item_id": "BOX-A",
                    "expected_marker_ids": ["ARUCO_4X4_50_20"],
                    "expected_item_count": 1,
                    "vision_zone_id": "storage_lower_static_item_zone",
                    "operation": "PRE_DROP_OFF",
                    "command_satisfying": True,
                },
            },
        }
        with (
            patch.object(orchestrator, "task_repo") as task_repo,
            patch.object(orchestrator, "robot_repo") as robot_repo,
            patch.object(orchestrator, "evidence_runtime") as runtime,
            patch.object(orchestrator.command_service, "dispatch_robot_command") as dispatch,
            patch.object(orchestrator.person_hazard, "arm_physical_motion_monitor", return_value=True),
            patch.object(orchestrator.lift_load_evidence, "settings", _lift_gate_settings()),
            patch.object(orchestrator.lift_load_evidence, "post_lift_load_evaluate", return_value=response) as post,
            patch.object(orchestrator.lift_load_evidence, "evidence_repo", return_value=repo),
            patch.object(orchestrator.person_hazard, "arm_physical_motion_monitor", return_value=True),
        ):
            task_repo.return_value.get.return_value = task
            robot_repo.return_value.exists.return_value = True
            runtime.attach_orchestration.side_effect = lambda row, _conn: row
            runtime.resolve_command_def_id.return_value = 44
            dispatch.return_value = RobotCommandResponse(
                command_id="cmd-unload",
                robot_id="tb3_1",
                kind="dock_transfer",
                accepted=True,
            )

            result = orchestrator.dispatch_current_step(conn, 9001)

        self.assertEqual(result, "cmd-unload")
        self.assertEqual(post.call_args.args[0]["operation"], "PRE_DROP_OFF")
        nav_payload = dispatch.call_args.args[1]
        self.assertNotIn("evidence_operation", nav_payload.params)
        self.assertEqual(nav_payload.params["action"], "unload")

    def test_nohardware_unload_fail_holds_without_dispatching_lift_down(self):
        _, raised, evaluate, dispatch, runtime = self._dispatch_unload_with_evidence(
            {"advisory_evidence_id": 502, "result": "FAIL", "command_satisfying": False}
        )

        self.assertIsNotNone(raised)
        self.assertEqual(raised.status_code, 409)
        evaluate.assert_called_once()
        dispatch.assert_not_called()
        saved_orch = runtime.save_orchestration.call_args[0][2]
        self.assertIn(saved_orch["phase"], {"AWAITING_OPERATOR", "NEEDS_ATTENTION"})


class MainLoadTrustedGateDecisionNoHardwareTest(unittest.TestCase):
    def test_nohardware_load_ai_advisory_records_main_trusted_gate_decision_before_dispatch(self):
        conn = MagicMock()
        steps = [
            {
                "kind": "dock_transfer",
                "status": "dispatched",
                "command_id": "cmd-load",
                "params": {"action": "load", "aruco_marker_id": 7, "level": 1},
            },
            {"kind": "move_to_point", "status": "pending", "command_id": None, "params": {"map_id": "m", "x": 1, "y": 2}},
        ]
        task = _task_with_orchestration(step_index=0, steps=steps)
        with (
            patch.object(orchestrator, "task_repo") as task_repo,
            patch.object(orchestrator, "evidence_runtime") as runtime,
            patch.object(orchestrator, "event_repo"),
            patch.object(orchestrator, "dispatch_current_step", return_value="cmd-next") as dispatch,
            patch.object(
                orchestrator.lift_load_evidence,
                "evaluate_and_record",
                return_value={"advisory_evidence_id": 601, "result": "PASS", "command_satisfying": True},
            ),
        ):
            task_repo.return_value.get.return_value = task
            runtime.attach_orchestration.side_effect = lambda row, _conn: row
            runtime.resolve_command_def_id.return_value = 12

            orchestrator.advance_task(conn, 9001, {"event": "DONE", "command_id": "cmd-load"})

        decision_calls = [
            call for call in runtime.record_movement_evidence.call_args_list
            if call.kwargs.get("event_type") == "LIFT_LOAD_GATE_DECISION"
        ]
        self.assertEqual(len(decision_calls), 1)
        decision = decision_calls[0].kwargs
        self.assertTrue(decision["trusted"])
        self.assertEqual(decision["source"], "main_gate_policy")
        self.assertEqual(decision["data_json"]["advisory_evidence_id"], 601)
        self.assertEqual(decision["data_json"]["decision"], "PASS")
        self.assertTrue(decision["data_json"]["command_satisfying"])
        dispatch.assert_called_once_with(conn, 9001)


class MainLoadEvidenceGateNoHardwareTest(unittest.TestCase):
    def _run_load_done(self, evidence_result):
        conn = MagicMock()
        steps = [
            {
                "kind": "dock_transfer",
                "status": "dispatched",
                "command_id": "cmd-load",
                "params": {"action": "load", "aruco_marker_id": 7, "level": 1},
            },
            {"kind": "move_to_point", "status": "pending", "command_id": None, "params": {"map_id": "m", "x": 1, "y": 2}},
        ]
        task = _task_with_orchestration(step_index=0, steps=steps)
        patches = [
            patch.object(orchestrator, "task_repo"),
            patch.object(orchestrator, "evidence_runtime"),
            patch.object(orchestrator, "event_repo"),
            patch.object(orchestrator, "dispatch_current_step", return_value="cmd-next"),
        ]
        with patches[0] as task_repo, patches[1] as evidence_runtime, patches[2], patches[3] as dispatch:
            task_repo.return_value.get.return_value = task
            evidence_runtime.attach_orchestration.side_effect = lambda row, _conn: row
            evidence_runtime.resolve_command_def_id.return_value = 12
            if isinstance(evidence_result, BaseException):
                evidence_patch = patch.object(orchestrator.lift_load_evidence, "evaluate_and_record", side_effect=evidence_result)
            else:
                evidence_patch = patch.object(orchestrator.lift_load_evidence, "evaluate_and_record", return_value=evidence_result)
            with evidence_patch:
                result = orchestrator.advance_task(conn, 9001, {"event": "DONE", "command_id": "cmd-load"})
        return result, dispatch, evidence_runtime

    def test_nohardware_load_pass_dispatches_next_step_after_ai_evidence_pass(self):
        _, dispatch, _ = self._run_load_done({"result": "PASS", "command_satisfying": True})

        dispatch.assert_called_once_with(unittest.mock.ANY, 9001)

    def test_nohardware_load_fail_holds_task_without_dispatching_next_step(self):
        _, dispatch, evidence_runtime = self._run_load_done({"result": "FAIL", "command_satisfying": False})

        dispatch.assert_not_called()
        saved_orch = evidence_runtime.save_orchestration.call_args[0][2]
        self.assertIn(saved_orch["phase"], {"AWAITING_OPERATOR", "NEEDS_ATTENTION"})

    def test_nohardware_load_uncertain_holds_task_without_dispatching_next_step(self):
        _, dispatch, evidence_runtime = self._run_load_done({"result": "UNCERTAIN", "command_satisfying": False})

        dispatch.assert_not_called()
        saved_orch = evidence_runtime.save_orchestration.call_args[0][2]
        self.assertIn(saved_orch["phase"], {"AWAITING_OPERATOR", "NEEDS_ATTENTION"})

    def test_nohardware_load_evidence_error_holds_task_without_dispatching_next_step(self):
        _, dispatch, evidence_runtime = self._run_load_done(RuntimeError("ai evidence unavailable"))

        dispatch.assert_not_called()
        saved_orch = evidence_runtime.save_orchestration.call_args[0][2]
        self.assertIn(saved_orch["phase"], {"AWAITING_OPERATOR", "NEEDS_ATTENTION"})


class LegacyLoadOrchestrationNoHardwareTest(unittest.TestCase):
    def test_nohardware_legacy_inout_load_completion_requires_migration_before_next_dispatch(self):
        """A legacy legs/cursor state must not bypass POST_PICK_UP gating."""
        for task_type in ("INBOUND", "OUTBOUND"):
            with self.subTest(task_type=task_type):
                conn = MagicMock()
                legs = [
                    {
                        "kind": "dock_transfer",
                        "status": "dispatched",
                        "command_id": "cmd-load",
                        "params": {"action": "load", "aruco_marker_id": 7, "level": 1},
                    },
                    {
                        "kind": "move_to_point",
                        "status": "pending",
                        "command_id": None,
                        "params": {"map_id": "m", "x": 1, "y": 2},
                    },
                ]
                task = {
                    "task_id": 9001,
                    "status": "RUNNING",
                    "task_type": task_type,
                    "assigned_robot_id": "tb3_1",
                    "item_id": "BOX-A",
                    "preset_snapshot": {
                        "_orchestration": {"phase": "RUNNING", "cursor": 0, "legs": legs}
                    },
                }
                with (
                    patch.object(orchestrator, "task_repo") as task_repo,
                    patch.object(orchestrator, "evidence_runtime") as runtime,
                    patch.object(orchestrator, "event_repo"),
                    patch.object(orchestrator, "dispatch_current_step") as dispatch,
                    patch.object(orchestrator.lift_load_evidence, "evaluate_and_record") as evaluate,
                ):
                    task_repo.return_value.get.return_value = task
                    runtime.attach_orchestration.side_effect = lambda row, _conn: row
                    runtime.resolve_command_def_id.return_value = 12

                    orchestrator.advance_task(conn, 9001, {"event": "DONE", "command_id": "cmd-load"})

                dispatch.assert_not_called()
                evaluate.assert_not_called()
                saved_orch = runtime.save_orchestration.call_args.args[2]
                self.assertEqual(saved_orch["phase"], "AWAITING_OPERATOR")
                self.assertEqual(saved_orch["recovery"]["reason"], "orchestration_migration_required")


class MainUnloadApprovalBoundaryNoHardwareTest(unittest.TestCase):
    def test_nohardware_unload_lift_down_requires_main_evidence_pass_before_dispatch(self):
        conn = MagicMock()
        steps = [
            {"kind": "move_to_point", "status": "DONE", "command_id": "cmd-move", "params": {"map_id": "m", "x": 1, "y": 2}},
            {
                "kind": "dock_transfer",
                "status": "pending",
                "command_id": None,
                "params": {"action": "unload", "aruco_marker_id": 7, "level": 1},
            },
        ]
        task = _task_with_orchestration(step_index=1, steps=steps)
        with (
            patch.object(orchestrator, "task_repo") as task_repo,
            patch.object(orchestrator, "robot_repo") as robot_repo,
            patch.object(orchestrator, "evidence_runtime") as evidence_runtime,
            patch.object(orchestrator.command_service, "dispatch_robot_command") as dispatch,
        ):
            task_repo.return_value.get.return_value = task
            robot_repo.return_value.exists.return_value = True
            evidence_runtime.attach_orchestration.side_effect = lambda row, _conn: row
            evidence_runtime.resolve_command_def_id.return_value = 44
            dispatch.return_value = RobotCommandResponse(
                command_id="cmd-unload",
                robot_id="tb3_1",
                kind="dock_transfer",
                accepted=True,
            )

            with self.assertRaises(HTTPException) as ctx:
                orchestrator.dispatch_current_step(conn, 9001)

        self.assertEqual(ctx.exception.status_code, 409)
        dispatch.assert_not_called()


class PersonHazardTrustedDecisionNoHardwareTest(unittest.TestCase):
    def setUp(self) -> None:
        person_hazard._runtime.clear()
        person_hazard._cooldown_until.clear()

    def test_nohardware_human_detected_advisory_creates_main_trusted_estop_decision(self):
        conn = MagicMock()
        repo = MagicMock()
        repo.append.side_effect = [101, 202, 303]
        stop_repo = MagicMock()
        runtime = person_hazard.MonitorRuntime(robot_id="tb3_1", source="tb3_1_picam", task_id=9001)
        runtime.enable_time = datetime.now(timezone.utc) - timedelta(seconds=1)
        observed_at = datetime.now(timezone.utc).isoformat()
        payload = {
            "result": "ADVISORY",
            "reason_code": "HUMAN_DETECTED",
            "event": {
                "event_id": "evt-human-1",
                "event_type": "HUMAN_DETECTED",
                "source": "tb3_1_picam",
                "robot_id": "tb3_1",
                "task_id": 9001,
                "result": "ADVISORY",
                "severity": "CRITICAL",
                "confidence": 0.91,
                "reason_code": "HUMAN_DETECTED",
                "trusted": False,
                "observed_at": observed_at,
                "data_json": {"source_event_id": "vision-human-1"},
            },
        }
        with (
            patch.object(person_hazard, "evidence_repo", return_value=repo),
            patch.object(person_hazard, "safety_stop_repo", return_value=stop_repo),
            patch.object(person_hazard, "movement_client") as movement_client,
            patch.object(person_hazard, "mark_task_needs_attention") as mark_attention,
            patch.object(person_hazard, "settings", SimpleNamespace(person_hazard_cooldown_sec=30.0, person_hazard_stale_sec=5.0)),
        ):
            movement_client.estop.return_value = {"ok": True}
            ok = person_hazard.process_advisory(conn, runtime, payload)

        self.assertTrue(ok)
        movement_client.estop.assert_called_once_with("tb3_1")
        self.assertEqual(repo.append.call_args_list[0].kwargs["event_type"], "HUMAN_DETECTED")
        self.assertFalse(repo.append.call_args_list[0].kwargs["trusted"])
        self.assertEqual(repo.append.call_args_list[1].kwargs["event_type"], "SAFETY_ESTOP_DECISION")
        self.assertTrue(repo.append.call_args_list[1].kwargs["trusted"])
        stop_repo.open_from_evidence.assert_called_once_with(202)
        mark_attention.assert_called_once()


if __name__ == "__main__":
    unittest.main()
