"""PHASE_79 — work order manual robot_id assignment."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.services import tasks as task_service


class WorkOrderRobotAssignTest(unittest.TestCase):
    @patch.object(task_service, "assign_task")
    def test_assign_work_order_robot_delegates_to_assign_task(self, assign) -> None:
        # readiness는 이제 assign_task가 단일 지점에서 강제한다(수동 큐 배정과 공유).
        conn = MagicMock()
        assign.return_value = {"task_id": 1, "assigned_robot_id": "tb3_2"}
        out = task_service.assign_work_order_robot(conn, 1, "tb3_2")
        assign.assert_called_once_with(conn, 1, "tb3_2", source="work_order")
        self.assertEqual(out["assigned_robot_id"], "tb3_2")

    @patch.object(task_service, "_apply_assignment")
    @patch.object(task_service, "_assert_robot_capable_for_task")
    @patch.object(task_service, "_assert_robot_ready_for_assignment")
    @patch.object(task_service, "robot_repo")
    @patch.object(task_service, "task_repo")
    def test_assign_task_enforces_readiness(self, task_repo, robot_repo, ready, capable, apply_) -> None:
        task_repo.return_value.get.return_value = {"task_id": 1, "status": "QUEUED", "assigned_robot_id": None}
        robot_repo.return_value.exists.return_value = True
        robot_repo.return_value.list_idle.return_value = [{"robot_id": "tb3_2"}]
        task_service.assign_task(MagicMock(), 1, "tb3_2")
        ready.assert_called_once_with("tb3_2")
        capable.assert_called_once_with({"task_id": 1, "status": "QUEUED", "assigned_robot_id": None}, "tb3_2")
        apply_.assert_called_once()

    @patch("app.api.movement_helpers.localization_snapshot")
    @patch("app.core.config.settings")
    def test_assert_robot_ready_rejects_offline(self, settings, snap) -> None:
        settings.movement_client_mode = "http"
        snap.return_value = {
            "health": {"ok": False, "robot_online": False},
            "localized": False,
        }
        with self.assertRaises(HTTPException) as ctx:
            task_service._assert_robot_ready_for_assignment("tb3_2")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "robot_offline")

    @patch("app.api.movement_helpers.localization_snapshot")
    @patch("app.core.config.settings")
    def test_assert_robot_ready_ok(self, settings, snap) -> None:
        settings.movement_client_mode = "http"
        snap.return_value = {
            "health": {"ok": True, "robot_online": True, "command_accepting": True},
            "localized": True,
            "pose": {"x": 0, "y": 0},
        }
        task_service._assert_robot_ready_for_assignment("tb3_1")


if __name__ == "__main__":
    unittest.main()
