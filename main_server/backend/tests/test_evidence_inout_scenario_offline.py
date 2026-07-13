"""Offline unit tests for in/out scenario building (no PostgreSQL required)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.domains.execution import evidence as evidence_runtime


def _mock_locations() -> dict[str, dict]:
    return {
        "INBOUND_01": {"slot_id": "INBOUND_01", "location_id": "INBOUND_01", "x": 2.0, "y": 0.0, "marker_id": 101},
        "OUTBOUND_01": {"slot_id": "OUTBOUND_01", "location_id": "OUTBOUND_01", "x": 4.0, "y": 0.0, "marker_id": 102},
        "STORAGE_S1": {"slot_id": "STORAGE_S1", "location_id": "STORAGE_S1", "x": 1.0, "y": 1.0, "marker_id": 201},
        "scan_INBOUND_01": {"slot_id": "scan_INBOUND_01", "location_id": "scan_INBOUND_01", "x": 1.8, "y": 0.0, "marker_id": 101},
        "scan_OUTBOUND_01": {"slot_id": "scan_OUTBOUND_01", "location_id": "scan_OUTBOUND_01", "x": 3.8, "y": 0.0, "marker_id": 102},
        "scan_STORAGE_S1": {"slot_id": "scan_STORAGE_S1", "location_id": "scan_STORAGE_S1", "x": 0.8, "y": 1.0, "marker_id": 201},
        "HOME_01": {"slot_id": "HOME_01", "location_id": "HOME_01", "x": 0.0, "y": 0.0, "marker_id": 301},
        "scan_HOME_01": {"slot_id": "scan_HOME_01", "location_id": "scan_HOME_01", "x": -0.3, "y": 0.0, "marker_id": 301},
    }


class InOutScenarioOfflineTest(unittest.TestCase):
    def _repo(self, data: dict[str, dict]) -> MagicMock:
        repo = MagicMock()
        repo.get.side_effect = lambda loc_id: data.get(loc_id)
        repo.route_steps_for_target.side_effect = lambda target_id: (
            [data["inbound_slot_1_pre_approach"]]
            if target_id in {"scan_INBOUND_01", "inbound_slot_1_approach"}
            and "inbound_slot_1_pre_approach" in data
            else []
        )
        repo.list_by_type.side_effect = lambda t: (
            [data["HOME_01"]] if t == "home" else
            [v for k, v in data.items() if k.startswith("scan_")] if t == "scan" else
            []
        )
        return repo

    @patch("app.domains.execution.evidence.location_repo")
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
        self.assertEqual(steps[1]["action_type"], "move")
        self.assertAlmostEqual(steps[1]["x"], 1.8)
        self.assertEqual(steps[2]["action_type"], "dock_transfer")
        self.assertEqual(steps[2]["params"]["action"], "load")
        self.assertEqual(steps[4]["params"]["action"], "unload")
        # HOME approach 이동 뒤 무리프트 ArUco 정렬로 주차한다.
        self.assertEqual(steps[5]["action_type"], "move")
        self.assertEqual(steps[5]["name"], "scan:scan_HOME_01")
        self.assertEqual(steps[6]["action_type"], "aruco_align")
        self.assertEqual(steps[6]["params"], {"aruco_marker_id": 301, "final": "park"})

    @patch("app.domains.execution.evidence.location_repo")
    def test_inbound1_uses_pre_approach_when_configured(self, location_repo_fn) -> None:
        data = _mock_locations()
        data["inbound_slot_1_pre_approach"] = {
            "slot_id": "inbound_slot_1_pre_approach",
            "location_id": "inbound_slot_1_pre_approach",
            "x": -0.085,
            "y": -0.22,
            "yaw": 1.571,
            "marker_id": None,
        }
        location_repo_fn.return_value = self._repo(data)
        scenario = evidence_runtime.build_scenario_from_task(MagicMock(), {
            "task_id": 4,
            "task_type": "INBOUND",
            "from_location_id": "INBOUND_01",
            "to_location_id": "STORAGE_S1",
            "from_floor": 1,
            "to_floor": 1,
        })
        steps = scenario["steps"]
        self.assertEqual(len(steps), 8)
        self.assertEqual(steps[1]["name"], "transit:inbound_slot_1_pre_approach")
        self.assertEqual(steps[1]["waypoint_id"], "inbound_slot_1_pre_approach")
        self.assertEqual(steps[2]["name"], "scan:scan_INBOUND_01")
        self.assertEqual(steps[3]["action_type"], "dock_transfer")

    @patch("app.domains.execution.evidence.location_repo")
    def test_outbound_builds_home_parking_legs(self, location_repo_fn) -> None:
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
        self.assertEqual(steps[6]["action_type"], "aruco_align")

    @patch("app.domains.execution.evidence.location_repo")
    def test_home_without_marker_falls_back_to_plain_move(self, location_repo_fn) -> None:
        data = _mock_locations()
        data["HOME_01"]["marker_id"] = None
        data.pop("scan_HOME_01")
        location_repo_fn.return_value = self._repo(data)
        scenario = evidence_runtime.build_scenario_from_task(MagicMock(), {
            "task_id": 3,
            "task_type": "INBOUND",
            "from_location_id": "INBOUND_01",
            "to_location_id": "STORAGE_S1",
            "from_floor": 1,
            "to_floor": 1,
        })
        self.assertEqual(len(scenario["steps"]), 6)
        self.assertEqual(scenario["steps"][-1]["name"], "home:HOME_01")


if __name__ == "__main__":
    unittest.main()
