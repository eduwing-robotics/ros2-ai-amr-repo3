"""Unit tests for person hazard policy."""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from app.domains.safety import hazard as ph


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
        ph._pending_estops.clear()
        ph._last_reconcile_at = 0.0

    def test_reconcile_restores_dispatched_move_monitor(self) -> None:
        task = {
            "task_id": 101,
            "assigned_robot_id": "tb3_1",
            "preset_snapshot": {
                "_orchestration": {
                    "steps": [{"kind": "move_to_point", "status": "dispatched", "command_id": "cmd-1"}],
                    "step_index": 0,
                }
            },
        }
        with (
            patch.object(ph.evidence_runtime, "list_orchestrated_running", return_value=[task]),
            patch.object(ph, "enable_monitor") as enable,
            patch.object(ph, "get_runtime", side_effect=[None, ph.MonitorRuntime("tb3_1", "tb3_1_picam", 101)]),
        ):
            restored = ph.reconcile_active_monitors(MagicMock(), force=True)
        self.assertEqual(restored, 1)
        enable.assert_called_once_with("tb3_1", 101, command_id="cmd-1")

    def test_reconcile_ignores_non_movement_step(self) -> None:
        task = {
            "task_id": 101,
            "assigned_robot_id": "tb3_1",
            "preset_snapshot": {"_orchestration": {"steps": [{"kind": "dock_transfer", "status": "dispatched"}]}},
        }
        with (
            patch.object(ph.evidence_runtime, "list_orchestrated_running", return_value=[task]),
            patch.object(ph, "enable_monitor") as enable,
        ):
            self.assertEqual(ph.reconcile_active_monitors(MagicMock(), force=True), 0)
        enable.assert_not_called()

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
        with patch("app.domains.safety.hazard.evidence_repo", return_value=repo):
            self.assertFalse(ph.process_advisory(conn, runtime, _fresh_advisory(observed_at=old)))
            repo.append.assert_not_called()

    def test_fresh_advisory_creates_evidence_and_estop(self) -> None:
        runtime = ph.MonitorRuntime(robot_id="tb3_1", source="tb3_1_picam", task_id=101)
        conn = MagicMock()
        repo = MagicMock()
        repo.append.side_effect = [11, 22]
        stop_repo = MagicMock()
        with (
            patch("app.domains.safety.hazard.evidence_repo", return_value=repo),
            patch("app.domains.safety.hazard.safety_stop_repo", return_value=stop_repo),
            patch("app.domains.safety.hazard.movement_client.estop", return_value={"ok": True}) as estop,
            patch("app.domains.safety.hazard.mark_task_awaiting_operator"),
        ):
            ok = ph.process_advisory(conn, runtime, _fresh_advisory())
        self.assertTrue(ok)
        estop.assert_called_once_with("tb3_1")
        stop_repo.open_from_evidence.assert_called_once_with(22)
        self.assertEqual(repo.append.call_count, 2)
        self.assertFalse(repo.append.call_args_list[0].kwargs.get("trusted", True))

    def test_duplicate_advisory_respects_cooldown(self) -> None:
        runtime = ph.MonitorRuntime(robot_id="tb3_1", source="tb3_1_picam", task_id=101)
        conn = MagicMock()
        repo = MagicMock()
        repo.append.side_effect = [11, 22, 33, 44]
        with (
            patch("app.domains.safety.hazard.evidence_repo", return_value=repo),
            patch("app.domains.safety.hazard.safety_stop_repo"),
            patch("app.domains.safety.hazard.movement_client.estop", return_value={"ok": True}),
            patch("app.domains.safety.hazard.mark_task_awaiting_operator"),
        ):
            ph.process_advisory(conn, runtime, _fresh_advisory())
            ph.process_advisory(conn, runtime, _fresh_advisory())
        self.assertEqual(repo.append.call_count, 2)

    def test_failed_estop_is_retried_until_confirmed(self) -> None:
        runtime = ph.MonitorRuntime(robot_id="tb3_1", source="tb3_1_picam", task_id=101)
        conn = MagicMock()
        repo = MagicMock()
        repo.append.side_effect = [11, 22, 33]
        with (
            patch("app.domains.safety.hazard.evidence_repo", return_value=repo),
            patch("app.domains.safety.hazard.safety_stop_repo"),
            patch(
                "app.domains.safety.hazard.movement_client.estop",
                side_effect=[ph.MovementClientError("offline"), {"ok": True}],
            ) as estop,
            patch("app.domains.safety.hazard.mark_task_awaiting_operator"),
        ):
            self.assertFalse(ph.process_advisory(conn, runtime, _fresh_advisory()))
            self.assertEqual(ph._pending_estops, {"tb3_1": 101})
            self.assertEqual(ph.retry_pending_estops(conn), 1)
        self.assertEqual(estop.call_count, 2)
        self.assertFalse(ph._pending_estops)
        self.assertEqual(repo.append.call_args_list[-1].kwargs["event_type"], "SAFETY_ESTOP_CONFIRMED")


if __name__ == "__main__":
    unittest.main()
