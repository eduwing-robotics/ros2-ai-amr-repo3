"""auto_assign_and_start — offline unit tests (no PostgreSQL required)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import HTTPException

from app.domains.execution import orchestrator, tasks


def _queued(task_id: int) -> dict:
    return {"task_id": task_id, "status": "QUEUED"}


class AutoAssignAndStartTest(unittest.TestCase):
    def _patched(self, queued: list[dict], idle: list[dict]):
        postgres_tasks = MagicMock()
        postgres_tasks.list_assignable.return_value = queued
        postgres_robots = MagicMock()
        postgres_robots.list_idle.return_value = idle
        return (
            patch.object(tasks, "tasks", postgres_tasks),
            patch.object(tasks, "robots", postgres_robots),
            patch.object(tasks, "operational_events", MagicMock()),
            # readiness는 offline 단위테스트에서 항상 통과(ready) 처리.
            patch.object(tasks, "robot_assignment_block_reason", return_value=None),
        )

    def test_assigns_and_starts_up_to_idle_robots(self) -> None:
        p1, p2, p3, p4 = self._patched([_queued(1), _queued(2)], [{"robot_id": "tb3_1"}])
        with (
            p1,
            p2,
            p3,
            p4,
            patch.object(
                orchestrator,
                "start_task_orchestration",
            ) as start,
        ):
            result = tasks.auto_assign_and_start(MagicMock(), source="task_progress_poller")
        self.assertEqual(result["assigned"], [{"task_id": 1, "robot_id": "tb3_1"}])
        self.assertEqual(result["started"], [1])
        self.assertEqual(result["start_failed"], [])
        self.assertEqual(result["queued_remaining"], 1)
        start.assert_called_once()
        self.assertEqual(start.call_args.args[1], 1)

    def test_start_failure_logged_and_others_continue(self) -> None:
        p1, p2, p3, p4 = self._patched(
            [_queued(1), _queued(2)],
            [{"robot_id": "tb3_1"}, {"robot_id": "tb3_2"}],
        )

        def _start(conn, task_id, callback_base_url=None, source="operator"):
            if task_id == 1:
                raise HTTPException(status_code=502, detail="step dispatch rejected")
            return {"task": {"task_id": task_id}}

        with (
            p1,
            p2,
            p3,
            p4,
            patch.object(
                orchestrator,
                "start_task_orchestration",
                side_effect=_start,
            ),
        ):
            result = tasks.auto_assign_and_start(MagicMock(), source="task_progress_poller")
        self.assertEqual(len(result["assigned"]), 2)
        self.assertEqual(result["started"], [2])
        self.assertEqual(result["start_failed"], [{"task_id": 1, "detail": "step dispatch rejected"}])

    def test_auto_assign_excludes_low_battery_robot(self) -> None:
        postgres_tasks = MagicMock()
        postgres_tasks.list_assignable.return_value = [_queued(1)]
        postgres_robots = MagicMock()
        postgres_robots.list_idle.return_value = [
            {"robot_id": "tb3_low"},
            {"robot_id": "tb3_ready"},
        ]

        def block_reason(robot_id: str) -> str | None:
            return "robot_battery_low" if robot_id == "tb3_low" else None

        with (
            patch.object(tasks, "tasks", postgres_tasks),
            patch.object(tasks, "robots", postgres_robots),
            patch.object(tasks, "operational_events", MagicMock()),
            patch.object(tasks, "robot_assignment_block_reason", side_effect=block_reason),
        ):
            result = tasks.auto_assign(MagicMock())

        self.assertEqual(result["assigned"], [{"task_id": 1, "robot_id": "tb3_ready"}])
        self.assertEqual(result["not_ready"], 1)
        self.assertEqual(result["idle_remaining"], 0)


if __name__ == "__main__":
    unittest.main()
