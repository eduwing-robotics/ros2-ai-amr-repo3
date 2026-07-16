"""Vision proxy unit tests."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.services import vision_proxy


class VisionProxyTest(unittest.TestCase):
    @patch("app.services.vision_proxy.urlopen")
    @patch("app.services.vision_proxy.settings")
    def test_fetch_stream_transports(self, mock_settings, mock_urlopen) -> None:
        mock_settings.vision_api_base_url = "http://vision:8100"
        mock_settings.vision_timeout_sec = 1.0
        mock_settings.vision_hmac_secret = "test-vision-hmac-secret"
        payload = json.dumps({"sources": [{"stream_transports": [{"kind": "mjpeg"}]}]}).encode()
        mock_res = MagicMock()
        mock_res.read.return_value = payload
        mock_res.headers = {"Content-Type": "application/json"}
        mock_res.__enter__ = lambda s: s
        mock_res.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_res

        body, content_type = vision_proxy.fetch_stream_transports("tb3_1_picam", "full")
        self.assertEqual(content_type, "application/json")
        data = json.loads(body)
        self.assertEqual(data["sources"][0]["stream_transports"][0]["kind"], "mjpeg")
        called_url = mock_urlopen.call_args[0][0].full_url
        self.assertIn("/api/v1/vision/streams", called_url)
        self.assertIn("source=tb3_1_picam", called_url)

    @patch("app.services.vision_proxy.urlopen")
    @patch("app.services.vision_proxy.settings")
    def test_fetch_stream_transports_webrtc_ready_passthrough(self, mock_settings, mock_urlopen) -> None:
        mock_settings.vision_api_base_url = "http://vision:8100"
        mock_settings.vision_timeout_sec = 1.0
        mock_settings.vision_hmac_secret = "test-vision-hmac-secret"
        payload = json.dumps(
            {
                "stream_transports": [
                    {"kind": "mjpeg", "configured": True, "healthy": True, "status": "ready"},
                    {
                        "kind": "webrtc",
                        "configured": True,
                        "healthy": True,
                        "status": "ready",
                        "sidecar": {"status": "healthy", "offer_url": "http://vision:8100/offer"},
                    },
                ],
            }
        ).encode()
        mock_res = MagicMock()
        mock_res.read.return_value = payload
        mock_res.headers = {"Content-Type": "application/json"}
        mock_res.__enter__ = lambda s: s
        mock_res.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_res

        body, _ = vision_proxy.fetch_stream_transports("global_cam_01", "full")
        data = json.loads(body)
        webrtc = next(t for t in data["stream_transports"] if t["kind"] == "webrtc")
        self.assertEqual(webrtc["status"], "ready")
        self.assertEqual(webrtc["sidecar"]["status"], "healthy")

    @patch("app.services.vision_proxy.urlopen")
    @patch("app.services.vision_proxy.settings")
    def test_post_webrtc_offer(self, mock_settings, mock_urlopen) -> None:
        mock_settings.vision_api_base_url = "http://vision:8100"
        mock_settings.vision_timeout_sec = 1.0
        mock_settings.vision_hmac_secret = "test-vision-hmac-secret"
        answer = json.dumps({"sdp": "v=0", "type": "answer", "media_only": True}).encode()
        mock_res = MagicMock()
        mock_res.read.return_value = answer
        mock_res.headers = {"Content-Type": "application/json"}
        mock_res.__enter__ = lambda s: s
        mock_res.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_res

        body, _ = vision_proxy.post_webrtc_offer("global_cam_01", "full", {"sdp": "v=0", "type": "offer"})
        data = json.loads(body)
        self.assertTrue(data["media_only"])
        req = mock_urlopen.call_args[0][0]
        self.assertEqual(req.get_method(), "POST")
        self.assertIn("/webrtc/offer", req.full_url)

    @patch("app.services.vision_proxy.urlopen")
    @patch("app.services.vision_proxy.settings")
    def test_post_webrtc_offer_fallback_passthrough(self, mock_settings, mock_urlopen) -> None:
        mock_settings.vision_api_base_url = "http://vision:8100"
        mock_settings.vision_timeout_sec = 1.0
        mock_settings.vision_hmac_secret = "test-vision-hmac-secret"
        answer = json.dumps(
            {
                "status": "fallback_required",
                "reason": "sidecar_not_configured",
                "selected_transport": "mjpeg",
                "media_only": True,
            }
        ).encode()
        mock_res = MagicMock()
        mock_res.read.return_value = answer
        mock_res.headers = {"Content-Type": "application/json"}
        mock_res.__enter__ = lambda s: s
        mock_res.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_res

        body, content_type = vision_proxy.post_webrtc_offer("global_cam_01", "full", {"sdp": "v=0", "type": "offer"})
        self.assertEqual(content_type, "application/json")
        data = json.loads(body)
        self.assertEqual(data["status"], "fallback_required")
        self.assertEqual(data["selected_transport"], "mjpeg")

    @patch("app.services.vision_proxy.urlopen")
    @patch("app.services.vision_proxy.settings")
    def test_open_mjpeg_stream_includes_view(self, mock_settings, mock_urlopen) -> None:
        mock_settings.vision_stream_base_url = "http://vision:8090"
        mock_settings.vision_stream_timeout_sec = 1.0
        mock_res = MagicMock()
        mock_res.read1.side_effect = [b"chunk", b""]
        mock_res.read = MagicMock()
        mock_res.headers = {"Content-Type": "multipart/x-mixed-replace"}
        mock_res.close = MagicMock()
        mock_urlopen.return_value = mock_res

        chunks, _ = vision_proxy.open_mjpeg_stream("overlay", "tb3_1_picam", 15, view="lift_roi")
        self.assertEqual(b"".join(chunks), b"chunk")
        mock_res.read1.assert_called()
        mock_res.read.assert_not_called()
        called_url = mock_urlopen.call_args[0][0].full_url
        self.assertIn("view=lift_roi", called_url)


if __name__ == "__main__":
    unittest.main()
