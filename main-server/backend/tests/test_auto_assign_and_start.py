"""auto_assign_and_start — offline unit tests (no PostgreSQL required)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import HTTPException

from app.services import tasks as task_service


def _queued(task_id: int) -> dict:
    return {"task_id": task_id, "status": "QUEUED"}


class AutoAssignAndStartTest(unittest.TestCase):
    def _patched(self, queued: list[dict], idle: list[dict]):
        task_repo = MagicMock()
        task_repo.return_value.list_assignable.return_value = queued
        robot_repo = MagicMock()
        robot_repo.return_value.list_idle.return_value = idle
        return (
            patch.object(task_service, "task_repo", task_repo),
            patch.object(task_service, "robot_repo", robot_repo),
            patch.object(task_service, "event_repo", MagicMock()),
            # readiness/capability는 offline 단위테스트에서 항상 통과 처리.
            patch.object(task_service, "robot_assignment_block_reason", return_value=None),
            patch.object(task_service, "observed_robot_capabilities", return_value={
                "navigate", "charge", "lift", "inbound", "outbound",
            }),
        )

    def test_assigns_and_starts_up_to_idle_robots(self) -> None:
        p1, p2, p3, p4, p5 = self._patched([_queued(1), _queued(2)], [{"robot_id": "tb3_1"}])
        with p1, p2, p3, p4, p5, patch.object(
            task_service.orchestrator_service, "start_task_orchestration",
        ) as start:
            result = task_service.auto_assign_and_start(MagicMock(), source="task_progress_poller")
        self.assertEqual(result["assigned"], [{"task_id": 1, "robot_id": "tb3_1"}])
        self.assertEqual(result["started"], [1])
        self.assertEqual(result["start_failed"], [])
        self.assertEqual(result["queued_remaining"], 1)
        start.assert_called_once()
        self.assertEqual(start.call_args.args[1], 1)

    def test_start_failure_logged_and_others_continue(self) -> None:
        p1, p2, p3, p4, p5 = self._patched(
            [_queued(1), _queued(2)],
            [{"robot_id": "tb3_1"}, {"robot_id": "tb3_2"}],
        )

        def _start(conn, task_id, callback_base_url=None, source="operator"):
            if task_id == 1:
                raise HTTPException(status_code=502, detail="leg dispatch rejected")
            return {"task": {"task_id": task_id}}

        with p1, p2, p3, p4, p5, patch.object(
            task_service.orchestrator_service, "start_task_orchestration", side_effect=_start,
        ):
            result = task_service.auto_assign_and_start(MagicMock(), source="task_progress_poller")
        self.assertEqual(len(result["assigned"]), 2)
        self.assertEqual(result["started"], [2])
        self.assertEqual(result["start_failed"], [{"task_id": 1, "detail": "leg dispatch rejected"}])


if __name__ == "__main__":
    unittest.main()
