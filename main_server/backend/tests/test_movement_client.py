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

from app.domains.movement.client import HttpMovementClient, MovementClientError


class HttpMovementClientTest(unittest.TestCase):
    def setUp(self) -> None:
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
        with patch("app.domains.movement.client.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b'{"accepted": true}'
            self.client.robot_command("tb3_burger_01", envelope)
        req = urlopen.call_args.args[0]
        self.assertEqual(req.full_url, "http://nav.local:8001/robot-commands")
        body = json.loads(req.data.decode())
        self.assertEqual(body["robot_id"], "tb3_1")
        self.assertEqual(body["robot_name"], "tb3_1")
        self.assertEqual(req.get_header("Idempotency-key"), "cmd-1")

    def test_robot_command_retries_on_unreachable(self) -> None:
        envelope = {"command_id": "cmd-2", "kind": "dock_transfer", "params": {}}
        ok = BytesIO(b'{"accepted": true}')
        with patch("app.domains.movement.client.urlopen") as urlopen:
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
        with patch("app.domains.movement.client.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b'{"state": "ARRIVED"}'
            result = self.client.command_status("tb3_1", "cmd-move-1")
        self.assertEqual(result["state"], "ARRIVED")
        req = urlopen.call_args.args[0]
        self.assertEqual(req.full_url, "http://nav.local:8001/robot-commands/cmd-move-1")

    def test_command_status_preserves_canonical_404(self) -> None:
        err = HTTPError(
            url="http://nav.local:8001/robot-commands/cmd-x",
            code=404,
            msg="Not Found",
            hdrs=None,
            fp=BytesIO(b'{"detail":"missing"}'),
        )
        with patch("app.domains.movement.client.urlopen") as urlopen:
            urlopen.side_effect = err
            with self.assertRaises(MovementClientError) as ctx:
                self.client.command_status("tb3_1", "cmd-x")
        self.assertEqual(ctx.exception.status_code, 404)
        self.assertEqual(urlopen.call_count, 1)

    def test_http_error_preserves_status_code(self) -> None:
        err = HTTPError(
            url="http://nav.local:8001/robot-commands",
            code=409,
            msg="Conflict",
            hdrs=None,
            fp=BytesIO(b'{"detail":"gate: ARRIVED required"}'),
        )
        with patch("app.domains.movement.client.urlopen", side_effect=err):
            with self.assertRaises(MovementClientError) as ctx:
                self.client.robot_command("tb3_1", {"command_id": "c", "kind": "dock_transfer"})
        self.assertEqual(ctx.exception.status_code, 409)
        self.assertNotIn("gate: ARRIVED required", str(ctx.exception))

    def test_rejects_invalid_base_url(self) -> None:
        with self.assertRaises(ValueError):
            HttpMovementClient({"tb3_1": "file:///etc/passwd"}, {}, "http://nav.local:8001", 1.0)

    def test_rejects_oversized_json_response(self) -> None:
        with patch("app.domains.movement.client.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.read.return_value = b"x" * (2 * 1024 * 1024 + 1)
            with self.assertRaises(MovementClientError) as ctx:
                self.client.robot_command("tb3_1", {"command_id": "large", "kind": "move_to_point"})
        self.assertEqual(ctx.exception.status_code, 502)

    def test_scenario_contract_paths_and_idempotency_header(self) -> None:
        body = {
            "contract_version": "1.0",
            "command_id": "main-task-344-tb3_2-contract-001",
            "task_id": 344,
            "robot_name": "tb3_2",
            "scenario_type": "inbound",
            "map": {"map_id": "robot2_map", "frame_id": "map"},
            "pickup": {"location_id": "INBOUND_02", "floor": 1, "approach": {"waypoint_id": "inbound_slot_2_approach", "x": 0.234, "y": 0.006, "yaw": 1.571}},
            "dropoff": {"location_id": "STORAGE_02", "floor": 1, "approach": {"waypoint_id": "warehouse_a_approach", "x": 0.019, "y": -0.618, "yaw": 0.0}},
            "callback_url": "http://main/callback",
        }
        responses = [
            b'{"accepted":true}',
            b'{"state":"RUNNING"}',
            b'{"accepted":true}',
        ]
        requests = []

        def open_request(req, timeout):
            requests.append(req)
            return BytesIO(responses[len(requests) - 1])

        with patch("app.domains.movement.client.urlopen", side_effect=open_request):
            self.client.inout_scenario_command("tb3_2", body)
            self.client.inout_scenario_status("tb3_2", body["command_id"])
            self.client.inout_scenario_safe_stop(
                "tb3_2", body["command_id"], {"request_id": "stop-344", "reason": "OPERATOR_REQUESTED", "requested_by": "main-operator"}
            )

        self.assertEqual(requests[0].full_url, "http://nav.local:8002/movement-api/v1/scenario-commands")
        self.assertEqual(requests[0].get_header("Idempotency-key"), body["command_id"])
        self.assertEqual(requests[1].full_url, f"http://nav.local:8002/movement-api/v1/scenario-commands/{body['command_id']}")
        self.assertEqual(requests[2].full_url, f"http://nav.local:8002/movement-api/v1/scenario-commands/{body['command_id']}/safe-stop")
        self.assertEqual(requests[2].get_header("Idempotency-key"), "stop-344")


if __name__ == "__main__":
    unittest.main()
