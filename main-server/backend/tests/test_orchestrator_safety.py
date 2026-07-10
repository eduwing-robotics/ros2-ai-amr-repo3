"""Orchestrator safety / recovery state transitions (UX audit P0)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import HTTPException

from app.services import orchestrator
from app.services import tasks as task_service


class AdvanceTaskEstopTest(unittest.TestCase):
    def test_aborted_estop_keeps_task_running_and_needs_attention(self) -> None:
        conn = MagicMock()
        task = {
            "task_id": 42,
            "status": "RUNNING",
            "assigned_robot_id": "robot1",
            "preset_snapshot": {
                "_orchestration": {
                    "phase": "RUNNING",
                    "cursor": 0,
                    "legs": [{"kind": "move_to_point", "status": "RUNNING", "command_id": "cmd-1"}],
                },
            },
        }
        with patch.object(orchestrator, "task_repo") as task_repo, \
             patch.object(orchestrator, "evidence_runtime") as evidence_runtime, \
             patch.object(orchestrator, "event_repo") as event_repo, \
             patch.object(orchestrator, "person_hazard") as person_hazard:
            task_repo.return_value.get.return_value = task
            evidence_runtime.attach_orchestration.side_effect = lambda row, _conn: row
            evidence_runtime.resolve_command_def_id.return_value = "cmddef"
            event = {"event": "ABORTED", "reason": "operator_estop", "command_id": "cmd-1"}
            result = orchestrator.advance_task(conn, 42, event)

        self.assertIsNotNone(result)
        evidence_runtime.save_orchestration.assert_called()
        saved_orch = evidence_runtime.save_orchestration.call_args[0][2]
        self.assertEqual(saved_orch["phase"], "AWAITING_OPERATOR")
        self.assertEqual(saved_orch["recovery"]["reason"], "movement_estop")
        task_repo.return_value.set_status.assert_not_called()
        person_hazard.on_robot_task_terminal.assert_not_called()
        event_repo.return_value.append.assert_called()
        event_types = [c.kwargs.get("event_type") or c[1].get("event_type") for c in event_repo.return_value.append.call_args_list]
        self.assertIn("TASK_AWAITING_OPERATOR", event_types)
        self.assertIn("TASK_NEEDS_ATTENTION", event_types)

    def test_aborted_non_estop_still_fails_task(self) -> None:
        conn = MagicMock()
        task = {
            "task_id": 7,
            "status": "RUNNING",
            "assigned_robot_id": "robot1",
            "preset_snapshot": {
                "_orchestration": {
                    "phase": "RUNNING",
                    "cursor": 0,
                    "legs": [{"kind": "move_to_point", "status": "RUNNING", "command_id": "cmd-1"}],
                },
            },
        }
        with patch.object(orchestrator, "task_repo") as task_repo, \
             patch.object(orchestrator, "robot_repo") as robot_repo, \
             patch.object(orchestrator, "evidence_runtime") as evidence_runtime, \
             patch.object(orchestrator, "event_repo"), \
             patch.object(orchestrator, "person_hazard") as person_hazard:
            task_repo.return_value.get.return_value = task
            evidence_runtime.attach_orchestration.side_effect = lambda row, _conn: row
            evidence_runtime.resolve_command_def_id.return_value = "cmddef"
            orchestrator.advance_task(conn, 7, {"event": "ABORTED", "reason": "path_blocked", "command_id": "cmd-1"})

        task_repo.return_value.set_status.assert_called_once_with(7, "FAILED", clear_robot=True)
        robot_repo.return_value.set_task.assert_called_once_with("robot1", "IDLE", None)
        person_hazard.on_robot_task_terminal.assert_called_once_with("robot1")
        saved_orch = evidence_runtime.save_orchestration.call_args[0][2]
        self.assertEqual(saved_orch["phase"], "ABORTED")

    def test_advance_skipped_when_needs_attention(self) -> None:
        conn = MagicMock()
        task = {
            "task_id": 3,
            "status": "RUNNING",
            "assigned_robot_id": "robot1",
            "preset_snapshot": {
                "_orchestration": {
                    "phase": "NEEDS_ATTENTION",
                    "cursor": 0,
                    "legs": [{"kind": "move_to_point", "status": "ABORTED", "command_id": "cmd-1"}],
                },
            },
        }
        with patch.object(orchestrator, "task_repo") as task_repo, \
             patch.object(orchestrator, "evidence_runtime") as evidence_runtime:
            task_repo.return_value.get.return_value = task
            evidence_runtime.attach_orchestration.side_effect = lambda row, _conn: row
            result = orchestrator.advance_task(conn, 3, {"event": "DONE"})
        self.assertIsNone(result)
        evidence_runtime.save_orchestration.assert_not_called()


class PollRunningTasksGateTest(unittest.TestCase):
    def test_poll_skips_needs_attention_tasks(self) -> None:
        conn = MagicMock()
        held = {
            "task_id": 9,
            "assigned_robot_id": "robot1",
            "preset_snapshot": {"_orchestration": {"phase": "NEEDS_ATTENTION", "cursor": 0, "legs": []}},
        }
        with patch.object(orchestrator, "evidence_runtime") as evidence_runtime, \
             patch.object(orchestrator, "advance_on_command_event") as advance:
            evidence_runtime.list_orchestrated_running.return_value = [held]
            advanced = orchestrator.poll_running_tasks(conn)
        self.assertEqual(advanced, 0)
        advance.assert_not_called()


class CancelRunningTaskTest(unittest.TestCase):
    def test_cancel_running_task_blocked(self) -> None:
        conn = MagicMock()
        with patch.object(task_service, "task_repo") as task_repo:
            task_repo.return_value.get.return_value = {
                "task_id": 1,
                "status": "RUNNING",
                "assigned_robot_id": "robot1",
            }
            with self.assertRaises(HTTPException) as ctx:
                task_service.cancel_task(conn, 1)
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "running_task_cancel_blocked_use_recovery")


if __name__ == "__main__":
    unittest.main()
