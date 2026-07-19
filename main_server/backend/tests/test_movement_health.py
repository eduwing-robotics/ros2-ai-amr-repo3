# 기능 책임: health endpoint·pose fallback·stale 판정을 검증한다. 비책임: 실장비의 물리 동작.
"""Movement health probe tests."""

from __future__ import annotations

import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.domains.movement.health import health_urls_for, http_health
from app.domains.movement.navigation import movement_reason

BASE = "http://nav.local:8001/movement-api/v1"


def not_found(url: str) -> HTTPError:
    return HTTPError(
        url=url,
        code=404,
        msg="Not Found",
        hdrs=None,
        fp=BytesIO(b'{"detail":"missing"}'),
    )


class MovementHealthTest(unittest.TestCase):
    def test_health_urls_prefer_versioned_base_then_root(self) -> None:
        self.assertEqual(
            health_urls_for(BASE),
            [
                "http://nav.local:8001/movement-api/v1/health",
                "http://nav.local:8001/health",
            ],
        )

    @patch("app.domains.movement.health.health_bases_for", return_value=[BASE])
    def test_http_health_uses_versioned_health_first(self, _bases) -> None:
        with patch("app.domains.movement.health.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b'{"ok":true,"robot_online":true}'
            result = http_health("tb3_burger_01")
        self.assertTrue(result["ok"])
        req = urlopen.call_args.args[0]
        self.assertEqual(req.full_url, "http://nav.local:8001/movement-api/v1/health")

    @patch("app.domains.movement.health.health_bases_for", return_value=[BASE])
    def test_http_health_does_not_hide_explicit_unhealthy_response(self, _bases) -> None:
        with patch("app.domains.movement.health.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = (
                b'{"ok":false,"robot_online":false,"error":"bringup missing"}'
            )
            result = http_health("tb3_burger_01")
        self.assertFalse(result["ok"])
        self.assertFalse(result["robot_online"])
        self.assertEqual(result["error"], "bringup missing")
        self.assertEqual(urlopen.call_count, 1)

    @patch("app.domains.movement.health.health_bases_for", return_value=[BASE])
    def test_http_health_falls_back_to_root_health(self, _bases) -> None:
        with patch("app.domains.movement.health.urlopen") as urlopen:
            urlopen.side_effect = [
                not_found(f"{BASE}/health"),
                BytesIO(b'{"ok":true,"robot_online":true}'),
            ]
            result = http_health("tb3_burger_01")
        self.assertTrue(result["ok"])
        self.assertEqual(
            urlopen.call_args_list[0].args[0].full_url,
            "http://nav.local:8001/movement-api/v1/health",
        )
        self.assertEqual(
            urlopen.call_args_list[1].args[0].full_url,
            "http://nav.local:8001/health",
        )

    @patch("app.domains.movement.health.health_bases_for", return_value=[BASE])
    def test_http_health_uses_pose_fallback_when_health_missing(self, _bases) -> None:
        pose_body = b'{"robot_name":"tb3_1","localized":true,"pose":{"x":1.0,"y":2.0,"yaw":0.0,"age_sec":0.1}}'
        with patch("app.domains.movement.health.urlopen") as urlopen:
            urlopen.side_effect = [
                not_found(f"{BASE}/health"),
                not_found("http://nav.local:8001/health"),
                BytesIO(pose_body),
            ]
            result = http_health("tb3_burger_01")
        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "pose_fallback")
        self.assertTrue(result["robot_online"])
        self.assertEqual(
            urlopen.call_args_list[2].args[0].full_url,
            "http://nav.local:8001/movement-api/v1/robots/tb3_1/pose",
        )

    @patch("app.domains.movement.health.health_bases_for", return_value=[BASE])
    def test_pose_fallback_rejects_stale_pose_as_robot_online(self, _bases) -> None:
        pose_body = b'{"robot_name":"tb3_1","localized":true,"pose":{"x":1.0,"y":2.0,"yaw":0.0,"age_sec":30.0}}'
        with patch("app.domains.movement.health.urlopen") as urlopen:
            urlopen.side_effect = [
                not_found(f"{BASE}/health"),
                not_found("http://nav.local:8001/health"),
                BytesIO(pose_body),
            ]
            result = http_health("tb3_burger_01")
        self.assertTrue(result["ok"])
        self.assertFalse(result["robot_online"])
        self.assertFalse(result["command_accepting"])


if __name__ == "__main__":
    unittest.main()
