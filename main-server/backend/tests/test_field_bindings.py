"""Regression tests for Main's authoritative field-location contract."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from fastapi import HTTPException

from app.services import field_bindings
from app.services.movement import movement_client


class FieldBindingsTest(unittest.TestCase):
    def setUp(self) -> None:
        field_bindings.load_field_bindings.cache_clear()
        self.binding = field_bindings.binding_for("STORAGE_S1")
        self.row = {
            "location_id": "STORAGE_S1",
            "map_id": self.binding["map_id"],
            "marker_id": self.binding["marker_id"],
            **self.binding["pose"],
        }

    def test_current_contract_is_complete(self) -> None:
        document = field_bindings.load_field_bindings()
        self.assertEqual(
            {binding["kind"] for binding in document["locations"].values()},
            {"inbound", "outbound", "storage", "home", "charge"},
        )

    def test_runtime_accepts_exact_bound_location(self) -> None:
        self.assertEqual(field_bindings.validate_runtime_location(self.row, "STORAGE_S1"), self.binding)

    def test_runtime_rejects_marker_map_and_pose_drift(self) -> None:
        for field, bad_value in (("marker_id", 999), ("map_id", "robot2_map"), ("x", 99.0)):
            with self.subTest(field=field), self.assertRaises(HTTPException) as ctx:
                field_bindings.validate_runtime_location({**self.row, field: bad_value}, "STORAGE_S1")
            self.assertEqual(ctx.exception.status_code, 409)
            self.assertIn(field, ctx.exception.detail)

    def test_unknown_task_location_is_not_inferred(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            field_bindings.binding_for("STORAGE_UNKNOWN")
        self.assertEqual(ctx.exception.status_code, 409)

    def test_live_robot_map_mismatch_is_rejected_without_remap(self) -> None:
        with patch.object(movement_client, "map_state", return_value={"active_map_id": "robot2_map"}), self.assertRaises(HTTPException) as ctx:
            field_bindings.assert_robot_live_map("tb3_burger_02", "robot1_map")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("live_map=robot2_map", ctx.exception.detail)

    def test_saved_scenario_cannot_relabel_bound_coordinates(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            field_bindings.assert_locations_match_map(["INBOUND_01", "STORAGE_S1", "HOME_01"], "robot2_map")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("scenario_map=robot2_map", ctx.exception.detail)

    def test_robot2_field_dispatch_is_machine_readably_blocked(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            field_bindings.assert_field_dispatch_commissioned("INBOUND", "robot2_map")
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail["code"], "BLOCKED_PENDING_PER_MAP_FIELD_BINDINGS")
        self.assertEqual(ctx.exception.detail["field_dispatch"]["status"], "BLOCKED_PENDING_PER_MAP_FIELD_BINDINGS")

    def test_robot1_field_dispatch_is_commissioned(self) -> None:
        field_bindings.assert_field_dispatch_commissioned("OUTBOUND", "robot1_map")


if __name__ == "__main__":
    unittest.main()
