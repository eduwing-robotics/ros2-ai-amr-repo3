"""PHASE_21 — RuntimeMapContext unit tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services.runtime_map_context import (
    RuntimeMapContext,
    assert_runtime_map_binding,
    asset_status_for,
    get_runtime_map_context,
    metadata_matches,
    overlay_nav_dims,
    pose_in_bounds,
    resolve_command_map,
)


class RuntimeMapContextTest(unittest.TestCase):
    def test_from_movement_payload(self) -> None:
        payload = {
            "active_map_id": "map",
            "frame_id": "map",
            "resolution": 0.030508,
            "origin": [-1.0, -2.0, 0.0],
            "width": 59,
            "height": 59,
            "reported_at": "2026-06-24T10:00:00Z",
        }
        with patch("app.services.runtime_map_context.movement_client.map_state", return_value=payload):
            ctx = get_runtime_map_context()
        self.assertTrue(ctx.ok)
        self.assertEqual(ctx.active_map_id, "map")
        self.assertEqual(ctx.width, 59)
        self.assertEqual(ctx.source, "movement")
        self.assertEqual(ctx.confidence, "live")

    def test_runtime_context_requests_the_receiving_robot_map(self) -> None:
        payload = {"active_map_id": "robot2_map"}
        with patch("app.services.runtime_map_context.movement_client.map_state", return_value=payload) as map_state:
            ctx = get_runtime_map_context("tb3_burger_02")
        map_state.assert_called_once_with("tb3_burger_02")
        self.assertEqual(ctx.active_map_id, "robot2_map")

    def test_db_fallback_on_movement_error(self) -> None:
        from app.services.movement import MovementClientError

        record = {
            "map_id": "map",
            "resolution": 0.03,
            "origin_x": 0.0,
            "origin_y": 0.0,
            "origin_yaw": 0.0,
            "width": 59,
            "height": 59,
            "frame_id": "map",
        }
        with patch("app.services.runtime_map_context.movement_client.map_state", side_effect=MovementClientError("down")), patch(
            "app.api.movement_helpers.map_record_by_id", return_value=record
        ):
            ctx = get_runtime_map_context()
        self.assertEqual(ctx.source, "db_fallback")
        self.assertEqual(ctx.confidence, "stale")

    def test_metadata_match_alias(self) -> None:
        ctx = RuntimeMapContext(ok=True, active_map_id="map", resolution=0.03, origin=[0, 0, 0], width=59, height=59)
        record = {"map_id": "robot1_map", "resolution": 0.03, "origin_x": 0, "origin_y": 0, "origin_yaw": 0, "width": 59, "height": 59}
        self.assertEqual(asset_status_for(record, ctx), "alias")

    def test_mismatch_when_dims_differ(self) -> None:
        ctx = RuntimeMapContext(ok=True, active_map_id="map", resolution=0.03, origin=[0, 0, 0], width=59, height=59)
        record = {"map_id": "map", "resolution": 0.03, "origin_x": 0, "origin_y": 0, "origin_yaw": 0, "width": 52, "height": 51}
        self.assertEqual(asset_status_for(record, ctx), "mismatch")
        self.assertFalse(metadata_matches(record, ctx))

    def test_overlay_nav_dims_for_active_mismatch(self) -> None:
        ctx = RuntimeMapContext(ok=True, active_map_id="map", resolution=0.03, origin=[0, 0, 0], width=59, height=59)
        record = {"map_id": "map", "resolution": 0.03, "origin_x": 0, "origin_y": 0, "origin_yaw": 0, "width": 52, "height": 51}
        out = overlay_nav_dims(record, ctx)
        self.assertEqual(out["width"], 52)
        self.assertEqual(out["height"], 51)
        self.assertEqual(out["display_width"], 52)
        self.assertEqual(out["display_height"], 51)
        self.assertEqual(out["runtime_width"], 59)
        self.assertEqual(out["runtime_height"], 59)
        self.assertEqual(out["asset_status"], "mismatch")
        self.assertFalse(out["runtime_match"])

    def test_pose_in_bounds(self) -> None:
        ctx = RuntimeMapContext(ok=True, active_map_id="map", resolution=0.05, origin=[0, 0, 0], width=100, height=80)
        self.assertTrue(pose_in_bounds(2.0, 2.0, ctx))
        self.assertFalse(pose_in_bounds(99.0, 99.0, ctx))

    def test_resolve_command_map_rejects_remap(self) -> None:
        ctx = RuntimeMapContext(ok=True, active_map_id="map", resolution=0.03, origin=[0, 0, 0], width=59, height=59)
        with patch("app.services.runtime_map_context.get_runtime_map_context", return_value=ctx), patch(
            "app.api.movement_helpers.map_record_by_id",
            return_value={"map_id": "robot1_map", "width": 52, "height": 51, "resolution": 0.05, "origin_x": 0, "origin_y": 0, "origin_yaw": 0},
        ):
            from fastapi import HTTPException
            with self.assertRaises(HTTPException) as raised:
                resolve_command_map("robot1_map")
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["error"], "runtime_map_id_mismatch")

    def test_runtime_binding_rejects_missing_identity(self) -> None:
        from fastapi import HTTPException
        ctx = RuntimeMapContext(ok=True, active_map_id="robot2_map", resolution=.02, origin=[-.429, -1.48, 0], width=111, height=112, map_yaml_exists=True, image_exists=True)
        with self.assertRaises(HTTPException) as raised:
            assert_runtime_map_binding("robot2_map", ctx)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertEqual(raised.exception.detail["error"], "runtime_map_identity_missing")


if __name__ == "__main__":
    unittest.main()
