"""Robot capability-aware assignment tests."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.services import movement_health
from app.services import tasks as task_service


def _task(task_id: int, task_type: str) -> dict:
    return {"task_id": task_id, "status": "QUEUED", "assigned_robot_id": None, "task_type": task_type}


class RobotCapabilityAssignmentTest(unittest.TestCase):
    def test_http_manual_assign_accepts_nav_and_lift_without_fake_direction_capability(self) -> None:
        conn = MagicMock()
        task_repo = MagicMock()
        task_repo.return_value.get.return_value = _task(1, "INBOUND")
        robot_repo = MagicMock()
        robot_repo.return_value.exists.return_value = True
        robot_repo.return_value.list_idle.return_value = [{"robot_id": "tb3_1"}]

        with (
            patch.object(task_service, "task_repo", task_repo),
            patch.object(task_service, "robot_repo", robot_repo),
            patch.object(task_service, "event_repo", MagicMock()),
            patch("app.core.config.settings") as settings,
            patch("app.api.movement_helpers.localization_snapshot") as snap,
        ):
            settings.movement_client_mode = "http"
            snap.return_value = {
                "health": {
                    "ok": True,
                    "robot_online": True,
                    "command_accepting": True,
                    "capabilities": ["navigate", "lift"],
                },
                "localized": True,
                "pose": {"x": 0, "y": 0},
            }
            task_service.assign_task(conn, 1, "tb3_1")

        task_repo.return_value.assign.assert_called_once_with(1, "tb3_1", task_service.ASSIGNED_STATUS)

    def test_http_manual_assign_rejects_unknown_capabilities(self) -> None:
        with (
            patch("app.core.config.settings") as settings,
            patch("app.api.movement_helpers.localization_snapshot") as snap,
        ):
            settings.movement_client_mode = "http"
            snap.return_value = {
                "health": {"ok": True, "robot_online": True, "command_accepting": True},
                "localized": True,
                "pose": {"x": 0, "y": 0},
            }
            with self.assertRaises(HTTPException) as ctx:
                task_service._assert_robot_capable_for_task(_task(1, "CHARGE"), "tb3_1")

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "robot_capabilities_unknown")

    def test_fake_manual_assign_rejects_lift_task_when_fake_robot_lacks_lift(self) -> None:
        conn = MagicMock()
        tasks = MagicMock()
        tasks.return_value.get.return_value = _task(1, "INBOUND")
        robots = MagicMock()
        robots.return_value.exists.return_value = True
        robots.return_value.list_idle.return_value = [{"robot_id": "tb3_1"}]
        movement_health.set_fake_robot_capabilities("tb3_1", ["navigate", "inbound"])
        try:
            with (
                patch.object(task_service, "task_repo", tasks),
                patch.object(task_service, "robot_repo", robots),
                patch.object(task_service, "event_repo", MagicMock()),
                patch("app.core.config.settings") as settings,
            ):
                settings.movement_client_mode = "fake"
                with self.assertRaises(HTTPException) as ctx:
                    task_service.assign_task(conn, 1, "tb3_1")
        finally:
            movement_health.clear_fake_robot_capabilities("tb3_1")

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "robot_missing_capability:lift")

    def test_fake_manual_assign_accepts_fully_capable_lift_robot(self) -> None:
        conn = MagicMock()
        tasks = MagicMock()
        tasks.return_value.get.return_value = _task(1, "OUTBOUND")
        robots = MagicMock()
        robots.return_value.exists.return_value = True
        robots.return_value.list_idle.return_value = [{"robot_id": "tb3_1"}]
        movement_health.set_fake_robot_capabilities("tb3_1", ["navigate", "lift"])
        try:
            with (
                patch.object(task_service, "task_repo", tasks),
                patch.object(task_service, "robot_repo", robots),
                patch.object(task_service, "event_repo", MagicMock()),
                patch("app.core.config.settings") as settings,
            ):
                settings.movement_client_mode = "fake"
                task_service.assign_task(conn, 1, "tb3_1")
        finally:
            movement_health.clear_fake_robot_capabilities("tb3_1")

        tasks.return_value.assign.assert_called_once_with(1, "tb3_1", task_service.ASSIGNED_STATUS)

    def test_synthetic_hil_assignment_requires_live_virtual_backend_but_not_physical_lift_capability(self) -> None:
        movement_health.set_fake_robot_capabilities("tb3_1", ["navigate", "charge"])
        movement_health.set_fake_robot_health("tb3_1", {
            "execution_class": "synthetic_hil",
            "evidence_class": "nonphysical",
            "lift_backend": "virtual",
            "lift": {"synthetic_test_capable": True, "ready": True, "reason": "ok"},
        })
        try:
            with (
                patch("app.core.config.settings") as settings,
                patch.object(
                    task_service,
                    "synthetic_hil_backend_block_reason",
                    return_value=None,
                ),
            ):
                settings.movement_client_mode = "fake"
                task_service._assert_robot_capable_for_task(
                    _task(1, "OUTBOUND"),
                    "tb3_1",
                    execution_mode="synthetic_hil",
                )
        finally:
            movement_health.clear_fake_robot_capabilities("tb3_1")
            movement_health.clear_fake_robot_health("tb3_1")

    def test_synthetic_hil_assignment_rejects_physical_nav_profile(self) -> None:
        movement_health.set_fake_robot_health("tb3_1", {
            "execution_class": "live",
            "evidence_class": "physical",
        })
        try:
            with patch("app.core.config.settings") as settings:
                settings.movement_client_mode = "fake"
                with self.assertRaises(HTTPException) as ctx:
                    task_service._assert_robot_capable_for_task(
                        _task(1, "INBOUND"),
                        "tb3_1",
                        execution_mode="synthetic_hil",
                    )
        finally:
            movement_health.clear_fake_robot_health("tb3_1")

        self.assertEqual(ctx.exception.detail, "synthetic_hil_nav_profile_not_active")

    def test_offline_manual_assign_rejects_unknown_fake_capabilities(self) -> None:
        movement_health.set_fake_robot_health("tb3_1", {"capabilities": None})
        try:
            with patch("app.core.config.settings") as settings:
                settings.movement_client_mode = "offline"
                with self.assertRaises(HTTPException) as ctx:
                    task_service._assert_robot_capable_for_task(_task(1, "MOVE"), "tb3_1")
        finally:
            movement_health.clear_fake_robot_health("tb3_1")

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "robot_capabilities_unknown")

    def test_fake_auto_assign_skips_lift_mismatch_and_assigns_matching_robot(self) -> None:
        tasks = MagicMock()
        tasks.return_value.list_assignable.return_value = [_task(1, "OUTBOUND")]
        robots = MagicMock()
        robots.return_value.list_idle.return_value = [{"robot_id": "nav_only"}, {"robot_id": "lift_out"}]
        movement_health.set_fake_robot_capabilities("nav_only", ["navigate"])
        movement_health.set_fake_robot_capabilities("lift_out", ["navigate", "lift", "outbound"])
        try:
            with (
                patch.object(task_service, "task_repo", tasks),
                patch.object(task_service, "robot_repo", robots),
                patch.object(task_service, "event_repo", MagicMock()),
                patch.object(task_service, "robot_assignment_block_reason", return_value=None),
                patch("app.core.config.settings") as settings,
            ):
                settings.movement_client_mode = "fake"
                result = task_service.auto_assign(MagicMock())
        finally:
            movement_health.clear_fake_robot_capabilities()

        self.assertEqual(result["assigned"], [{"task_id": 1, "robot_id": "lift_out"}])
        self.assertEqual(result["queued_remaining"], 0)

    def test_fake_auto_assign_skips_unknown_capabilities(self) -> None:
        tasks = MagicMock()
        tasks.return_value.list_assignable.return_value = [_task(1, "MOVE")]
        robots = MagicMock()
        robots.return_value.list_idle.return_value = [{"robot_id": "unknown"}]
        movement_health.set_fake_robot_health("unknown", {"capabilities": None})
        try:
            with (
                patch.object(task_service, "task_repo", tasks),
                patch.object(task_service, "robot_repo", robots),
                patch.object(task_service, "event_repo", MagicMock()),
                patch.object(task_service, "robot_assignment_block_reason", return_value=None),
                patch("app.core.config.settings") as settings,
            ):
                settings.movement_client_mode = "fake"
                result = task_service.auto_assign(MagicMock())
        finally:
            movement_health.clear_fake_robot_health("unknown")

        self.assertEqual(result["assigned"], [])
        self.assertEqual(result["queued_remaining"], 1)

    def test_auto_assign_greedy_matches_required_capabilities_without_reusing_robot(self) -> None:
        task_repo = MagicMock()
        task_repo.return_value.list_assignable.return_value = [
            _task(1, "INBOUND"),
            _task(2, "MOVE"),
            _task(3, "OUTBOUND"),
        ]
        robot_repo = MagicMock()
        robot_repo.return_value.list_idle.return_value = [
            {"robot_id": "nav_only"},
            {"robot_id": "lift_in"},
            {"robot_id": "lift_out"},
        ]
        capabilities = {
            "nav_only": {"navigate", "charge"},
            "lift_in": {"navigate", "lift"},
            "lift_out": {"navigate", "lift"},
        }

        with (
            patch.object(task_service, "task_repo", task_repo),
            patch.object(task_service, "robot_repo", robot_repo),
            patch.object(task_service, "event_repo", MagicMock()),
            patch.object(task_service, "robot_assignment_block_reason", return_value=None),
            patch.object(task_service, "observed_robot_capabilities", side_effect=lambda robot_id: capabilities[robot_id]),
        ):
            result = task_service.auto_assign(MagicMock())

        self.assertEqual(
            result["assigned"],
            [
                {"task_id": 1, "robot_id": "lift_in"},
                {"task_id": 2, "robot_id": "nav_only"},
                {"task_id": 3, "robot_id": "lift_out"},
            ],
        )
        self.assertEqual(result["queued_remaining"], 0)
        self.assertEqual(result["idle_remaining"], 0)

    def test_assignment_event_records_required_and_observed_capabilities(self) -> None:
        events = MagicMock()
        with (
            patch.object(task_service, "task_repo") as task_repo,
            patch.object(task_service, "robot_repo") as robot_repo,
            patch.object(task_service, "event_repo", events),
            patch.object(task_service, "observed_robot_capabilities", return_value={"navigate", "charge"}),
        ):
            task_repo.return_value.assign.return_value = None
            robot_repo.return_value.set_task.return_value = None
            task_repo.return_value.add_history.return_value = None
            task_service._apply_assignment(MagicMock(), _task(9, "CHARGE"), "tb3_1", "operator")

        payload = events.return_value.append.call_args.kwargs["payload"]
        self.assertEqual(payload["required_capabilities"], ["charge", "navigate"])
        self.assertEqual(payload["observed_capabilities"], ["charge", "navigate"])

    def test_fake_health_has_deterministic_capability_seam(self) -> None:
        movement_health.set_fake_robot_capabilities("tb3_2", ["navigate", "charge"])
        try:
            self.assertEqual(movement_health.fake_health("tb3_2")["capabilities"], ["charge", "navigate"])
        finally:
            movement_health.clear_fake_robot_capabilities()


if __name__ == "__main__":
    unittest.main()
