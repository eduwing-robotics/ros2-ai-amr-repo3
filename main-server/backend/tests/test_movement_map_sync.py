"""Movement map sync and resolve unit tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import HTTPException

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.api.movement_helpers import movement_reason, resolve_movement_map_id
from app.models.schemas import RobotCommandRequest
from app.services import robot_commands as command_service
from app.services.movement_map_sync import _write_map_yaml
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


class MovementReasonTest(unittest.TestCase):
    def test_nonphysical_health_still_blocks_emergency_stop(self) -> None:
        reason = movement_reason(
            {
                "ok": True,
                "robot_online": True,
                "is_emergency": True,
                "localization_required": False,
                "localized": False,
                "pose": None,
                "command_accepting": True,
            }
        )
        self.assertEqual(reason, ("emergency_stop", "clear_emergency"))

    def test_nonphysical_health_can_accept_without_pose(self) -> None:
        reason = movement_reason(
            {
                "ok": True,
                "robot_online": True,
                "is_emergency": False,
                "localization_required": False,
                "localized": False,
                "pose": None,
                "command_accepting": True,
            }
        )
        self.assertEqual(reason, ("ok", None))

    def test_nonphysical_health_still_requires_command_acceptance(self) -> None:
        reason = movement_reason(
            {
                "ok": True,
                "robot_online": True,
                "localization_required": False,
                "localized": False,
                "pose": None,
                "command_accepting": False,
            }
        )
        self.assertEqual(reason, ("command_not_accepting", "check_nav_state"))

    def test_physical_health_still_requires_localization(self) -> None:
        reason = movement_reason(
            {
                "ok": True,
                "robot_online": True,
                "localization_required": True,
                "localized": False,
                "pose": None,
                "command_accepting": True,
            }
        )
        self.assertEqual(reason, ("initial_pose_required", "set_initial_pose"))


class MoveToPointCanonicalRouteTest(unittest.TestCase):
    def test_robot_commands_404_does_not_fallback_to_legacy_route(self) -> None:
        payload = RobotCommandRequest(
            robot_id="tb3_1",
            kind="move_to_point",
            dry_run=True,
            params={"map_id": "map", "x": 1.0, "y": 2.0, "yaw": 0.0},
        )
        passthrough_error = HTTPException(status_code=502, detail='movement HTTP 404: {"detail":"Not Found"}')
        with patch(
            "app.services.robot_commands.field_bindings.assert_robot_live_map",
            return_value={"ok": True},
        ), patch(
            "app.services.robot_commands._dispatch_passthrough",
            side_effect=passthrough_error,
        ), patch(
            "app.services.robot_commands.mission_service.preview_goto_route",
            return_value={"accepted": True, "command_id": "cmd-route-1"},
        ) as preview, self.assertRaises(HTTPException) as raised:
            command_service._dispatch_move_to_point(MagicMock(), payload, "cmd-route-1", "")
        self.assertIs(raised.exception, passthrough_error)
        preview.assert_not_called()


if __name__ == "__main__":
    unittest.main()


def test_existing_map_yaml_identity_is_not_rewritten(tmp_path: Path) -> None:
    target = tmp_path / "robot2_map.yaml"
    original = "image: robot2_map.pgm\nresolution: 0.020\nfree_thresh: 0.196"
    target.write_text(original, encoding="utf-8")

    _write_map_yaml(
        tmp_path,
        "robot2_map",
        {"resolution": 0.02, "origin": [-0.429, -1.48, 0.0]},
    )

    assert target.read_text(encoding="utf-8") == original
