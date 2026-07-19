"""INBOUND/OUTBOUND home parking must remain an explicit ArUco safety gate."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.services import evidence_runtime


def _locations(*, park_marker: object = 3, include_park_scan: bool = True) -> dict[str, dict]:
    rows = {
        "INBOUND_01": {"location_id": "INBOUND_01", "slot_id": "INBOUND_01", "x": 2.0, "y": 0.0, "marker_id": 1},
        "STORAGE_S1": {"location_id": "STORAGE_S1", "slot_id": "STORAGE_S1", "x": 3.0, "y": 0.0, "marker_id": 2},
        "inbound_slot_1_approach": {"location_id": "inbound_slot_1_approach", "slot_id": "inbound_slot_1_approach", "x": 1.8, "y": 0.0, "marker_id": 0},
        "warehouse_a_approach": {"location_id": "warehouse_a_approach", "slot_id": "warehouse_a_approach", "x": 2.8, "y": 0.0, "marker_id": 7},
        "HOME_01": {"location_id": "HOME_01", "slot_id": "HOME_01", "x": 0.0, "y": 0.0, "marker_id": None},
    }
    if include_park_scan:
        rows["vehicle_1_approach"] = {
            "location_id": "vehicle_1_approach", "slot_id": "vehicle_1_approach", "x": 0.3, "y": 0.0, "marker_id": park_marker,
        }
    return rows


def _task() -> dict:
    return {"task_id": 1, "task_type": "INBOUND", "from_location_id": "INBOUND_01", "to_location_id": "STORAGE_S1"}


class InOutHomePrecisionTest(unittest.TestCase):
    def _build(self, data: dict[str, dict], route_steps: list[dict] | None = None) -> dict:
        repo = MagicMock()
        repo.get.side_effect = data.get
        repo.list_route_steps.side_effect = lambda scan_id: (
            list(route_steps or []) if scan_id == "inbound_slot_1_approach" else []
        )
        repo.list_by_type.side_effect = lambda kind: [data["HOME_01"]] if kind == "home" else []
        with (
            patch.object(evidence_runtime, "location_repo", return_value=repo),
            patch.object(evidence_runtime, "settings", SimpleNamespace(movement_active_map_id="map")),
        ):
            return evidence_runtime.build_scenario_from_task(MagicMock(), _task())

    def test_missing_park_scan_blocks_build_instead_of_plain_home_move(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            self._build(_locations(include_park_scan=False))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("scan approach missing", ctx.exception.detail)

    def test_malformed_park_marker_blocks_build_explicitly(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            self._build(_locations(park_marker="not-a-marker"))
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertEqual(ctx.exception.detail, "dock HOME_01 invalid aruco_marker_id")

    def test_plain_move_task_remains_unaffected_without_park_configuration(self) -> None:
        repo = MagicMock()
        repo.get.return_value = {"location_id": "POINT_A", "x": 1.0, "y": 2.0, "yaw": 0.0}
        with (
            patch.object(evidence_runtime, "location_repo", return_value=repo),
            patch.object(evidence_runtime, "settings", SimpleNamespace(movement_active_map_id="map")),
        ):
            scenario = evidence_runtime.build_scenario_from_task(
                MagicMock(), {"task_id": 2, "task_type": "MOVE", "to_location_id": "POINT_A"},
            )
        self.assertEqual(
            scenario["steps"],
            [
                {
                    "action_type": "move",
                    "name": "to:POINT_A",
                    "x": 1.0,
                    "y": 2.0,
                    "yaw": 0.0,
                    "human_hazard_monitor": True,
                }
            ],
        )

    def test_valid_park_ends_with_final_aruco_alignment(self) -> None:
        scenario = self._build(_locations())
        park_approach = scenario["steps"][-2]
        final = scenario["steps"][-1]
        self.assertEqual(park_approach["action_type"], "move")
        self.assertTrue(park_approach["human_hazard_monitor"])
        self.assertEqual(final["action_type"], "aruco_align")
        self.assertEqual(final["params"], {"aruco_marker_id": 3, "final": "park"})
        self.assertFalse(final["human_hazard_monitor"])
        self.assertFalse(any(step["name"].startswith("home:") for step in scenario["steps"]))

    def test_transit_route_requires_coordinates_and_scan_map_identity(self) -> None:
        data = _locations()
        data["inbound_slot_1_approach"]["map_id"] = "robot2_map"
        invalid_routes = (
            (
                {"location_id": "missing_xy", "slot_id": "missing_xy", "type": "transit", "map_id": "robot2_map"},
                "missing coordinates",
            ),
            (
                {
                    "location_id": "wrong_map",
                    "slot_id": "wrong_map",
                    "type": "transit",
                    "x": 1.0,
                    "y": 2.0,
                    "map_id": "other_map",
                },
                "map mismatch",
            ),
        )
        for route, detail in invalid_routes:
            with self.subTest(route=route["location_id"]):
                with (
                    patch.object(evidence_runtime.field_bindings, "validate_runtime_location"),
                    self.assertRaises(HTTPException) as ctx,
                ):
                    self._build(data, [route])
                self.assertEqual(ctx.exception.status_code, 409)
                self.assertIn(detail, ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
