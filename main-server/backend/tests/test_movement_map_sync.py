"""Movement map sync and resolve unit tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.api.movement_helpers import resolve_movement_map_id
from app.models.schemas import RobotCommandRequest
from app.services import robot_commands as command_service
from app.services.runtime_map_context import RuntimeMapContext


def _ctx(**kwargs) -> RuntimeMapContext:
    values = {
        "ok": True,
        "active_map_id": "map",
        "resolution": 0.03,
        "origin": [0.0, 0.0, 0.0],
        "width": 59,
        "height": 59,
        "confidence": "live",
    }
    values.update(kwargs)
    return RuntimeMapContext(**values)


class ResolveMovementMapIdTest(unittest.TestCase):
    def test_initial_pose_map_resolution_is_robot_scoped(self) -> None:
        ctx = _ctx(active_map_id="robot2_map")
        with patch("app.services.runtime_map_context.get_runtime_map_context", return_value=ctx) as get_context:
            with self.assertRaises(HTTPException) as raised:
                resolve_movement_map_id("robot1_map", robot_id="tb3_burger_02")
        get_context.assert_called_once_with("tb3_burger_02")
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["error"], "runtime_map_id_mismatch")

    def test_exact_id_match(self) -> None:
        with patch("app.services.runtime_map_context.get_runtime_map_context", return_value=_ctx()):
            with self.assertRaises(HTTPException) as raised:
                resolve_movement_map_id("map")
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["error"], "runtime_map_asset_missing")

    def test_metadata_alias_remap_is_rejected(self) -> None:
        record = {
            "map_id": "robot1_map",
            "resolution": 0.03,
            "origin_x": 0.0,
            "origin_y": 0.0,
            "origin_yaw": 0.0,
            "width": 59,
            "height": 59,
        }
        with patch("app.services.runtime_map_context.get_runtime_map_context", return_value=_ctx()), patch(
            "app.api.movement_helpers.map_record_by_id", return_value=record
        ):
            with self.assertRaises(HTTPException) as raised:
                resolve_movement_map_id("robot1_map")
        self.assertEqual(raised.exception.status_code, 409)

    def test_mismatch_is_rejected(self) -> None:
        record = {"map_id": "robot1_map", "resolution": 0.05, "origin_x": -1, "origin_y": -1, "origin_yaw": 0, "width": 52, "height": 51}
        with patch("app.services.runtime_map_context.get_runtime_map_context", return_value=_ctx()), patch(
            "app.api.movement_helpers.map_record_by_id", return_value=record
        ):
            with self.assertRaises(HTTPException) as raised:
                resolve_movement_map_id("robot1_map")
        self.assertEqual(raised.exception.status_code, 409)


class MoveToPointRouteFallbackTest(unittest.TestCase):
    def test_falls_back_to_route_on_robot_commands_404(self) -> None:
        payload = RobotCommandRequest(
            robot_id="tb3_1",
            kind="move_to_point",
            dry_run=True,
            params={"map_id": "map", "x": 1.0, "y": 2.0, "yaw": 0.0},
        )
        passthrough_error = HTTPException(status_code=502, detail='movement HTTP 404: {"detail":"Not Found"}')
        with patch("app.services.robot_commands.field_bindings.assert_robot_live_map", return_value={"ok": True}), patch(
            "app.services.robot_commands._dispatch_passthrough", side_effect=passthrough_error
        ), patch(
            "app.services.robot_commands.mission_service.preview_goto_route",
            return_value={"accepted": True, "command_id": "cmd-route-1"},
        ) as preview:
            result = command_service._dispatch_move_to_point(MagicMock(), payload, "cmd-route-1", "")
        self.assertTrue(result.accepted)
        preview.assert_called_once()


if __name__ == "__main__":
    unittest.main()
