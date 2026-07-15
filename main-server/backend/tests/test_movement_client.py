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

    def test_robot_command_primary_failure_is_audited(self) -> None:
        envelope = {"command_id": "cmd-2", "kind": "dock_transfer", "params": {}}
        with patch("app.services.movement.urlopen", side_effect=URLError("name not resolved")) as urlopen, patch(
            "app.services.movement.finish_call"
        ) as finish_call:
            with self.assertRaises(MovementClientError):
                self.client.robot_command("tb3_1", envelope)
        self.assertEqual(urlopen.call_count, 1)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://nav.local:8001/robot-commands")
        finish_call.assert_called_once()
        self.assertEqual(finish_call.call_args.args[1:3], (False, "unreachable"))

    def test_command_status_uses_robot_commands_path(self) -> None:
        with patch("app.services.movement.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b'{"state": "ARRIVED"}'
            result = self.client.command_status("tb3_1", "cmd-move-1")
        self.assertEqual(result["state"], "ARRIVED")
        req = urlopen.call_args.args[0]
        self.assertEqual(req.full_url, "http://nav.local:8001/robot-commands/cmd-move-1")

    def test_command_status_does_not_fall_back_on_canonical_404(self) -> None:
        err = HTTPError(
            url="http://nav.local:8001/robot-commands/cmd-x",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=BytesIO(b'{"detail":"missing"}'),
        )
        with patch("app.services.movement.urlopen") as urlopen:
            urlopen.side_effect = err
            with self.assertRaises(MovementClientError) as ctx:
                self.client.command_status("tb3_1", "cmd-x")
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(urlopen.call_count, 1)
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://nav.local:8001/robot-commands/cmd-x")

    def test_cancel_command_uses_signed_canonical_path(self) -> None:
        with patch("app.services.movement.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b'{"state": "CANCELED"}'
            result = self.client.cancel_command("tb3_1", "cmd-x")
        self.assertEqual(result["state"], "CANCELED")
        request = urlopen.call_args.args[0]
        self.assertEqual(request.full_url, "http://nav.local:8001/robot-commands/cmd-x/cancel")
        self.assertEqual(request.method, "POST")
        self.assertIn("x-sf-signature", {key.lower(): value for key, value in request.headers.items()})

    def test_estop_controls_use_signed_root_compatibility_paths(self) -> None:
        with patch("app.services.movement.urlopen") as urlopen:
            response = urlopen.return_value.__enter__.return_value
            response.read.side_effect = [b'{"message":"stopped"}', b'{"message":"cleared"}']

            self.client.estop("tb3_1")
            self.client.clear_estop("tb3_1")

        requests = [call.args[0] for call in urlopen.call_args_list]
        self.assertEqual(
            [request.full_url for request in requests],
            [
                "http://nav.local:8001/robot/estop",
                "http://nav.local:8001/robot/clear_estop",
            ],
        )
        for request in requests:
            self.assertEqual(request.method, "POST")
            self.assertIn(
                "x-sf-signature",
                {key.lower(): value for key, value in request.headers.items()},
            )

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

    def test_unknown_robot_has_no_cross_robot_endpoint_fallback(self) -> None:
        with patch("app.services.movement.urlopen") as urlopen:
            with self.assertRaises(MovementClientError) as ctx:
                self.client.nav_state("unknown-robot")
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertIn("endpoint is not configured", str(ctx.exception))
        urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
