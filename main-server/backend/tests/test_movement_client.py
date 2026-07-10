"""HttpMovementClient unit tests (no live Movement server)."""

from __future__ import annotations

import json
import sys
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings
from app.services.movement import HttpMovementClient, MovementClientError


class HttpMovementClientTest(unittest.TestCase):
    def setUp(self) -> None:
        object.__setattr__(settings, "movement_hmac_secret", "test-main-nav-secret")
        self.client = HttpMovementClient(
            {
                "tb3_1": "http://nav.local:8001/movement-api/v1",
                "tb3_2": "http://nav.local:8002/movement-api/v1",
            },
            {
                "tb3_1": "http://192.168.10.54:8001/movement-api/v1",
                "tb3_2": "http://192.168.10.54:8002/movement-api/v1",
            },
            "http://nav.local:8001/movement-api/v1",
            timeout_sec=1.0,
        )

    def test_api_origin_strips_movement_prefix(self) -> None:
        self.assertEqual(
            HttpMovementClient._api_origin("http://nav.local:8001/movement-api/v1"),
            "http://nav.local:8001",
        )

    def test_robot_command_posts_to_root_robot_commands(self) -> None:
        envelope = {"command_id": "cmd-1", "kind": "move_to_point", "params": {}}
        with patch("app.services.movement.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b'{"accepted": true}'
            self.client.robot_command("tb3_burger_01", envelope)
        req = urlopen.call_args.args[0]
        self.assertEqual(req.full_url, "http://nav.local:8001/robot-commands")
        body = json.loads(req.data.decode())
        self.assertEqual(body["robot_id"], "tb3_1")
        self.assertEqual(body["robot_name"], "tb3_1")

    def test_robot_command_retries_on_unreachable(self) -> None:
        envelope = {"command_id": "cmd-2", "kind": "dock_transfer", "params": {}}
        ok = BytesIO(b'{"accepted": true}')
        with patch("app.services.movement.urlopen") as urlopen:
            urlopen.side_effect = [
                URLError("name not resolved"),
                ok,
            ]
            result = self.client.robot_command("tb3_1", envelope)
        self.assertTrue(result.get("accepted"))
        self.assertEqual(urlopen.call_count, 2)
        fallback_req = urlopen.call_args_list[1].args[0]
        self.assertEqual(fallback_req.full_url, "http://192.168.10.54:8001/robot-commands")

    def test_command_status_uses_robot_commands_path(self) -> None:
        with patch("app.services.movement.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b'{"state": "ARRIVED"}'
            result = self.client.command_status("tb3_1", "cmd-move-1")
        self.assertEqual(result["state"], "ARRIVED")
        req = urlopen.call_args.args[0]
        self.assertEqual(req.full_url, "http://nav.local:8001/robot-commands/cmd-move-1")

    def test_command_status_falls_back_to_legacy_commands_on_404(self) -> None:
        err = HTTPError(
            url="http://nav.local:8001/robot-commands/cmd-x",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=BytesIO(b'{"detail":"missing"}'),
        )
        ok = BytesIO(b'{"state": "DONE"}')
        with patch("app.services.movement.urlopen") as urlopen:
            urlopen.side_effect = [err, ok]
            result = self.client.command_status("tb3_1", "cmd-x")
        self.assertEqual(result["state"], "DONE")
        legacy_req = urlopen.call_args_list[1].args[0]
        self.assertIn("/commands/cmd-x", legacy_req.full_url)

    def test_http_error_preserves_status_code(self) -> None:
        err = HTTPError(
            url="http://nav.local:8001/robot-commands",
            code=409,
            msg="Conflict",
            hdrs=None,
            fp=BytesIO(b'{"detail":"gate: ARRIVED required"}'),
        )
        with patch("app.services.movement.urlopen", side_effect=err):
            with self.assertRaises(MovementClientError) as ctx:
                self.client.robot_command("tb3_1", {"command_id": "c", "kind": "dock_transfer"})
        self.assertEqual(ctx.exception.status_code, 409)


if __name__ == "__main__":
    unittest.main()
