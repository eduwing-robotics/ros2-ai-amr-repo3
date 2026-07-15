"""Canonical robot-command cancellation and physical-stop regressions."""

from __future__ import annotations

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from nav_app.models import MovementCommandRequest, MovementStep
from nav_app.routers import movement_api
from nav_app.runtime import runtime
from nav_app.services import command_state


def _running_command() -> dict:
    return {
        "command_id": "cmd-cancel-1",
        "task_id": 42,
        "robot_name": "tb3_1",
        "state": "RUNNING",
        "current_step_action": "nav2_pose",
        "callback_url": "http://smartfactory-main.local:8088/api/v1/movement/command-events",
        "traffic_segments": ["seg-a"],
    }


def test_cancel_command_stops_motion_and_reports_terminal_once():
    command = _running_command()
    navigator = SimpleNamespace(
        nav=SimpleNamespace(cancelTask=MagicMock()),
        publish_stop_velocity=MagicMock(return_value=True),
    )
    lift = SimpleNamespace(enabled=True, stop=MagicMock())

    with (
        patch.object(runtime, "navigator", navigator),
        patch.object(runtime, "lift_client", lift),
        patch.object(command_state, "report_movement_result") as report_result,
        patch.object(command_state, "report_command_callback") as report_callback,
        patch.object(command_state, "_report_movement_robot_status") as report_status,
        patch.object(command_state, "release_traffic_locks_for_command") as release_locks,
    ):
        first = command_state.cancel_command(command)
        second = command_state.cancel_command(command)

    assert first["accepted"] is True
    assert first["state"] == "CANCELED"
    assert first["changed"] is True
    assert second["changed"] is False
    assert command["state"] == "CANCELED"
    assert command["reason"] == "operator_cancel"
    navigator.nav.cancelTask.assert_called_once_with()
    navigator.publish_stop_velocity.assert_called_once_with()
    lift.stop.assert_called_once_with()
    report_result.assert_called_once()
    report_callback.assert_called_once_with(command, "CANCELED", "canceled by operator")
    report_status.assert_called_once_with("tb3_1", None, "idle")
    release_locks.assert_called_once_with(command)


def test_canceled_command_is_terminal_and_cannot_be_restarted_by_executor():
    command = _running_command()
    command["state"] = "CANCELED"
    runtime.movement_commands[command["command_id"]] = command
    request = SimpleNamespace(command_id=command["command_id"])

    from nav_app.services import movement_executor

    with patch.object(movement_executor, "_report_command_callback") as callback:
        movement_executor.execute_movement_command(request)

    assert command["state"] == "CANCELED"
    callback.assert_not_called()


def test_executor_state_transition_cannot_overwrite_concurrent_cancel():
    from nav_app.services import movement_executor

    command = _running_command()
    command["state"] = "CANCELED"

    changed = movement_executor._transition_command_state(
        command,
        expected_states={"RUNNING"},
        state="DONE",
        message="completed",
    )

    assert changed is False
    assert command["state"] == "CANCELED"
    assert command.get("message") != "completed"


def test_cancel_command_does_not_confirm_when_physical_stop_fails():
    command = _running_command()
    navigator = SimpleNamespace(
        nav=SimpleNamespace(cancelTask=MagicMock()),
        publish_stop_velocity=MagicMock(side_effect=RuntimeError("base offline")),
    )

    with (
        patch.object(runtime, "navigator", navigator),
        patch.object(runtime, "lift_client", None),
        patch.object(command_state, "engage_estop") as escalate_estop,
        patch.object(command_state, "report_movement_result") as report_result,
        patch.object(command_state, "report_command_callback") as report_callback,
        patch.object(command_state, "_report_movement_robot_status") as report_status,
        patch.object(command_state, "release_traffic_locks_for_command") as release_locks,
    ):
        result = command_state.cancel_command(command)

    assert result["accepted"] is False
    assert result["state"] == "STOP_UNCONFIRMED"
    assert command["state"] == "STOP_UNCONFIRMED"
    escalate_estop.assert_called_once_with()
    report_result.assert_not_called()
    report_callback.assert_not_called()
    report_status.assert_called_once_with("tb3_1", None, "estop")
    release_locks.assert_called_once_with(command)


def test_cancel_before_accept_creates_terminal_tombstone():
    command_id = "cmd-cancel-before-accept"
    runtime.movement_commands.pop(command_id, None)

    first = command_state.cancel_command_id(command_id)
    second = command_state.cancel_command_id(command_id)

    assert first == {
        "accepted": True,
        "command_id": command_id,
        "state": "CANCELED",
        "changed": True,
        "tombstone": True,
    }
    assert second["accepted"] is True
    assert second["state"] == "CANCELED"
    assert second["changed"] is False
    assert runtime.movement_commands[command_id]["cancel_tombstone"] is True


def test_waiting_accept_cannot_overwrite_cancel_tombstone():
    command_id = "cmd-cancel-wins-register-race"
    register_waiting = threading.Event()
    release_register = threading.Event()
    underlying_lock = threading.Lock()

    class CancelFirstLock:
        def __enter__(self):
            if threading.current_thread().name == "waiting-command-register":
                register_waiting.set()
                if not release_register.wait(timeout=1.0):
                    raise AssertionError("register thread was not released")
            underlying_lock.acquire()
            return self

        def __exit__(self, exc_type, exc_value, traceback):
            underlying_lock.release()

    request = MovementCommandRequest(
        command_id=command_id,
        task_id=43,
        robot_name="tb3_1",
        steps=[MovementStep(action="nav2_pose", payload={})],
    )
    result: dict = {}
    errors: list[BaseException] = []

    def register_command() -> None:
        try:
            result["registration"] = movement_api._register_movement_command(request)
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)

    controlled_lock = CancelFirstLock()
    with (
        patch.object(runtime, "command_state_lock", controlled_lock),
        patch.object(runtime, "movement_commands", {}),
    ):
        thread = threading.Thread(target=register_command, name="waiting-command-register")
        thread.start()
        assert register_waiting.wait(timeout=1.0), "register did not wait on command_state_lock"

        canceled = command_state.cancel_command_id(command_id)
        release_register.set()
        thread.join(timeout=1.0)

        assert not thread.is_alive(), "register thread did not finish"
        assert errors == []
        response, created = result["registration"]
        assert canceled["tombstone"] is True
        assert created is False
        assert response == {
            "accepted": True,
            "command_id": command_id,
            "state": "CANCELED",
            "duplicate": True,
        }
        assert runtime.movement_commands[command_id]["state"] == "CANCELED"
        assert runtime.movement_commands[command_id]["cancel_tombstone"] is True
