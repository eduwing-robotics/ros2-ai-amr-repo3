"""Camera health and cache tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.api_logs import clear_logs, list_logs, record_heartbeat
from app.core.health_cache import clear_cache
from app.domains.vision.client import fetch_camera_health


class CameraHealthTest(unittest.TestCase):
    def setUp(self) -> None:
        clear_cache()
        clear_logs()

    @patch("app.domains.vision.client._probe_bridge_health", return_value={"ok": False, "error": "bridge down"})
    @patch("app.domains.vision.client._probe_ai_image_health", return_value={"ok": True, "base_url": "http://x:8100"})
    def test_ai_image_ok_when_bridge_down(self, *_mocks) -> None:
        result = fetch_camera_health(["tb3_1_picam"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "ai_image")

    @patch("app.domains.vision.client._probe_bridge_health", return_value={"ok": True, "base_url": "http://x:8090"})
    @patch("app.domains.vision.client._probe_ai_image_health", return_value={"ok": False, "error": "ai down"})
    def test_bridge_ok_when_ai_down(self, *_mocks) -> None:
        result = fetch_camera_health(["tb3_1_picam"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "bridge")

    @patch("app.domains.vision.client._probe_bridge_health", return_value={"ok": False, "error": "bridge down"})
    @patch("app.domains.vision.client._probe_ai_image_health", return_value={"ok": False, "error": "ai down"})
    def test_both_down_offline(self, *_mocks) -> None:
        result = fetch_camera_health(["tb3_1_picam"])
        self.assertFalse(result["ok"])
        self.assertEqual(result["source"], "none")

    def test_vision_heartbeat_records_transitions_only(self) -> None:
        record_heartbeat("vision", "camera", False, detail="brief drop")
        record_heartbeat("vision", "camera", True, detail="back immediately")
        self.assertEqual(list_logs(service="vision"), [])

        for _ in range(3):
            record_heartbeat("vision", "camera", False, detail="down")
        rows = list_logs(service="vision")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["status"], "initial_unreachable")
        self.assertEqual(rows[0]["repeat_count"], 3)

        record_heartbeat("vision", "camera", True, detail="one lucky response")
        self.assertEqual(len(list_logs(service="vision")), 1)
        record_heartbeat("vision", "camera", False, detail="down again")
        self.assertEqual(len(list_logs(service="vision")), 1)

        record_heartbeat("vision", "camera", True, detail="bridge")
        record_heartbeat("vision", "camera", True, detail="bridge")
        rows = list_logs(service="vision")
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["status"], "recovered")

        for _ in range(3):
            record_heartbeat("vision", "camera", False, detail="down again")
        rows = list_logs(service="vision")
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["status"], "unreachable")


if __name__ == "__main__":
    unittest.main()
