"""Robot command envelope unit tests (no external movement server)."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.domains.movement import commands
from app.models.robot_commands import RobotCommandRequest


class RobotCommandServiceTest(unittest.TestCase):
    def test_default_command_id_includes_kind(self) -> None:
        command_id = commands.default_command_id(42, "robot-a", "move_to_point")
        self.assertIn("task-42", command_id)
        self.assertIn("robot-a", command_id)
        self.assertIn("move_to_point", command_id)

    def test_dock_transfer_dry_run_validates(self) -> None:
        payload = RobotCommandRequest(
            robot_id="robot-a",
            kind="dock_transfer",
            dry_run=True,
            params={"aruco_marker_id": 7, "action": "load", "level": 2},
        )
        result = commands._dispatch_dock_transfer(payload, "cmd-dock-1", "")
        self.assertTrue(result.accepted)
        self.assertTrue(result.response.get("validated"))
        self.assertEqual(result.response["params"]["level"], 2)

    def test_dock_transfer_dry_run_echoes_optional_lift_fields(self) -> None:
        payload = RobotCommandRequest(
            robot_id="robot-a",
            kind="dock_transfer",
            dry_run=True,
            params={
                "aruco_marker_id": 7,
                "action": "unload",
                "level": 1,
                "lift_height_mm": 48,
                "lift_timeout_sec": 25,
                "home_on_unload": True,
            },
        )
        result = commands._dispatch_dock_transfer(payload, "cmd-dock-opt", "")
        echoed = result.response["params"]
        self.assertEqual(echoed["lift_height_mm"], 48.0)
        self.assertEqual(echoed["lift_timeout_sec"], 25.0)
        self.assertTrue(echoed["home_on_unload"])

    def test_dock_transfer_optional_fields_passthrough_execute(self) -> None:
        payload = RobotCommandRequest(
            robot_id="robot-a",
            kind="dock_transfer",
            dry_run=False,
            params={
                "aruco_marker_id": 2,
                "action": "load",
                "level": 2,
                "lift_height_mm": 50,
                "lift_timeout_sec": 30,
            },
        )
        with patch("app.domains.movement.commands.movement_client.robot_command", return_value={"accepted": True, "command_id": "cmd-dock-opt-exec"}) as robot_command:
            commands._dispatch_dock_transfer(payload, "cmd-dock-opt-exec", "")
        sent = robot_command.call_args.args[1]
        self.assertEqual(sent["params"]["lift_height_mm"], 50.0)
        self.assertEqual(sent["params"]["lift_timeout_sec"], 30.0)
        self.assertNotIn("home_on_unload", sent["params"])

    def test_dock_transfer_rejects_invalid_level(self) -> None:
        payload = RobotCommandRequest(
            robot_id="robot-a",
            kind="dock_transfer",
            dry_run=True,
            params={"aruco_marker_id": 7, "action": "load", "level": 3},
        )
        with self.assertRaises(HTTPException) as ctx:
            commands._dispatch_dock_transfer(payload, "cmd-dock-level-bad", "")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("level must be 1 or 2", str(ctx.exception.detail))

    def test_dock_transfer_rejects_non_bool_home_on_unload(self) -> None:
        payload = RobotCommandRequest(
            robot_id="robot-a",
            kind="dock_transfer",
            dry_run=True,
            params={"aruco_marker_id": 7, "action": "unload", "home_on_unload": "yes"},
        )
        with self.assertRaises(HTTPException) as ctx:
            commands._dispatch_dock_transfer(payload, "cmd-dock-home-bad", "")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_dock_transfer_normalizes_level(self) -> None:
        payload = RobotCommandRequest(
            robot_id="robot-a",
            kind="dock_transfer",
            dry_run=False,
            params={"aruco_marker_id": 2, "action": "load", "level": 2},
        )
        with patch("app.domains.movement.commands.movement_client.robot_command", return_value={"accepted": True, "command_id": "cmd-dock-level"}) as robot_command:
            commands._dispatch_dock_transfer(payload, "cmd-dock-level", "")
        sent = robot_command.call_args.args[1]
        self.assertEqual(sent["params"]["level"], 2)

    def test_dock_transfer_execute_passthrough(self) -> None:
        payload = RobotCommandRequest(
            robot_id="robot-a",
            kind="dock_transfer",
            dry_run=False,
            params={"aruco_marker_id": 7, "action": "unload"},
        )
        with patch("app.domains.movement.commands.movement_client.robot_command", return_value={"accepted": True, "command_id": "cmd-dock-2"}):
            result = commands._dispatch_dock_transfer(payload, "cmd-dock-2", "")
        self.assertTrue(result.accepted)

    def test_dock_transfer_missing_movement_endpoint_returns_501(self) -> None:
        payload = RobotCommandRequest(
            robot_id="robot-a",
            kind="dock_transfer",
            dry_run=False,
            params={"aruco_marker_id": 7, "action": "load"},
        )
        with patch(
            "app.domains.movement.commands.movement_client.robot_command",
            side_effect=commands.MovementClientError('movement HTTP 404: {"detail":"Not Found"}'),
        ):
            with self.assertRaises(HTTPException) as ctx:
                commands._dispatch_dock_transfer(payload, "cmd-dock-404", "")
        self.assertEqual(ctx.exception.status_code, 501)
        self.assertIn("movement_robot_commands_api_missing", str(ctx.exception.detail))

    def test_dock_transfer_requires_params(self) -> None:
        payload = RobotCommandRequest(robot_id="robot-a", kind="dock_transfer", dry_run=True, params={})
        with self.assertRaises(HTTPException) as ctx:
            commands._dispatch_dock_transfer(payload, "cmd-dock-3", "")
        self.assertEqual(ctx.exception.status_code, 400)

    def test_aruco_align_dry_run_validates(self) -> None:
        payload = RobotCommandRequest(
            robot_id="robot-a",
            kind="aruco_align",
            dry_run=True,
            params={"aruco_marker_id": 3, "final": "charge"},
        )
        result = commands._dispatch_aruco_align(payload, "cmd-align-1", "")
        self.assertTrue(result.accepted)
        self.assertTrue(result.response.get("validated"))
        self.assertEqual(result.response["params"]["aruco_marker_id"], 3)
        self.assertEqual(result.response["params"]["final"], "charge")
        self.assertEqual(result.response["params"]["tolerance"], {"xy_m": 0.05})

    def test_aruco_align_tolerance_object(self) -> None:
        payload = RobotCommandRequest(
            robot_id="tb3_burger_01",
            kind="aruco_align",
            dry_run=True,
            params={"aruco_marker_id": 2, "tolerance": {"xy_m": 0.02, "yaw_deg": 2}},
        )
        result = commands._dispatch_aruco_align(payload, "cmd-align-tol", "")
        self.assertEqual(result.response["params"]["tolerance"], {"xy_m": 0.02, "yaw_deg": 2.0})

    def test_aruco_align_execute_normalizes_robot_id(self) -> None:
        payload = RobotCommandRequest(
            robot_id="tb3_burger_01",
            kind="aruco_align",
            dry_run=False,
            params={"aruco_marker_id": 3},
        )
        with patch("app.domains.movement.commands.movement_client.robot_command", return_value={"accepted": True}) as robot_command:
            commands._dispatch_aruco_align(payload, "cmd-align-2", "")
        sent = robot_command.call_args.args[1]
        self.assertEqual(sent["robot_id"], "tb3_1")
        self.assertEqual(sent["robot_name"], "tb3_1")

    def test_dock_transfer_gate_conflict_returns_409(self) -> None:
        payload = RobotCommandRequest(
            robot_id="robot-a",
            kind="dock_transfer",
            dry_run=False,
            params={"aruco_marker_id": 7, "action": "load"},
        )
        with patch(
            "app.domains.movement.commands.movement_client.robot_command",
            side_effect=commands.MovementClientError(
                'movement HTTP 409: {"detail":"ARRIVED required"}',
                status_code=409,
            ),
        ):
            with self.assertRaises(HTTPException) as ctx:
                commands._dispatch_dock_transfer(payload, "cmd-dock-gate", "")
        self.assertEqual(ctx.exception.status_code, 409)

    def test_aruco_align_execute_passthrough(self) -> None:
        payload = RobotCommandRequest(
            robot_id="robot-a",
            kind="aruco_align",
            dry_run=False,
            params={"aruco_marker_id": 3},
        )
        with patch("app.domains.movement.commands.movement_client.robot_command", return_value={"accepted": True, "command_id": "cmd-align-2"}):
            result = commands._dispatch_aruco_align(payload, "cmd-align-2", "")
        self.assertTrue(result.accepted)

    def test_command_status_preserves_kind_when_available(self) -> None:
        with patch(
            "app.domains.movement.commands.missions.command_status",
            return_value={"state": "RUNNING", "kind": "aruco_align", "dry_run": True},
        ):
            result = commands.get_command_status("robot-a", "cmd-align-3")
        self.assertEqual(result.kind, "aruco_align")
        self.assertTrue(result.accepted)

    def test_estop_failure_returns_502(self) -> None:
        payload = RobotCommandRequest(robot_id="robot-a", kind="estop", params={"op": "stop"})
        with patch(
            "app.domains.movement.commands.movement_client.estop",
            side_effect=commands.MovementClientError("movement unreachable"),
        ):
            with self.assertRaises(HTTPException) as ctx:
                commands._dispatch_estop(payload, "cmd-estop-1")
        self.assertEqual(ctx.exception.status_code, 502)

    def test_manual_drive_dry_run_validates_without_movement(self) -> None:
        payload = RobotCommandRequest(
            robot_id="robot-a",
            kind="manual_drive",
            dry_run=True,
            params={"command": "forward", "hold": True},
        )
        result = commands._dispatch_manual_drive(payload, "cmd-manual-1")
        self.assertTrue(result.dry_run)
        self.assertTrue(result.accepted)
        self.assertTrue(result.response.get("validated"))

    def test_move_to_point_rejects_waypoint_with_coordinates(self) -> None:
        payload = RobotCommandRequest(
            robot_id="robot-a",
            kind="move_to_point",
            dry_run=True,
            params={
                "waypoint_id": "warehouse_b_approach",
                "map_id": "must-not-leak",
                "x": 99.0,
                "y": 99.0,
            },
        )
        with self.assertRaises(HTTPException) as ctx:
            commands._dispatch_move_to_point(MagicMock(), payload, "cmd-waypoint", "")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("not both", str(ctx.exception.detail))

    def test_move_to_point_requires_map_id(self) -> None:
        payload = RobotCommandRequest(robot_id="robot-a", kind="move_to_point", params={"x": 1.0, "y": 2.0})
        with self.assertRaises(HTTPException) as ctx:
            commands._dispatch_move_to_point(MagicMock(), payload, "cmd-move-1", "")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("map_id", str(ctx.exception.detail))

    def test_move_to_point_requires_x(self) -> None:
        payload = RobotCommandRequest(robot_id="robot-a", kind="move_to_point", params={"map_id": "map-1", "y": 2.0})
        with self.assertRaises(HTTPException) as ctx:
            commands._dispatch_move_to_point(MagicMock(), payload, "cmd-move-2", "")
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("x", str(ctx.exception.detail))

    def test_robot_command_request_rejects_unknown_kind(self) -> None:
        with self.assertRaises(ValidationError):
            RobotCommandRequest.model_validate({"robot_id": "robot-a", "kind": "fly", "params": {}})

    @staticmethod
    def _scenario_payload() -> RobotCommandRequest:
        return RobotCommandRequest(
            robot_id="tb3_2",
            kind="scenario",
            command_id="main-task-344-tb3_2-contract-001",
            task_id=344,
            params={
                "scenario_id": "inbound2-storage-b",
                "scenario_version": 1,
                "expected_plan_hash": "hash-verified",
                "skip_lift": False,
            },
        )

    def test_scenario_preview_hash_mismatch_does_not_execute(self) -> None:
        payload = self._scenario_payload()
        with (
            patch.object(
                commands.movement_client,
                "scenario_preview",
                return_value={"executable": True, "blocking_reasons": [], "plan_hash": "hash-other"},
            ),
            patch.object(commands.movement_client, "scenario_command") as execute,
        ):
            with self.assertRaises(HTTPException) as ctx:
                commands._dispatch_scenario(payload, payload.command_id or "", "http://main/callback")
        self.assertEqual(ctx.exception.status_code, 409)
        execute.assert_not_called()

    def test_scenario_preview_blocked_does_not_execute(self) -> None:
        payload = self._scenario_payload()
        with (
            patch.object(
                commands.movement_client,
                "scenario_preview",
                return_value={
                    "executable": False,
                    "blocking_reasons": ["robot_not_localized"],
                    "plan_hash": "hash-verified",
                },
            ),
            patch.object(commands.movement_client, "scenario_command") as execute,
        ):
            with self.assertRaises(HTTPException) as ctx:
                commands._dispatch_scenario(payload, payload.command_id or "", "http://main/callback")
        self.assertEqual(ctx.exception.status_code, 409)
        execute.assert_not_called()

    def test_scenario_uses_same_body_for_preview_and_command(self) -> None:
        payload = self._scenario_payload()
        preview = {"executable": True, "blocking_reasons": [], "plan_hash": "hash-verified"}
        accepted = {
            "accepted": True,
            "command_id": payload.command_id,
            "execution_id": "exec-contract-001",
            "state": "ACCEPTED",
            "scenario_id": "inbound2-storage-b",
            "scenario_version": 1,
            "authority_owner": "MOVEMENT",
            "plan_hash": "hash-verified",
        }
        with (
            patch.object(commands.movement_client, "scenario_preview", return_value=preview) as preview_call,
            patch.object(commands.movement_client, "scenario_command", return_value=accepted) as command_call,
        ):
            result = commands._dispatch_scenario(
                payload,
                payload.command_id or "",
                "http://main/api/v1/movement/command-events",
            )

        preview_body = preview_call.call_args.args[2]
        command_body = command_call.call_args.args[2]
        self.assertEqual(preview_body, command_body)
        self.assertEqual(command_body["command_id"], payload.command_id)
        self.assertEqual(command_body["task_id"], 344)
        self.assertEqual(command_body["robot_name"], "tb3_2")
        self.assertEqual(command_body["scenario_version"], 1)
        self.assertFalse(command_body["dry_run"])
        self.assertFalse(command_body["skip_lift"])
        self.assertTrue(result.accepted)

    def test_scenario_uncertain_post_uses_existing_status_without_resend(self) -> None:
        payload = self._scenario_payload()
        preview = {"executable": True, "blocking_reasons": [], "plan_hash": "hash-verified"}
        status = {
            "command_id": payload.command_id,
            "execution_id": "exec-contract-001",
            "state": "RUNNING",
            "scenario_id": "inbound2-storage-b",
            "scenario_version": 1,
            "authority_owner": "MOVEMENT",
            "plan_hash": "hash-verified",
        }
        with (
            patch.object(commands.movement_client, "scenario_preview", return_value=preview),
            patch.object(
                commands.movement_client,
                "scenario_command",
                side_effect=commands.MovementClientError("movement request timed out"),
            ) as command_call,
            patch.object(commands.movement_client, "scenario_command_status", return_value=status) as lookup,
        ):
            result = commands._dispatch_scenario(payload, payload.command_id or "", "http://main/callback")

        command_call.assert_called_once()
        lookup.assert_called_once_with("tb3_2", payload.command_id)
        self.assertTrue(result.response["recovered_after_timeout"])

    def test_scenario_uncertain_post_resends_same_body_only_after_404(self) -> None:
        payload = self._scenario_payload()
        preview = {"executable": True, "blocking_reasons": [], "plan_hash": "hash-verified"}
        accepted = {
            "accepted": True,
            "command_id": payload.command_id,
            "execution_id": "exec-contract-001",
            "state": "ACCEPTED",
            "scenario_id": "inbound2-storage-b",
            "scenario_version": 1,
            "authority_owner": "MOVEMENT",
            "plan_hash": "hash-verified",
        }
        with (
            patch.object(commands.movement_client, "scenario_preview", return_value=preview),
            patch.object(
                commands.movement_client,
                "scenario_command",
                side_effect=[commands.MovementClientError("movement request timed out"), accepted],
            ) as command_call,
            patch.object(
                commands.movement_client,
                "scenario_command_status",
                side_effect=commands.MovementClientError("not found", status_code=404),
            ) as lookup,
        ):
            result = commands._dispatch_scenario(payload, payload.command_id or "", "http://main/callback")

        self.assertTrue(result.accepted)
        self.assertEqual(command_call.call_count, 2)
        lookup.assert_called_once_with("tb3_2", payload.command_id)
        first_body = command_call.call_args_list[0].args[2]
        second_body = command_call.call_args_list[1].args[2]
        self.assertEqual(first_body, second_body)
        self.assertEqual(first_body["command_id"], payload.command_id)
