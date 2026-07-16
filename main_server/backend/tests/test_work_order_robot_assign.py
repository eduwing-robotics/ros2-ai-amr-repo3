"""— work order manual robot_id assignment."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.domains.execution import tasks


class WorkOrderRobotAssignTest(unittest.TestCase):
    @patch.object(tasks, "assign_task")
    def test_assign_work_order_robot_delegates_to_assign_task(self, assign) -> None:
        # readiness는 이제 assign_task가 단일 지점에서 강제한다(수동 큐 배정과 공유).
        conn = MagicMock()
        assign.return_value = {"task_id": 1, "assigned_robot_id": "tb3_2"}
        out = tasks.assign_work_order_robot(conn, 1, "tb3_2")
        assign.assert_called_once_with(conn, 1, "tb3_2", source="work_order")
        self.assertEqual(out["assigned_robot_id"], "tb3_2")

    @patch.object(tasks, "_apply_assignment")
    @patch.object(tasks, "_assert_robot_ready_for_assignment")
    @patch.object(tasks, "robots")
    @patch.object(tasks, "tasks")
    def test_assign_task_enforces_readiness(
        self, postgres_tasks, postgres_robots, ready, apply_
    ) -> None:
        postgres_tasks.get_task.return_value = {
            "task_id": 1,
            "status": "QUEUED",
            "assigned_robot_id": None,
        }
        postgres_robots.exists.return_value = True
        postgres_robots.list_idle.return_value = [{"robot_id": "tb3_2"}]
        tasks.assign_task(MagicMock(), 1, "tb3_2")
        ready.assert_called_once_with("tb3_2")
        apply_.assert_called_once()

    @patch("app.domains.movement.navigation.localization_snapshot")
    def test_assert_robot_ready_rejects_offline(self, snap) -> None:
        snap.return_value = {
            "health": {"ok": False, "robot_online": False},
            "localized": False,
        }
        with self.assertRaises(HTTPException) as ctx:
            tasks._assert_robot_ready_for_assignment("tb3_2")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "robot_offline")

    @patch("app.domains.movement.navigation.localization_snapshot")
    def test_assert_robot_ready_ok(self, snap) -> None:
        snap.return_value = {
            "health": {"ok": True, "robot_online": True, "command_accepting": True},
            "localized": True,
            "pose": {"x": 0, "y": 0},
        }
        tasks._assert_robot_ready_for_assignment("tb3_1")

    @patch("app.domains.movement.navigation.localization_snapshot")
    def test_battery_assignment_boundaries(self, snap) -> None:
        base = {
            "health": {"ok": True, "robot_online": True, "command_accepting": True},
            "localized": True,
            "pose": {"x": 0, "y": 0},
        }
        for battery, expected in ((19, "robot_battery_low"), (20, None), (None, None)):
            with self.subTest(battery=battery):
                health = dict(base["health"])
                health["battery"] = battery
                snap.return_value = {**base, "health": health}
                self.assertEqual(tasks.robot_assignment_block_reason("tb3_1"), expected)


if __name__ == "__main__":
    unittest.main()
