"""ArUco latest readout proxy tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import HTTPException

from app.domains.movement.router import aruco_latest


class ArucoLatestTest(unittest.TestCase):
    def test_api_route_returns_detection(self) -> None:
        with (
            patch("app.domains.movement.router.postgres_robots") as repo_factory,
            patch("app.domains.movement.router.transaction") as tx,
            patch("app.domains.movement.router.movement_client") as client,
        ):
            tx.return_value.__enter__.return_value = object()
            repo_factory.exists.return_value = True
            client.aruco_latest.return_value = {"robot_id": "tb3_1", "detections": [{}]}
            result = aruco_latest(robot_id="tb3_1", marker_id=101)
        self.assertEqual(result["robot_id"], "tb3_1")
        self.assertTrue(result["detections"])

    def test_api_route_unknown_robot_404(self) -> None:
        with (
            patch("app.domains.movement.router.postgres_robots") as repo_factory,
            patch("app.domains.movement.router.transaction") as tx,
        ):
            tx.return_value.__enter__.return_value = object()
            repo_factory.exists.return_value = False
            with self.assertRaises(HTTPException) as ctx:
                aruco_latest(robot_id="missing", marker_id=1)
        self.assertEqual(ctx.exception.status_code, 404)


if __name__ == "__main__":
    unittest.main()
