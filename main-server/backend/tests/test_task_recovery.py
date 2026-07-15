"""Tests for E-stop recovery plan APIs (PHASE_78)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.services import movement_health
from app.services import task_recovery as recovery


class TaskRecoveryTest(unittest.TestCase):
    def tearDown(self) -> None:
        movement_health.clear_fake_robot_health()

    def test_fake_health_override_is_deterministic_for_offline_recovery_tests(self) -> None:
        movement_health.set_fake_robot_health("r1", {"ok": True, "is_emergency": False, "checked_at": "fixed"})
        health = movement_health.fake_health("r1")
        self.assertEqual(health["checked_at"], "fixed")
        self.assertTrue(health["ok"])
        self.assertFalse(health["is_emergency"])

    def _safe_plan(self):
        return {"executable": True, "steps": [{"kind": "move_to_point", "params": {}}]}

    def _running_task(self):
        return {"task_id": 1, "status": "RUNNING", "assigned_robot_id": "r1"}

    def _execute_safe_move(self, *, stops, health):
        conn = MagicMock()
        evidence = MagicMock()
        evidence.list_for_task.return_value = [{"id": 10}]
        evidence.get_orchestration.return_value = {}
        safety = MagicMock()
        safety.list_active.return_value = stops
        tasks = MagicMock()
        tasks.get.return_value = self._running_task()
        with (
            patch.object(recovery, "_assert_needs_attention_phase"),
            patch.object(recovery, "preview_recovery_plan", return_value=self._safe_plan()),
            patch.object(recovery, "evidence_repo", return_value=evidence),
            patch.object(recovery, "safety_stop_repo", return_value=safety),
            patch.object(recovery, "task_repo", return_value=tasks),
            patch.object(
                recovery,
                "get_movement_health",
                side_effect=health if isinstance(health, Exception) else None,
                return_value=None if isinstance(health, Exception) else health,
            ),
            patch.object(recovery.command_service, "dispatch_robot_command") as dispatch,
        ):
            with self.assertRaises(HTTPException) as ctx:
                recovery.execute_recovery(conn, 1, cargo_state="LOADED", strategy="safe_move", checks={"area_clear": True})
        dispatch.assert_not_called()
        return ctx.exception

    def test_all_true_checks_do_not_dispatch_with_open_task_safety_stop(self) -> None:
        error = self._execute_safe_move(
            stops=[{"id": 9, "detected_evidence_id": 10, "status": "OPEN"}],
            health={"r1": {"ok": True, "is_emergency": False}},
        )
        self.assertEqual(error.detail, "recovery_blocked_active_safety_stop")

    def test_all_true_checks_do_not_dispatch_with_nav_emergency(self) -> None:
        error = self._execute_safe_move(
            stops=[], health={"r1": {"ok": True, "is_emergency": True}}
        )
        self.assertEqual(error.detail, "recovery_live_health_unsafe")

    def test_all_true_checks_do_not_dispatch_when_live_health_fails(self) -> None:
        error = self._execute_safe_move(stops=[], health=RuntimeError("health unavailable"))
        self.assertEqual(error.detail, "recovery_live_health_unavailable")

    def test_all_true_checks_do_not_dispatch_when_live_health_is_ambiguous(self) -> None:
        error = self._execute_safe_move(stops=[], health={"r1": {"ok": True}})
        self.assertEqual(error.detail, "recovery_live_health_unsafe")

    def test_pose_connectivity_fallback_cannot_authorize_recovery_motion(self) -> None:
        error = self._execute_safe_move(
            stops=[],
            health={
                "r1": {
                    "ok": True,
                    "mode": "http",
                    "source": "pose_fallback",
                    "is_emergency": False,
                    "estop_state": "clear",
                }
            },
        )
        self.assertEqual(error.detail, "recovery_live_health_unsafe")

    def test_health_endpoint_without_explicit_clear_cannot_authorize_recovery(self) -> None:
        error = self._execute_safe_move(
            stops=[],
            health={
                "r1": {
                    "ok": True,
                    "mode": "http",
                    "health_endpoint_reached": True,
                    "is_emergency": False,
                    "estop_state": "unknown",
                }
            },
        )
        self.assertEqual(error.detail, "recovery_live_health_unsafe")

    def test_unknown_cargo_blocks_preview(self) -> None:
        conn = MagicMock()
        with (
            patch("app.services.task_recovery.get_recovery_context", return_value={"task_id": 1}),
            self.assertRaises(HTTPException) as ctx,
        ):
            recovery.preview_recovery_plan(conn, 1, cargo_state="UNKNOWN", strategy="safe_move")
        self.assertEqual(ctx.exception.status_code, 409)

    def test_removed_strategies_are_rejected(self) -> None:
        for strategy in ("safe_replan", "restart"):
            with self.subTest(strategy=strategy), self.assertRaises(HTTPException) as ctx:
                recovery.preview_recovery_plan(MagicMock(), 1, cargo_state="LOADED", strategy=strategy)
            self.assertEqual(ctx.exception.status_code, 422)

    def test_loaded_preview_includes_safe_move(self) -> None:
        conn = MagicMock()
        safe = {"location_id": "HOME", "slot_id": "HOME", "x": 1.0, "y": 2.0, "yaw": 0.0}
        with (
            patch("app.services.task_recovery.get_recovery_context", return_value={"task_id": 1}),
            patch("app.services.task_recovery._safe_zone_location", return_value=safe),
        ):
            plan = recovery.preview_recovery_plan(conn, 1, cargo_state="LOADED", strategy="safe_move")
        kinds = [s["kind"] for s in plan["steps"]]
        self.assertIn("move_to_point", kinds)
        self.assertFalse(plan["dock_transfer_available"])

    def test_dock_transfer_disabled_keeps_safe_move_executable(self) -> None:
        conn = MagicMock()
        safe = {"location_id": "HOME", "slot_id": "HOME", "x": 1.0, "y": 2.0, "yaw": 0.0}
        with patch("app.services.task_recovery._safe_zone_location", return_value=safe):
            plan = recovery.preview_recovery_plan(conn, 1, cargo_state="LOADED", strategy="safe_move")
        self.assertTrue(plan["executable"])
        self.assertEqual([s["kind"] for s in plan["steps"]], ["move_to_point"])
        self.assertFalse(plan["dock_transfer_available"])

    def test_empty_cargo_safe_move_still_uses_configured_home(self) -> None:
        safe = {"location_id": "HOME", "slot_id": "HOME", "x": 1.0, "y": 2.0, "yaw": 0.0}
        with patch("app.services.task_recovery._safe_zone_location", return_value=safe):
            plan = recovery.preview_recovery_plan(MagicMock(), 1, cargo_state="EMPTY", strategy="safe_move")
        self.assertEqual([step["kind"] for step in plan["steps"]], ["move_to_point"])


if __name__ == "__main__":
    unittest.main()
