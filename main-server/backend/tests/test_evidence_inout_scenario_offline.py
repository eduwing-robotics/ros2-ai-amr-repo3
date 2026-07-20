"""Offline unit tests for in/out scenario building (no PostgreSQL required)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services import evidence_runtime


def _mock_locations() -> dict[str, dict]:
    return {
        "INBOUND_01": {"slot_id": "INBOUND_01", "location_id": "INBOUND_01", "x": 2.0, "y": 0.0},
        "INBOUND_02": {"slot_id": "INBOUND_02", "location_id": "INBOUND_02", "x": 2.5, "y": 0.0},
        "OUTBOUND_01": {"slot_id": "OUTBOUND_01", "location_id": "OUTBOUND_01", "x": 4.0, "y": 0.0},
        "OUTBOUND_02": {"slot_id": "OUTBOUND_02", "location_id": "OUTBOUND_02", "x": 4.5, "y": 0.0},
        "STORAGE_S1": {"slot_id": "STORAGE_S1", "location_id": "STORAGE_S1", "x": 1.0, "y": 1.0},
        "inbound_slot_1_approach": {"slot_id": "inbound_slot_1_approach", "location_id": "inbound_slot_1_approach", "x": 1.8, "y": 0.0, "marker_id": 0},
        "inbound_slot_2_approach": {"slot_id": "inbound_slot_2_approach", "location_id": "inbound_slot_2_approach", "x": 2.3, "y": 0.0, "marker_id": 1},
        "outbound_slot_1_approach": {"slot_id": "outbound_slot_1_approach", "location_id": "outbound_slot_1_approach", "x": 3.8, "y": 0.0, "marker_id": 5},
        "outbound_slot_2_approach": {"slot_id": "outbound_slot_2_approach", "location_id": "outbound_slot_2_approach", "x": 4.3, "y": 0.0, "marker_id": 6},
        "warehouse_a_approach": {"slot_id": "warehouse_a_approach", "location_id": "warehouse_a_approach", "x": 0.8, "y": 1.0, "marker_id": 7},
        "HOME_01": {"slot_id": "HOME_01", "location_id": "HOME_01", "x": 0.0, "y": 0.0},
        "HOME_02": {"slot_id": "HOME_02", "location_id": "HOME_02", "x": 0.5, "y": 0.0},
        "vehicle_1_approach": {"slot_id": "vehicle_1_approach", "location_id": "vehicle_1_approach", "x": 0.3, "y": 0.0, "marker_id": 3},
        "vehicle_2_approach": {"slot_id": "vehicle_2_approach", "location_id": "vehicle_2_approach", "x": 0.6, "y": 0.0, "marker_id": 4},
    }


class InOutScenarioOfflineTest(unittest.TestCase):
    def _repo(self, data: dict[str, dict]) -> MagicMock:
        repo = MagicMock()
        repo.get.side_effect = lambda loc_id: data.get(loc_id)
        repo.list_route_steps.return_value = []
        repo.list_by_type.side_effect = lambda t: (
            [data["HOME_01"]] if t == "home" else
            [v for k, v in data.items() if k.endswith("_approach")] if t == "scan" else
            []
        )
        return repo

    @patch("app.services.evidence_runtime.location_repo")
    def test_inbound_builds_scan_move_then_dock(self, location_repo_fn) -> None:
        data = _mock_locations()
        location_repo_fn.return_value = self._repo(data)
        conn = MagicMock()
        task = {
            "task_id": 1,
            "task_type": "INBOUND",
            "from_location_id": "INBOUND_01",
            "to_location_id": "STORAGE_S1",
            "from_floor": 1,
            "to_floor": 1,
        }
        scenario = evidence_runtime.build_scenario_from_task(conn, task)
        steps = scenario["steps"]
        self.assertEqual(len(steps), 7)
        self.assertEqual(steps[0]["action_type"], "leave_dock")
        self.assertEqual(steps[0]["params"], {
            "aruco_marker_id": 3,
            "parking_pose": {
                "map_id": "robot2_map",
                "x": 0.527,
                "y": 0.306,
                "yaw": 1.571,
            },
            "reverse_clearance_marker_distance_m": 0.70,
            "reverse_clearance_fallback_m": 0.50,
        })
        self.assertEqual(steps[1]["action_type"], "move")
        self.assertAlmostEqual(steps[1]["x"], 1.8)
        self.assertEqual(steps[2]["action_type"], "dock_transfer")
        self.assertEqual(steps[2]["params"]["action"], "load")
        self.assertEqual(steps[2]["params"]["pre_insert_lift_mm"], 0)
        self.assertIs(steps[2]["params"]["pre_insert_force_move"], True)
        self.assertEqual(steps[4]["params"]["action"], "unload")
        self.assertEqual(steps[5]["action_type"], "move")
        self.assertEqual(steps[5]["waypoint_id"], "vehicle_1_approach")
        self.assertEqual(steps[6]["action_type"], "aruco_align")
        self.assertEqual(steps[6]["params"], {"aruco_marker_id": 3, "final": "park"})

    @patch("app.services.evidence_runtime.location_repo")
    def test_outbound_ends_with_precision_park(self, location_repo_fn) -> None:
        data = _mock_locations()
        location_repo_fn.return_value = self._repo(data)
        conn = MagicMock()
        task = {
            "task_id": 2,
            "task_type": "OUTBOUND",
            "from_location_id": "STORAGE_S1",
            "to_location_id": "OUTBOUND_01",
            "from_floor": 1,
            "to_floor": 1,
        }
        scenario = evidence_runtime.build_scenario_from_task(conn, task)
        steps = scenario["steps"]
        self.assertEqual(len(steps), 7)
        self.assertEqual(steps[0]["action_type"], "leave_dock")
        self.assertEqual(steps[2]["params"]["action"], "load")
        self.assertEqual(steps[4]["params"]["action"], "unload")
        self.assertEqual(steps[5]["waypoint_id"], "vehicle_1_approach")
        self.assertEqual(steps[6]["action_type"], "aruco_align")
        self.assertEqual(steps[6]["params"], {"aruco_marker_id": 3, "final": "park"})

    @patch("app.services.evidence_runtime.location_repo")
    def test_tb2_uses_validated_second_slots_and_wait2_return(self, location_repo_fn) -> None:
        data = _mock_locations()
        location_repo_fn.return_value = self._repo(data)

        inbound = evidence_runtime.build_scenario_from_task(MagicMock(), {
            "task_id": 21,
            "task_type": "INBOUND",
            "assigned_robot_id": "tb3_2",
            "from_location_id": "INBOUND_02",
            "to_location_id": "STORAGE_S1",
            "from_floor": 1,
            "to_floor": 1,
        })["steps"]
        outbound = evidence_runtime.build_scenario_from_task(MagicMock(), {
            "task_id": 22,
            "task_type": "OUTBOUND",
            "assigned_robot_id": "tb3_2",
            "from_location_id": "STORAGE_S1",
            "to_location_id": "OUTBOUND_02",
            "from_floor": 1,
            "to_floor": 1,
        })["steps"]

        self.assertEqual(
            [step["params"]["aruco_marker_id"] for step in inbound if step["action_type"] in {"dock_transfer", "aruco_align"}],
            [1, 7, 4],
        )
        self.assertEqual(inbound[0]["params"], {
            "aruco_marker_id": 4,
            "parking_pose": {
                "map_id": "robot2_map",
                "x": 0.816,
                "y": 0.326,
                "yaw": 1.571,
            },
            "reverse_clearance_marker_distance_m": 0.70,
            "reverse_clearance_fallback_m": 0.50,
        })
        self.assertEqual(inbound[2]["params"]["pre_insert_lift_mm"], 0)
        self.assertEqual(inbound[-2]["waypoint_id"], "vehicle_2_approach")
        self.assertEqual(
            [step["params"]["aruco_marker_id"] for step in outbound if step["action_type"] in {"dock_transfer", "aruco_align"}],
            [7, 6, 4],
        )
        self.assertEqual(outbound[0]["params"], {
            "aruco_marker_id": 4,
            "parking_pose": {
                "map_id": "robot2_map",
                "x": 0.816,
                "y": 0.326,
                "yaw": 1.571,
            },
            "reverse_clearance_marker_distance_m": 0.70,
            "reverse_clearance_fallback_m": 0.50,
        })
        self.assertEqual(outbound[2]["params"]["pre_insert_lift_mm"], 0)
        self.assertEqual(outbound[-2]["waypoint_id"], "vehicle_2_approach")

    @patch("app.services.evidence_runtime.location_repo")
    def test_chained_task_leaves_the_previous_dock_instead_of_home(self, location_repo_fn) -> None:
        data = _mock_locations()
        location_repo_fn.return_value = self._repo(data)
        task = {
            "task_id": 23,
            "task_type": "OUTBOUND",
            "assigned_robot_id": "tb3_2",
            "from_location_id": "STORAGE_S1",
            "to_location_id": "OUTBOUND_02",
            "from_floor": 1,
            "to_floor": 1,
            "preset_snapshot": {
                "_orchestration": {
                    "phase": "ASSIGNED",
                    "chain_context": {
                        "previous_task_id": 22,
                        "start_dock_location_id": "STORAGE_S1",
                        "robot_id": "tb3_2",
                    },
                },
            },
        }

        scenario = evidence_runtime.build_scenario_from_task(MagicMock(), task)

        self.assertEqual(scenario["start_location_id"], "STORAGE_S1")
        self.assertEqual(scenario["steps"][0]["action_type"], "leave_dock")
        self.assertEqual(scenario["steps"][0]["params"]["aruco_marker_id"], 7)
        self.assertEqual(scenario["steps"][-1]["params"], {"aruco_marker_id": 4, "final": "park"})

    @patch("app.services.evidence_runtime.location_repo")
    def test_inbound_preserves_ordered_transit_then_scan_then_dock(self, location_repo_fn) -> None:
        data = _mock_locations()
        scan = data["inbound_slot_1_approach"]
        scan["map_id"] = "robot2_map"
        transit_1 = {
            "slot_id": "inbound_transit_1",
            "location_id": "inbound_transit_1",
            "type": "transit",
            "x": 1.4,
            "y": -0.2,
            "yaw": 0.1,
            "map_id": "robot2_map",
        }
        transit_2 = {
            "slot_id": "inbound_transit_2",
            "location_id": "inbound_transit_2",
            "type": "transit",
            "x": 1.6,
            "y": -0.1,
            "yaw": 0.0,
            "map_id": "robot2_map",
        }
        repo = self._repo(data)
        repo.list_route_steps.side_effect = lambda scan_id: (
            [transit_1, transit_2, scan] if scan_id == "inbound_slot_1_approach" else []
        )
        location_repo_fn.return_value = repo
        task = {
            "task_id": 3,
            "task_type": "INBOUND",
            "from_location_id": "INBOUND_01",
            "to_location_id": "STORAGE_S1",
            "from_floor": 1,
            "to_floor": 1,
        }
        with patch.object(evidence_runtime.field_bindings, "validate_runtime_location"):
            steps = evidence_runtime.build_scenario_from_task(MagicMock(), task)["steps"]

        self.assertEqual(
            [(step["action_type"], step.get("waypoint_id")) for step in steps[1:5]],
            [
                ("move", "inbound_transit_1"),
                ("move", "inbound_transit_2"),
                ("move", "inbound_slot_1_approach"),
                ("dock_transfer", None),
            ],
        )
        self.assertEqual(sum(step.get("waypoint_id") == "inbound_slot_1_approach" for step in steps), 1)

        source_route = steps[1:4]
        self.assertEqual({step["command_sequence_no"] for step in source_route}, {1})
        self.assertEqual({step["human_hazard_monitor"] for step in source_route}, {True})

        load = next(step for step in steps if step.get("params", {}).get("action") == "load")
        unload = next(step for step in steps if step.get("params", {}).get("action") == "unload")
        self.assertEqual((load["command_sequence_no"], load["evidence_sequence_no"]), (2, 3))
        self.assertEqual((unload["command_sequence_no"], unload["evidence_sequence_no"]), (6, 5))

        loaded_route = [
            step for step in steps
            if step.get("command_sequence_no") == 4 and step["action_type"] == "move"
        ]
        self.assertTrue(loaded_route)
        self.assertTrue(all(step["human_hazard_monitor"] is True for step in loaded_route))
        return_home = steps[-2]
        self.assertEqual(return_home["action_type"], "move")
        self.assertTrue(return_home["human_hazard_monitor"])
        self.assertFalse(load["human_hazard_monitor"])
        self.assertFalse(unload["human_hazard_monitor"])


if __name__ == "__main__":
    unittest.main()
