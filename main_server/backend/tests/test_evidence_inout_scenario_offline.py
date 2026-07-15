"""Offline unit tests for in/out scenario building (no PostgreSQL required)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.domains.execution import evidence


def _mock_locations() -> dict[str, dict]:
    return {
        "INBOUND_01": {"slot_id": "INBOUND_01", "location_id": "INBOUND_01", "x": 2.0, "y": 0.0, "marker_id": 101},
        "OUTBOUND_01": {"slot_id": "OUTBOUND_01", "location_id": "OUTBOUND_01", "x": 4.0, "y": 0.0, "marker_id": 102},
        "STORAGE_S1": {"slot_id": "STORAGE_S1", "location_id": "STORAGE_S1", "x": 1.0, "y": 1.0, "marker_id": 201},
        "scan_INBOUND_01": {
            "slot_id": "scan_INBOUND_01",
            "location_id": "scan_INBOUND_01",
            "x": 1.8,
            "y": 0.0,
            "marker_id": 101,
        },
        "scan_OUTBOUND_01": {
            "slot_id": "scan_OUTBOUND_01",
            "location_id": "scan_OUTBOUND_01",
            "x": 3.8,
            "y": 0.0,
            "marker_id": 102,
        },
        "scan_STORAGE_S1": {
            "slot_id": "scan_STORAGE_S1",
            "location_id": "scan_STORAGE_S1",
            "x": 0.8,
            "y": 1.0,
            "marker_id": 201,
        },
        "HOME_01": {"slot_id": "HOME_01", "location_id": "HOME_01", "x": 0.0, "y": 0.0, "marker_id": 301},
        "scan_HOME_01": {
            "slot_id": "scan_HOME_01",
            "location_id": "scan_HOME_01",
            "x": -0.3,
            "y": 0.0,
            "marker_id": 301,
        },
        "vehicle_2_approach": {
            "slot_id": "vehicle_2_approach",
            "location_id": "vehicle_2_approach",
            "type": "scan",
            "x": 0.816,
            "y": 0.006,
            "marker_id": 4,
        },
    }


class InOutScenarioOfflineTest(unittest.TestCase):
    def _repo(self, data: dict[str, dict]) -> MagicMock:
        repo = MagicMock()
        repo.get.side_effect = lambda _conn, loc_id: data.get(loc_id)
        repo.route_steps_for_target.side_effect = lambda _conn, target_id: (
            [data["inbound_slot_1_pre_approach"]]
            if target_id in {"scan_INBOUND_01", "inbound_slot_1_approach"} and "inbound_slot_1_pre_approach" in data
            else []
        )
        repo.list_by_type.side_effect = lambda _conn, t: (
            [data["HOME_01"]]
            if t == "home"
            else [v for k, v in data.items() if k.startswith("scan_") or v.get("type") == "scan"]
            if t == "scan"
            else []
        )
        return repo

    @patch("app.domains.execution.evidence.locations")
    def test_inbound_builds_scan_move_then_dock(self, location_repo_fn) -> None:
        data = _mock_locations()
        repo = self._repo(data)
        location_repo_fn.get_location = repo.get
        location_repo_fn.route_steps_for_target = repo.route_steps_for_target
        location_repo_fn.list_by_type = repo.list_by_type
        conn = MagicMock()
        task = {
            "task_id": 1,
            "task_type": "INBOUND",
            "from_location_id": "INBOUND_01",
            "to_location_id": "STORAGE_S1",
            "from_floor": 1,
            "to_floor": 1,
        }
        scenario = evidence.build_scenario_from_task(conn, task)
        steps = scenario["steps"]
        self.assertEqual(len(steps), 5)
        self.assertEqual(steps[0]["action_type"], "leave_dock")
        self.assertEqual(steps[1]["action_type"], "move")
        self.assertAlmostEqual(steps[1]["x"], 1.8)
        self.assertEqual(steps[1]["transfer_action"], "load")
        self.assertEqual(steps[2]["transfer_action"], "unload")
        self.assertNotIn("dock_transfer", [step["action_type"] for step in steps])
        # HOME approach 이동 뒤 무리프트 ArUco 정렬로 주차한다.
        self.assertEqual(steps[3]["action_type"], "move")
        self.assertEqual(steps[3]["name"], "scan:vehicle_2_approach")
        self.assertEqual(steps[4]["action_type"], "aruco_align")
        self.assertEqual(steps[4]["params"], {"aruco_marker_id": 4, "final": "park"})

    @patch("app.domains.execution.evidence.locations")
    def test_inbound1_uses_single_precision_waypoint_when_route_is_configured(self, location_repo_fn) -> None:
        data = _mock_locations()
        data["inbound_slot_1_pre_approach"] = {
            "slot_id": "inbound_slot_1_pre_approach",
            "location_id": "inbound_slot_1_pre_approach",
            "x": -0.085,
            "y": -0.22,
            "yaw": 1.571,
            "marker_id": None,
        }
        repo = self._repo(data)
        location_repo_fn.get_location = repo.get
        location_repo_fn.route_steps_for_target = repo.route_steps_for_target
        location_repo_fn.list_by_type = repo.list_by_type
        scenario = evidence.build_scenario_from_task(
            MagicMock(),
            {
                "task_id": 4,
                "task_type": "INBOUND",
                "from_location_id": "INBOUND_01",
                "to_location_id": "STORAGE_S1",
                "from_floor": 1,
                "to_floor": 1,
            },
        )
        steps = scenario["steps"]
        self.assertEqual(len(steps), 5)
        self.assertEqual(steps[1]["waypoint_id"], "scan_INBOUND_01")
        self.assertEqual(steps[1]["transfer_action"], "load")
        self.assertFalse(any(step.get("waypoint_id") == "inbound_slot_1_pre_approach" for step in steps))
        self.assertFalse(any(step["action_type"] == "dock_transfer" for step in steps))

    @patch("app.domains.execution.evidence.locations")
    def test_outbound_builds_home_parking_steps(self, location_repo_fn) -> None:
        data = _mock_locations()
        repo = self._repo(data)
        location_repo_fn.get_location = repo.get
        location_repo_fn.route_steps_for_target = repo.route_steps_for_target
        location_repo_fn.list_by_type = repo.list_by_type
        conn = MagicMock()
        task = {
            "task_id": 2,
            "task_type": "OUTBOUND",
            "from_location_id": "STORAGE_S1",
            "to_location_id": "OUTBOUND_01",
            "from_floor": 1,
            "to_floor": 1,
        }
        scenario = evidence.build_scenario_from_task(conn, task)
        steps = scenario["steps"]
        self.assertEqual(len(steps), 5)
        self.assertEqual(steps[0]["action_type"], "leave_dock")
        self.assertEqual(steps[1]["transfer_action"], "load")
        self.assertEqual(steps[2]["transfer_action"], "unload")
        self.assertEqual(steps[4]["action_type"], "aruco_align")

    @patch("app.domains.execution.evidence.locations")
    def test_home_without_marker_falls_back_to_plain_move(self, location_repo_fn) -> None:
        data = _mock_locations()
        data["HOME_01"]["marker_id"] = None
        data.pop("scan_HOME_01")
        data.pop("vehicle_2_approach")
        repo = self._repo(data)
        location_repo_fn.get_location = repo.get
        location_repo_fn.route_steps_for_target = repo.route_steps_for_target
        location_repo_fn.list_by_type = repo.list_by_type
        scenario = evidence.build_scenario_from_task(
            MagicMock(),
            {
                "task_id": 3,
                "task_type": "INBOUND",
                "from_location_id": "INBOUND_01",
                "to_location_id": "STORAGE_S1",
                "from_floor": 1,
                "to_floor": 1,
            },
        )
        self.assertEqual(len(scenario["steps"]), 4)
        self.assertEqual(scenario["steps"][-1]["name"], "home:HOME_01")

    @patch("app.domains.execution.evidence.locations")
    def test_inbound2_storage_b_floor2_tb3_2_uses_one_movement_scenario(self, location_repo) -> None:
        location_repo.list_map_markers.return_value = []
        task = {
            "task_id": 344,
            "task_type": "INBOUND",
            "status": "ASSIGNED",
            "assigned_robot_id": "tb3_2",
            "from_location_id": "INBOUND_02",
            "to_location_id": "STORAGE_01",
            "from_floor": 1,
            "to_floor": 2,
        }
        with patch.object(evidence, "settings") as contract:
            contract.inbound2_storage_b_scenario_enabled = True
            contract.inbound2_storage_b_scenario_id = "inbound2-storage-b"
            contract.inbound2_storage_b_scenario_version = 1
            contract.inbound2_storage_b_plan_hash = "verified-plan-hash"
            contract.inbound2_storage_b_skip_lift = False
            contract.movement_active_map_id = "robot2_map"
            scenario = evidence.build_scenario_from_task(MagicMock(), task)

        self.assertEqual(len(scenario["steps"]), 1)
        raw = scenario["steps"][0]
        self.assertEqual(raw["action_type"], "scenario")
        self.assertEqual(
            raw["params"],
            {
                "scenario_id": "inbound2-storage-b",
                "scenario_version": 1,
                "expected_plan_hash": "verified-plan-hash",
                "skip_lift": False,
            },
        )
        steps = evidence.plan_command_steps(MagicMock(), scenario, task_id=344, robot_id="tb3_2")
        self.assertEqual(len(steps), 1)
        self.assertEqual(steps[0]["kind"], "scenario")

    def test_inbound2_storage_b_wrong_floor_does_not_match_contract(self) -> None:
        task = {
            "task_type": "INBOUND", "assigned_robot_id": "tb3_2",
            "from_location_id": "INBOUND_02", "to_location_id": "STORAGE_01", "to_floor": 1,
        }
        self.assertFalse(evidence._is_inbound2_storage_b_contract(task))


if __name__ == "__main__":
    unittest.main()
