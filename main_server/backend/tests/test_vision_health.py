"""Camera health and cache tests."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.health_cache import clear_cache
from app.domains.vision.client import fetch_camera_health


class CameraHealthTest(unittest.TestCase):
    def setUp(self) -> None:
        clear_cache()

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


if __name__ == "__main__":
    unittest.main()
