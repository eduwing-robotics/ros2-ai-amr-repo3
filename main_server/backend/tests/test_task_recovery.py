"""Tests for E-stop recovery plan APIs."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.domains.execution import recovery


class TaskRecoveryTest(unittest.TestCase):
    def test_removed_recovery_strategy_is_rejected(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            recovery.preview_recovery_plan(
                MagicMock(),
                1,
                cargo_state="LOADED",
                strategy="restart",  # type: ignore[arg-type]
            )
        self.assertEqual(ctx.exception.status_code, 422)
        self.assertEqual(ctx.exception.detail, "unsupported recovery strategy")

    def test_unknown_cargo_blocks_preview(self) -> None:
        conn = MagicMock()
        with (
            patch("app.domains.execution.recovery.get_recovery_context", return_value={"task_id": 1}),
            self.assertRaises(HTTPException) as ctx,
        ):
            recovery.preview_recovery_plan(conn, 1, cargo_state="UNKNOWN", strategy="safe_move")
        self.assertEqual(ctx.exception.status_code, 409)

    def test_loaded_preview_includes_safe_move(self) -> None:
        conn = MagicMock()
        safe = {"location_id": "HOME", "slot_id": "HOME", "x": 1.0, "y": 2.0, "yaw": 0.0}
        with (
            patch("app.domains.execution.recovery.get_recovery_context", return_value={"task_id": 1}),
            patch("app.domains.execution.recovery._safe_zone_location", return_value=safe),
        ):
            plan = recovery.preview_recovery_plan(conn, 1, cargo_state="LOADED", strategy="safe_move")
        kinds = [s["kind"] for s in plan["steps"]]
        self.assertIn("move_to_point", kinds)
        self.assertFalse(plan["dock_transfer_available"])

    def test_dock_transfer_disabled_keeps_safe_move_executable(self) -> None:
        conn = MagicMock()
        safe = {"location_id": "HOME", "slot_id": "HOME", "x": 1.0, "y": 2.0, "yaw": 0.0}
        with patch("app.domains.execution.recovery._safe_zone_location", return_value=safe):
            plan = recovery.preview_recovery_plan(conn, 1, cargo_state="LOADED", strategy="safe_move")
        self.assertTrue(plan["executable"])
        self.assertEqual([s["kind"] for s in plan["steps"]], ["move_to_point"])
        self.assertFalse(plan["dock_transfer_available"])
        self.assertIn("자동 하역", plan["limitations"][0])

    def test_manual_abort_preview_is_explicit_operator_step(self) -> None:
        plan = recovery.preview_recovery_plan(
            MagicMock(),
            1,
            cargo_state="LOADED",
            strategy="manual_abort",
        )
        self.assertTrue(plan["executable"])
        self.assertEqual(plan["steps"][0]["action"], "manual_recovery")


if __name__ == "__main__":
    unittest.main()
