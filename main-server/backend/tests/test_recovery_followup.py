"""Follow-up UX remediation tests (recovery state close, held task guards)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import HTTPException

from app.services import task_recovery as recovery
from app.services import tasks as task_service


class RecoveryPhaseGuardTest(unittest.TestCase):
    def test_execute_requires_needs_attention_phase(self) -> None:
        conn = MagicMock()
        with patch.object(recovery, "_assert_needs_attention_phase", side_effect=HTTPException(409, "recovery_requires_needs_attention_phase")):
            with self.assertRaises(HTTPException) as ctx:
                recovery.execute_recovery(
                    conn, 1, cargo_state="LOADED", strategy="safe_replan",
                    checks={"site_clear": True, "pose_ok": True, "cargo_ok": True},
                )
        self.assertEqual(ctx.exception.detail, "recovery_requires_needs_attention_phase")


class RecoveryCommandTerminalTest(unittest.TestCase):
    def test_recovery_move_done_returns_to_needs_attention(self) -> None:
        conn = MagicMock()
        task = {
            "task_id": 5,
            "status": "RUNNING",
            "assigned_robot_id": "robot1",
            "preset_snapshot": {
                "_orchestration": {
                    "phase": "RECOVERY_RUNNING",
                    "recovery": {"active_command_id": "rec-cmd-1"},
                    "cursor": 0,
                    "legs": [{"kind": "move_to_point", "status": "ABORTED", "command_id": "leg-cmd"}],
                },
            },
        }
        with patch.object(recovery, "task_repo") as task_repo, \
             patch.object(recovery, "evidence_runtime") as evidence_runtime, \
             patch.object(recovery, "evidence_repo"), \
             patch.object(recovery, "get_recovery_context") as get_ctx:
            task_repo.return_value.get.return_value = task
            evidence_runtime.attach_orchestration.side_effect = lambda row, _conn: row
            get_ctx.return_value = {"task_id": 5, "orchestration_phase": "AWAITING_OPERATOR"}
            result = recovery.handle_recovery_command_event(
                conn, 5, {"command_id": "rec-cmd-1", "state": "DONE"},
            )
        self.assertIsNotNone(result)
        saved = evidence_runtime.save_orchestration.call_args[0][2]
        self.assertEqual(saved["phase"], "AWAITING_OPERATOR")
        self.assertNotIn("active_command_id", saved["recovery"])


class ListRecoveryTasksTest(unittest.TestCase):
    def test_list_includes_recovery_running(self) -> None:
        conn = MagicMock()
        tasks = [{
            "task_id": 9,
            "preset_snapshot": {"_orchestration": {"phase": "RECOVERY_RUNNING"}},
        }]
        with patch.object(recovery, "evidence_runtime") as evidence_runtime, \
             patch.object(recovery, "get_recovery_context") as get_ctx:
            evidence_runtime.list_orchestrated_running.return_value = tasks
            get_ctx.return_value = {"task_id": 9}
            out = recovery.list_needs_attention_tasks(conn)
        self.assertEqual(len(out), 1)
        get_ctx.assert_called_once_with(conn, 9)


class HeldCompleteTaskTest(unittest.TestCase):
    def test_complete_blocked_in_recovery_running(self) -> None:
        conn = MagicMock()
        with patch.object(task_service, "task_repo") as task_repo, \
             patch.object(task_service, "_orchestration_phase", return_value="RECOVERY_RUNNING"):
            task_repo.return_value.get.return_value = {"task_id": 1, "status": "RUNNING"}
            with self.assertRaises(HTTPException) as ctx:
                task_service.complete_task(conn, 1)
        self.assertEqual(ctx.exception.detail, "held_task_complete_blocked_use_recovery")


class ActiveCommandProjectionTest(unittest.TestCase):
    def test_active_command_prefers_recovery_command(self) -> None:
        from app.services import work_orders_pg as wo

        conn = MagicMock()
        task = {
            "preset_snapshot": {
                "_orchestration": {
                    "phase": "RECOVERY_RUNNING",
                    "recovery": {"active_command_id": "rec-99"},
                    "cursor": 0,
                    "legs": [{"status": "dispatched", "command_id": "leg-1"}],
                },
            },
        }
        with patch("app.services.evidence_runtime.attach_orchestration", return_value=task), \
             patch.object(wo, "MvpTaskRepository") as repo:
            repo.return_value.get.return_value = {"task_id": 1}
            cmd = wo._active_command_id(conn, 1)
        self.assertEqual(cmd, "rec-99")


if __name__ == "__main__":
    unittest.main()
