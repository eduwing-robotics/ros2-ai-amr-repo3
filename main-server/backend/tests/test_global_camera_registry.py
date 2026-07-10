"""global_cam_01 camera registry tests (PHASE_37, PHASE_38 vision allowlist)."""

from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

_PG_URL = os.getenv("LMS_DATABASE_URL", os.getenv("DATABASE_URL", "")).strip()
if _PG_URL:
    os.environ["LMS_DATABASE_URL"] = _PG_URL

from fastapi import HTTPException

from app.api.routers.cameras import list_camera_sources
from app.api.routers.system import status
from app.api.routers.vision import (
    _require_known_source,
    vision_overlay_stream,
    vision_streams,
    vision_webrtc_offer,
)
from app.db.connection import init_db, transaction
from app.db.mvp_repositories import MvpCameraRepository
from tests.pg_fixture import apply_demo_fixture


@unittest.skipUnless(_PG_URL, "LMS_DATABASE_URL required")
class GlobalCameraRegistryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def _source_ids(self) -> set[str]:
        with transaction() as conn:
            return {c["source_id"] for c in MvpCameraRepository(conn).list()}

    def test_repository_includes_global_cam_01(self) -> None:
        ids = self._source_ids()
        self.assertIn("global_cam_01", ids)

    def test_demo_seed_adds_robot_cameras(self) -> None:
        apply_demo_fixture()
        ids = self._source_ids()
        self.assertIn("tb3_1_picam", ids)
        self.assertIn("tb3_2_picam", ids)

    def test_global_cam_01_row_shape(self) -> None:
        with transaction() as conn:
            row = conn.execute(
                "SELECT source_id, label, robot_id, status, stream_url FROM cameras WHERE source_id = ?",
                ("global_cam_01",),
            ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["label"], "Global Camera 01")
        self.assertIsNone(row["robot_id"])
        self.assertEqual(row["status"], "not_connected")
        self.assertIsNone(row["stream_url"])

    def test_init_db_idempotent_for_global_cam(self) -> None:
        init_db()
        with transaction() as conn:
            count = conn.execute(
                "SELECT COUNT(*) FROM cameras WHERE source_id = 'global_cam_01'",
            ).fetchone()[0]
        self.assertEqual(count, 1)

    @patch("app.api.routers.system.fetch_camera_health", return_value={"ok": False})
    @patch("app.api.routers.system.get_movement_health", return_value={})
    def test_status_camera_sources_includes_global_cam_01(self, *_mocks) -> None:
        snapshot = status()
        ids = {c.source_id for c in snapshot.camera_sources}
        self.assertIn("global_cam_01", ids)

    def test_camera_sources_endpoint_includes_global_cam_01(self) -> None:
        sources = list_camera_sources()
        ids = {c.source_id for c in sources}
        self.assertIn("global_cam_01", ids)

    def test_vision_allowlist_accepts_global_cam_01(self) -> None:
        _require_known_source("global_cam_01")

    def test_vision_allowlist_rejects_unknown_source(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            _require_known_source("unknown_camera_xyz")
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, "unknown camera source")

    @patch("app.api.routers.vision.fetch_stream_transports")
    def test_vision_streams_not_registry_404(self, mock_fetch) -> None:
        mock_fetch.return_value = (b'{"stream_transports":[]}', "application/json")
        res = vision_streams(source="global_cam_01", view="full")
        self.assertEqual(res.status_code, 200)
        mock_fetch.assert_called_once_with("global_cam_01", "full")

    @patch("app.api.routers.vision.open_mjpeg_stream")
    def test_vision_overlay_stream_allowlist(self, mock_stream) -> None:
        mock_stream.return_value = (iter([b"chunk"]), "multipart/x-mixed-replace")
        for view in ("full", "lift_roi"):
            res = vision_overlay_stream(source="global_cam_01", view=view, max_fps=30)
            self.assertEqual(res.status_code, 200, msg=view)
        self.assertEqual(mock_stream.call_count, 2)

    def test_vision_webrtc_offer_unknown_source_404(self) -> None:
        with self.assertRaises(HTTPException) as ctx:
            vision_webrtc_offer(
                source_id="unknown_camera_xyz",
                view="full",
                payload={"sdp": "v=0", "type": "offer"},
            )
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(ctx.exception.detail, "unknown camera source")

    @patch("app.api.routers.vision.post_webrtc_offer")
    def test_vision_webrtc_offer_fallback_passthrough(self, mock_post) -> None:
        fallback = json.dumps(
            {
                "status": "fallback_required",
                "reason": "sidecar_not_configured",
                "selected_transport": "mjpeg",
                "media_only": True,
            }
        ).encode()
        mock_post.return_value = (fallback, "application/json")
        res = vision_webrtc_offer(
            source_id="global_cam_01",
            view="full",
            payload={"sdp": "v=0", "type": "offer"},
        )
        self.assertEqual(res.status_code, 200)
        body = json.loads(res.body)
        self.assertEqual(body["status"], "fallback_required")
        self.assertEqual(body["selected_transport"], "mjpeg")


if __name__ == "__main__":
    unittest.main()
