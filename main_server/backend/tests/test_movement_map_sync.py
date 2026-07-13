"""Movement map sync and resolve unit tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.domains.movement import commands as command_service
from app.domains.movement.navigation import RuntimeMapContext, resolve_movement_map_id
from app.models.schemas import RobotCommandRequest


def _ctx(**kwargs) -> RuntimeMapContext:
    return RuntimeMapContext(
        ok=True,
        active_map_id="map",
        resolution=0.03,
        origin=[0.0, 0.0, 0.0],
        width=59,
        height=59,
        confidence="live",
        **kwargs,
    )


class ResolveMovementMapIdTest(unittest.TestCase):
    def test_exact_id_match(self) -> None:
        with patch("app.domains.movement.navigation.get_runtime_map_context", return_value=_ctx()), patch(
            "app.domains.movement.navigation.map_record_by_id",
            return_value={"map_id": "map"},
        ):
            active, _ = resolve_movement_map_id("map")
        self.assertEqual(active, "map")

    def test_metadata_match_allows_alias(self) -> None:
        record = {
            "map_id": "robot1_map",
            "resolution": 0.03,
            "origin_x": 0.0,
            "origin_y": 0.0,
            "origin_yaw": 0.0,
            "width": 59,
            "height": 59,
        }
        with patch("app.domains.movement.navigation.get_runtime_map_context", return_value=_ctx()), patch(
            "app.domains.movement.navigation.map_record_by_id", return_value=record
        ):
            active, _ = resolve_movement_map_id("robot1_map")
        self.assertEqual(active, "map")

    def test_mismatch_still_uses_runtime_map(self) -> None:
        record = {"map_id": "robot1_map", "resolution": 0.05, "origin_x": -1, "origin_y": -1, "origin_yaw": 0, "width": 52, "height": 51}
        with patch("app.domains.movement.navigation.get_runtime_map_context", return_value=_ctx()), patch(
            "app.domains.movement.navigation.map_record_by_id", return_value=record
        ):
            active, _ = resolve_movement_map_id("robot1_map")
        self.assertEqual(active, "map")


if __name__ == "__main__":
    unittest.main()
