"""Teleop workflow characterization tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.domains.movement import teleop
from app.domains.movement.client import MovementClientError
from app.models.robots import TeleopRequest


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        manual_override_nav=True,
        manual_hold_timeout_sec=2.5,
        manual_rotate_duration_sec=1.5,
        manual_rotate_angular_z=0.6,
        manual_translate_duration_sec=1.2,
        manual_translate_linear_x=0.2,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (" W ", "forward"),
        ("x", "backward"),
        ("A", "left"),
        ("d", "right"),
        ("space", "stop"),
    ],
)
def test_normalize_teleop_command_keeps_keyboard_aliases(raw: str, expected: str) -> None:
    assert teleop.normalize_teleop_command(raw) == expected


def test_normalize_teleop_command_rejects_unknown_input() -> None:
    with pytest.raises(HTTPException) as exc_info:
        teleop.normalize_teleop_command("jump")

    assert exc_info.value.status_code == 400


@pytest.mark.parametrize(
    ("command", "hold", "expected_type", "expected_fields"),
    [
        ("stop", False, "manual_stop", {"robot_name": "tb3_1"}),
        (
            "forward",
            True,
            "manual_start",
            {
                "robot_name": "tb3_1",
                "override_nav": True,
                "command": "forward",
                "linear_x": 0.2,
                "angular_z": 0.6,
                "timeout_sec": 2.5,
            },
        ),
        (
            "left",
            False,
            "manual_rotate",
            {
                "robot_name": "tb3_1",
                "override_nav": True,
                "direction": "left",
                "duration_sec": 1.5,
                "angular_z": 0.6,
            },
        ),
        (
            "backward",
            False,
            "manual_translate",
            {
                "robot_name": "tb3_1",
                "override_nav": True,
                "direction": "backward",
                "duration_sec": 1.2,
                "linear_x": 0.2,
            },
        ),
    ],
)
def test_build_teleop_movement_request_selects_endpoint_and_payload(
    command: str,
    hold: bool,
    expected_type: str,
    expected_fields: dict,
) -> None:
    with patch.object(teleop, "settings", _settings()):
        command_type, body = teleop.build_teleop_movement_request("tb3_1", command, hold)

    assert command_type == expected_type
    assert body == expected_fields


@pytest.mark.parametrize(
    ("command_type", "method_name"),
    [
        ("manual_rotate", "manual_rotate"),
        ("manual_translate", "manual_translate"),
        ("manual_start", "manual_start"),
        ("manual_stop", "manual_stop"),
    ],
)
def test_send_teleop_movement_command_dispatches_to_client(command_type: str, method_name: str) -> None:
    client = MagicMock()
    getattr(client, method_name).return_value = {"accepted": True}

    with patch.object(teleop, "movement_client", client):
        response = teleop.send_teleop_movement_command("tb3_1", command_type, {"robot_name": "tb3_1"})

    assert response == {"accepted": True}
    getattr(client, method_name).assert_called_once_with("tb3_1", {"robot_name": "tb3_1"})


def test_invoke_teleop_movement_converts_client_error_to_failed_result() -> None:
    with patch.object(
        teleop,
        "send_teleop_movement_command",
        side_effect=MovementClientError("movement unavailable"),
    ):
        response, state = teleop.invoke_teleop_movement("tb3_1", "manual_stop", {"robot_name": "tb3_1"})

    assert state == "FAILED"
    assert response == {"accepted": False, "error": "movement unavailable"}


def test_execute_teleop_records_failed_call_before_returning_502() -> None:
    transaction = MagicMock()
    conn = transaction.return_value.__enter__.return_value
    request = TeleopRequest(robot_id="tb3_1", command="stop")

    with (
        patch.object(teleop, "transaction", transaction),
        patch.object(teleop.robots, "exists", return_value=True),
        patch.object(
            teleop,
            "invoke_teleop_movement",
            return_value=({"accepted": False, "error": "movement unavailable"}, "FAILED"),
        ),
        patch.object(teleop, "record_teleop_result") as record_result,
    ):
        with pytest.raises(HTTPException) as exc_info:
            teleop.execute_teleop(request)

    assert exc_info.value.status_code == 502
    record_result.assert_called_once()
    assert record_result.call_args.kwargs["conn"] is conn
    assert record_result.call_args.kwargs["status_value"] == "FAILED"
