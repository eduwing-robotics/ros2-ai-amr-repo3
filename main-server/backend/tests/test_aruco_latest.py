"""ArUco latest readout proxy tests (PHASE_19)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import HTTPException

from app.api.routers.movement import aruco_latest
from app.services.movement import FakeMovementClient


class ArucoLatestTest(unittest.TestCase):
    def test_fake_client_returns_detection(self) -> None:
        payload = FakeMovementClient().aruco_latest("tb3_1", 101)
        self.assertEqual(payload["marker_id"], 101)
        self.assertEqual(len(payload["detections"]), 1)
        self.assertIn("center_error_norm", payload["detections"][0])

    def test_api_route_returns_detection(self) -> None:
        with patch("app.api.routers.movement.robot_repo") as repo_factory, patch(
            "app.api.routers.movement.transaction"
        ) as tx, patch("app.api.routers.movement.movement_client") as client:
            tx.return_value.__enter__.return_value = object()
            repo_factory.return_value.exists.return_value = True
            client.aruco_latest.return_value = {"robot_id": "tb3_1", "detections": [{}]}
            result = aruco_latest(robot_id="tb3_1", marker_id=101)
        self.assertEqual(result["robot_id"], "tb3_1")
        self.assertTrue(result["detections"])

    def test_api_route_unknown_robot_404(self) -> None:
        with patch("app.api.routers.movement.robot_repo") as repo_factory, patch(
            "app.api.routers.movement.transaction"
        ) as tx:
            tx.return_value.__enter__.return_value = object()
            repo_factory.return_value.exists.return_value = False
            with self.assertRaises(HTTPException) as ctx:
                aruco_latest(robot_id="missing", marker_id=1)
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
