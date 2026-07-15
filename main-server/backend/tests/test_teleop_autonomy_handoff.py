"""Bounded teleop must terminalize active autonomy before manual motion."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

from app.services import teleop


def test_nonstop_teleop_cancels_active_autonomy_before_manual_motion():
    movement = MagicMock()
    movement.nav_state.side_effect = [
        {"robot_online": True, "active_commands": ["cmd-active"]},
        {"robot_online": True, "active_commands": []},
    ]
    movement.cancel_command.return_value = {
        "accepted": True,
        "state": "CANCELED",
    }
    movement.manual_translate.return_value = {"accepted": True}

    with patch.object(teleop, "movement_client", movement):
        payload, status = teleop.call_movement(
            "tb3_1",
            "manual_translate",
            {"robot_name": "tb3_1", "direction": "forward"},
        )

    assert status == "ACCEPTED"
    assert payload["accepted"] is True
    assert movement.method_calls == [
        call.nav_state("tb3_1"),
        call.cancel_command("tb3_1", "cmd-active"),
        call.nav_state("tb3_1"),
        call.manual_translate(
            "tb3_1", {"robot_name": "tb3_1", "direction": "forward"}
        ),
    ]


def test_teleop_is_blocked_until_cancel_is_terminal_and_confirmed():
    movement = MagicMock()
    movement.nav_state.return_value = {
        "robot_online": True,
        "active_commands": ["cmd-active"],
    }
    movement.cancel_command.return_value = {
        "accepted": True,
        "state": "CANCEL_REQUESTED",
    }

    with patch.object(teleop, "movement_client", movement):
        payload, status = teleop.call_movement(
            "tb3_1",
            "manual_start",
            {"robot_name": "tb3_1", "command": "forward"},
        )

    assert status == "FAILED"
    assert "safe stop was not confirmed" in payload["error"]
    movement.manual_start.assert_not_called()


def test_manual_stop_remains_immediate_and_does_not_require_nav_state():
    movement = MagicMock()
    movement.manual_stop.return_value = {"accepted": True, "stopped": True}

    with patch.object(teleop, "movement_client", movement):
        payload, status = teleop.call_movement(
            "tb3_1", "manual_stop", {"robot_name": "tb3_1"}
        )

    assert status == "ACCEPTED"
    assert payload["stopped"] is True
    movement.nav_state.assert_not_called()
    movement.cancel_command.assert_not_called()
