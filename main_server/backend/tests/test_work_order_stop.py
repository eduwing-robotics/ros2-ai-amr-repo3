"""Immediate work-order safe-stop request and callback policy."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.domains.execution import orchestrator, safe_stop
from app.domains.work_orders import service as work_orders


def _task(*, cargo_loaded: bool = False, business_completed: bool = False) -> dict:
    steps = [
        {
            "kind": "dock_transfer",
            "status": "DONE" if cargo_loaded else "pending",
            "params": {"action": "load"},
        },
        {
            "kind": "move_to_point",
            "status": "dispatched",
            "command_id": "cmd-active",
            "params": {},
        },
    ]
    return {
        "task_id": 42,
        "task_type": "INBOUND",
        "status": "RUNNING",
        "assigned_robot_id": "robot1",
        "preset_snapshot": {
            "_orchestration": {
                "phase": "RUNNING",
                "steps": steps,
                "step_index": 1,
                "business_completed": business_completed,
            },
        },
    }


def test_stop_request_is_immediate_and_cargo_aware() -> None:
    conn = MagicMock()
    task = _task(cargo_loaded=True)
    with (
        patch.object(safe_stop.evidence, "attach_orchestration", return_value=task),
        patch.object(safe_stop.evidence, "save_orchestration") as save,
        patch.object(safe_stop, "movement_client") as movement,
        patch.object(safe_stop, "operational_events"),
    ):
        movement.cancel_command.return_value = {"accepted": True}
        result = safe_stop.request_work_order_stop(conn, 42)

    movement.cancel_command.assert_called_once_with("robot1", "cmd-active")
    assert result["status"] == "CANCEL_REQUESTED"
    assert result["cargo_state"] == "LOADED"
    saved = save.call_args.args[2]
    assert saved["phase"] == "CANCEL_REQUESTED"
    assert saved["stop_request"]["cargo_state"] == "LOADED"
    assert saved["stop_request"]["accepted"] is True


def test_stop_work_order_facade_delegates_to_execution() -> None:
    conn = MagicMock()
    expected = {"status": "CANCEL_REQUESTED"}
    with patch.object(work_orders.execution_safe_stop, "request_work_order_stop", return_value=expected) as request_stop:
        assert work_orders.stop_work_order(conn, 42) == expected
    request_stop.assert_called_once_with(conn, 42)


def test_repeated_persisted_stop_request_does_not_cancel_twice() -> None:
    conn = MagicMock()
    task = _task(cargo_loaded=True)
    orch = task["preset_snapshot"]["_orchestration"]
    orch["phase"] = "CANCEL_REQUESTED"
    orch["stop_request"] = {
        "command_id": "cmd-active",
        "cargo_state": "LOADED",
        "business_completed": False,
        "accepted": True,
    }
    with (
        patch.object(safe_stop.evidence, "attach_orchestration", return_value=task),
        patch.object(safe_stop, "movement_client") as movement,
        patch.object(safe_stop.evidence, "save_orchestration") as save,
        patch.object(safe_stop, "operational_events") as events,
    ):
        result = safe_stop.request_work_order_stop(conn, 42)

    assert result["status"] == "CANCEL_REQUESTED"
    assert result["cargo_state"] == "LOADED"
    movement.cancel_command.assert_not_called()
    save.assert_not_called()
    events.append.assert_not_called()


def test_stop_event_failure_propagates_after_movement_cancel() -> None:
    conn = MagicMock()
    task = _task()
    with (
        patch.object(safe_stop.evidence, "attach_orchestration", return_value=task),
        patch.object(safe_stop.evidence, "save_orchestration") as save,
        patch.object(safe_stop, "movement_client") as movement,
        patch.object(safe_stop.operational_events, "append", side_effect=RuntimeError("event write failed")),
    ):
        movement.cancel_command.return_value = {"accepted": True}
        with pytest.raises(RuntimeError, match="event write failed"):
            safe_stop.request_work_order_stop(conn, 42)

    movement.cancel_command.assert_called_once_with("robot1", "cmd-active")
    save.assert_called_once()


def test_stop_callback_with_loaded_cargo_requires_operator() -> None:
    conn = MagicMock()
    task = _task(cargo_loaded=True)
    orch = task["preset_snapshot"]["_orchestration"]
    orch["phase"] = "CANCEL_REQUESTED"
    orch["stop_request"] = {"cargo_state": "LOADED", "business_completed": False}
    with (
        patch.object(orchestrator, "tasks") as tasks,
        patch.object(orchestrator, "evidence") as evidence,
        patch.object(orchestrator, "operational_events"),
        patch.object(orchestrator, "robots"),
        patch.object(orchestrator, "person_hazard"),
    ):
        tasks.get_task.return_value = task
        evidence.attach_orchestration.side_effect = lambda row, _conn: row
        result = orchestrator.advance_on_command_event(
            conn,
            42,
            {"command_id": "cmd-active", "state": "STOPPED"},
        )

    assert result is not None
    saved = evidence.save_orchestration.call_args.args[2]
    assert saved["phase"] == "AWAITING_OPERATOR"
    assert saved["recovery"]["cargo_state"] == "LOADED"
    tasks.set_status.assert_not_called()


def test_stop_callback_with_empty_robot_cancels_task() -> None:
    conn = MagicMock()
    task = _task()
    orch = task["preset_snapshot"]["_orchestration"]
    orch["phase"] = "CANCEL_REQUESTED"
    orch["stop_request"] = {"cargo_state": "EMPTY", "business_completed": False}
    with (
        patch.object(orchestrator, "tasks") as tasks,
        patch.object(orchestrator, "evidence") as evidence,
        patch.object(orchestrator, "operational_events"),
        patch.object(orchestrator, "robots") as robots,
        patch.object(orchestrator, "person_hazard"),
    ):
        tasks.get_task.return_value = task
        evidence.attach_orchestration.side_effect = lambda row, _conn: row
        orchestrator.advance_on_command_event(
            conn,
            42,
            {"command_id": "cmd-active", "state": "CANCELLED"},
        )

    tasks.set_status.assert_called_once_with(conn, 42, "CANCELLED", clear_robot=True)
    robots.set_task.assert_called_once_with(conn, "robot1", "IDLE", None)


def test_stop_terminal_event_is_not_applied_twice() -> None:
    conn = MagicMock()
    task = _task()
    orch = task["preset_snapshot"]["_orchestration"]
    orch["phase"] = "CANCEL_REQUESTED"
    orch["stop_request"] = {"cargo_state": "EMPTY", "business_completed": False}
    with (
        patch.object(orchestrator, "tasks") as tasks,
        patch.object(orchestrator, "evidence") as evidence,
        patch.object(orchestrator, "operational_events") as events,
        patch.object(orchestrator, "robots"),
        patch.object(orchestrator, "person_hazard"),
    ):
        tasks.get_task.return_value = task
        evidence.attach_orchestration.side_effect = lambda row, _conn: row
        first = orchestrator.advance_on_command_event(
            conn, 42, {"command_id": "cmd-active", "state": "STOPPED"}
        )
        second = orchestrator.advance_on_command_event(
            conn, 42, {"command_id": "cmd-active", "state": "STOPPED"}
        )

    assert first is not None
    assert second is None
    tasks.set_status.assert_called_once()
    assert events.append.call_count == 1
