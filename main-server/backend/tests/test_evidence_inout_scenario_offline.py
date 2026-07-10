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
        "INBOUND_01": {"slot_id": "INBOUND_01", "location_id": "INBOUND_01", "x": 2.0, "y": 0.0, "marker_id": 101},
        "OUTBOUND_01": {"slot_id": "OUTBOUND_01", "location_id": "OUTBOUND_01", "x": 4.0, "y": 0.0, "marker_id": 102},
        "STORAGE_S1": {"slot_id": "STORAGE_S1", "location_id": "STORAGE_S1", "x": 1.0, "y": 1.0, "marker_id": 201},
        "scan_INBOUND_01": {"slot_id": "scan_INBOUND_01", "location_id": "scan_INBOUND_01", "x": 1.8, "y": 0.0, "marker_id": 101},
        "scan_OUTBOUND_01": {"slot_id": "scan_OUTBOUND_01", "location_id": "scan_OUTBOUND_01", "x": 3.8, "y": 0.0, "marker_id": 102},
        "scan_STORAGE_S1": {"slot_id": "scan_STORAGE_S1", "location_id": "scan_STORAGE_S1", "x": 0.8, "y": 1.0, "marker_id": 201},
        "HOME_01": {"slot_id": "HOME_01", "location_id": "HOME_01", "x": 0.0, "y": 0.0, "marker_id": 301},
        "scan_HOME_01": {"slot_id": "scan_HOME_01", "location_id": "scan_HOME_01", "x": 0.3, "y": 0.0, "marker_id": 301},
    }


class InOutScenarioOfflineTest(unittest.TestCase):
    def _repo(self, data: dict[str, dict]) -> MagicMock:
        repo = MagicMock()
        repo.get.side_effect = lambda loc_id: data.get(loc_id)
        repo.list_by_type.side_effect = lambda t: (
            [data["HOME_01"]] if t == "home" else
            [v for k, v in data.items() if k.startswith("scan_")] if t == "scan" else
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
        self.assertEqual(steps[1]["action_type"], "move")
        self.assertAlmostEqual(steps[1]["x"], 1.8)
        self.assertEqual(steps[2]["action_type"], "dock_transfer")
        self.assertEqual(steps[2]["params"]["action"], "load")
        self.assertEqual(steps[4]["params"]["action"], "unload")
        self.assertEqual(steps[5]["action_type"], "move")
        self.assertEqual(steps[5]["waypoint_id"], "scan_HOME_01")
        self.assertEqual(steps[6]["action_type"], "aruco_align")
        self.assertEqual(steps[6]["params"], {"aruco_marker_id": 301, "final": "park"})

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
        self.assertEqual(steps[5]["waypoint_id"], "scan_HOME_01")
        self.assertEqual(steps[6]["action_type"], "aruco_align")
        self.assertEqual(steps[6]["params"], {"aruco_marker_id": 301, "final": "park"})


if __name__ == "__main__":
    unittest.main()
