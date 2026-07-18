# 기능 책임: 운영자 복구 command 후속 상태 전이을 검증한다. 비책임: 실장비의 물리 동작.
"""Follow-up UX remediation tests (recovery state close, held task guards)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import HTTPException

from app.domains.execution import orchestrator, recovery


class RecoveryPhaseGuardTest(unittest.TestCase):
    def test_execute_requires_awaiting_operator_phase(self) -> None:
        conn = MagicMock()
        with patch.object(
            recovery,
            "_assert_awaiting_operator_phase",
            side_effect=HTTPException(409, "recovery_requires_awaiting_operator_phase"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                recovery.execute_recovery(
                    conn,
                    1,
                    cargo_state="LOADED",
                    strategy="safe_move",
                    checks={"site_clear": True, "pose_ok": True, "cargo_ok": True},
                )
        self.assertEqual(ctx.exception.detail, "recovery_requires_awaiting_operator_phase")

    def test_rejected_recovery_command_does_not_enter_running_phase(self) -> None:
        conn = MagicMock()
        result = MagicMock(accepted=False, command_id="rec-rejected")
        plan = {"executable": True, "steps": [{"kind": "move_to_point", "params": {"map_id": "m1"}}]}
        with (
            patch.object(recovery, "_assert_awaiting_operator_phase"),
            patch.object(recovery, "save_recovery_decision"),
            patch.object(recovery, "preview_recovery_plan", return_value=plan),
            patch.object(recovery, "_assert_recovery_robot_ready"),
            patch.object(recovery, "tasks") as postgres_tasks,
            patch.object(recovery.commands, "dispatch_robot_command", return_value=result),
            patch.object(recovery.evidence, "save_orchestration") as save,
        ):
            postgres_tasks.get_task.return_value = {"task_id": 1, "assigned_robot_id": "tb3_1"}
            with self.assertRaises(HTTPException) as ctx:
                recovery.execute_recovery(
                    conn,
                    1,
                    cargo_state="LOADED",
                    strategy="safe_move",
                    checks={"site_clear": True, "pose_ok": True, "cargo_ok": True},
                )
        self.assertEqual(ctx.exception.status_code, 502)
        save.assert_not_called()


class RecoveryCommandTerminalTest(unittest.TestCase):
    def test_recovery_move_done_returns_to_awaiting_operator(self) -> None:
        conn = MagicMock()
        task = {
            "task_id": 5,
            "status": "RUNNING",
            "assigned_robot_id": "robot1",
            "preset_snapshot": {
                "_orchestration": {
                    "phase": "RECOVERY_RUNNING",
                    "recovery": {"active_command_id": "rec-cmd-1"},
                    "step_index": 0,
                    "steps": [{"kind": "move_to_point", "status": "ABORTED", "command_id": "step-cmd"}],
                },
            },
        }
        with (
            patch.object(recovery, "tasks") as postgres_tasks,
            patch.object(recovery, "evidence") as evidence,
            patch.object(recovery, "runtime_records"),
            patch.object(recovery, "get_recovery_context") as get_ctx,
        ):
            postgres_tasks.get_task.return_value = task
            evidence.attach_orchestration.side_effect = lambda row, _conn: row
            get_ctx.return_value = {"task_id": 5, "orchestration_phase": "AWAITING_OPERATOR"}
            result = recovery.handle_recovery_command_event(
                conn,
                5,
                {"command_id": "rec-cmd-1", "state": "DONE"},
            )
        self.assertIsNotNone(result)
        saved = evidence.save_orchestration.call_args[0][2]
        self.assertEqual(saved["phase"], "AWAITING_OPERATOR")
        self.assertNotIn("active_command_id", saved["recovery"])


class ListRecoveryTasksTest(unittest.TestCase):
    def test_list_includes_recovery_running(self) -> None:
        conn = MagicMock()
        task_rows = [
            {
                "task_id": 9,
                "preset_snapshot": {"_orchestration": {"phase": "RECOVERY_RUNNING"}},
            }
        ]
        with (
            patch.object(recovery, "evidence") as evidence,
            patch.object(recovery, "get_recovery_context") as get_ctx,
        ):
            evidence.list_orchestrated_running.return_value = task_rows
            get_ctx.return_value = {"task_id": 9}
            out = recovery.list_awaiting_operator_tasks(conn)
        self.assertEqual(len(out), 1)
        get_ctx.assert_called_once_with(conn, 9)


class ActiveCommandProjectionTest(unittest.TestCase):
    def test_active_command_prefers_recovery_command(self) -> None:
        from app.domains.work_orders import service as wo

        conn = MagicMock()
        task = {
            "preset_snapshot": {
                "_orchestration": {
                    "phase": "RECOVERY_RUNNING",
                    "recovery": {"active_command_id": "rec-99"},
                    "step_index": 0,
                    "steps": [{"status": "dispatched", "command_id": "step-1"}],
                },
            },
        }
        with (
            patch("app.domains.execution.evidence.attach_orchestration", return_value=task),
            patch.object(wo, "postgres_tasks") as repo,
        ):
            repo.get_task.return_value = {"task_id": 1}
            cmd = wo._active_command_id(conn, 1)
        self.assertEqual(cmd, "rec-99")


class RecoveryStopConfirmationTest(unittest.TestCase):
    def test_manual_abort_keeps_task_held_when_stop_is_unconfirmed(self) -> None:
        conn = MagicMock()
        with (
            patch.object(recovery, "tasks") as postgres_tasks,
            patch.object(recovery, "_stop_robot_movement", side_effect=HTTPException(409, "recovery_stop_unconfirmed")),
            patch.object(recovery.evidence, "save_orchestration") as save,
        ):
            postgres_tasks.get_task.return_value = {
                "task_id": 4,
                "status": "RUNNING",
                "assigned_robot_id": "tb3_1",
            }
            with self.assertRaises(HTTPException) as ctx:
                recovery._abort_recovery_task(
                    conn,
                    4,
                    cargo_state="LOADED",
                    checks={"site_clear": True, "pose_ok": True, "cargo_ok": True},
                )
        self.assertEqual(ctx.exception.detail, "recovery_stop_unconfirmed")
        postgres_tasks.set_status.assert_not_called()
        save.assert_not_called()


class RecoveryReadinessTest(unittest.TestCase):
    def test_offline_movement_blocks_safe_recovery(self) -> None:
        with (
            patch.object(
                recovery.movement_navigation,
                "localization_snapshot",
                return_value={"ok": False, "health": {}},
            ),
            patch.object(recovery, "get_movement_health"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                recovery._assert_recovery_robot_ready("tb3_1", "robot2_map")
        self.assertEqual(ctx.exception.detail, "recovery_movement_unreachable")

    def test_ready_robot_checks_active_map(self) -> None:
        snapshot = {
            "ok": True,
            "robot_online": True,
            "localized": True,
            "pose": {"x": 0, "y": 0},
            "command_accepting": True,
            "health": {"is_emergency": False},
        }
        with (
            patch.object(recovery, "get_movement_health"),
            patch.object(recovery.movement_navigation, "localization_snapshot", return_value=snapshot),
            patch.object(recovery.movement_navigation, "assert_movement_active_map") as assert_map,
        ):
            recovery._assert_recovery_robot_ready("tb3_1", "robot2_map")
        assert_map.assert_called_once_with("robot2_map")


if __name__ == "__main__":
    unittest.main()
