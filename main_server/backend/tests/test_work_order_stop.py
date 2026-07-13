"""Immediate work-order safe-stop request and callback policy."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domains.execution import orchestrator
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
    with patch.object(work_orders, "MvpTaskRepository") as tasks, \
         patch.object(work_orders.evidence_runtime, "attach_orchestration", return_value=task), \
         patch.object(work_orders.evidence_runtime, "save_orchestration") as save, \
         patch.object(work_orders, "movement_client") as movement, \
         patch.object(work_orders, "MvpEventRepository"):
        tasks.return_value.get.return_value = task
        movement.cancel_command.return_value = {"accepted": True}
        result = work_orders.stop_work_order(conn, 42)

    movement.cancel_command.assert_called_once_with("robot1", "cmd-active")
    assert result["status"] == "CANCEL_REQUESTED"
    assert result["cargo_state"] == "LOADED"
    saved = save.call_args.args[2]
    assert saved["phase"] == "CANCEL_REQUESTED"
    assert saved["stop_request"]["cargo_state"] == "LOADED"


def test_stop_callback_with_loaded_cargo_requires_operator() -> None:
    conn = MagicMock()
    task = _task(cargo_loaded=True)
    orch = task["preset_snapshot"]["_orchestration"]
    orch["phase"] = "CANCEL_REQUESTED"
    orch["stop_request"] = {"cargo_state": "LOADED", "business_completed": False}
    with patch.object(orchestrator, "task_repo") as tasks, \
         patch.object(orchestrator, "evidence_runtime") as evidence, \
         patch.object(orchestrator, "event_repo"), \
         patch.object(orchestrator, "robot_repo"), \
         patch.object(orchestrator, "person_hazard"):
        tasks.return_value.get.return_value = task
        evidence.attach_orchestration.side_effect = lambda row, _conn: row
        result = orchestrator.advance_on_command_event(
            conn, 42, {"command_id": "cmd-active", "state": "STOPPED"},
        )

    assert result is not None
    saved = evidence.save_orchestration.call_args.args[2]
    assert saved["phase"] == "AWAITING_OPERATOR"
    assert saved["recovery"]["cargo_state"] == "LOADED"
    tasks.return_value.set_status.assert_not_called()


def test_stop_callback_with_empty_robot_cancels_task() -> None:
    conn = MagicMock()
    task = _task()
    orch = task["preset_snapshot"]["_orchestration"]
    orch["phase"] = "CANCEL_REQUESTED"
    orch["stop_request"] = {"cargo_state": "EMPTY", "business_completed": False}
    with patch.object(orchestrator, "task_repo") as tasks, \
         patch.object(orchestrator, "evidence_runtime") as evidence, \
         patch.object(orchestrator, "event_repo"), \
         patch.object(orchestrator, "robot_repo") as robots, \
         patch.object(orchestrator, "person_hazard"):
        tasks.return_value.get.return_value = task
        evidence.attach_orchestration.side_effect = lambda row, _conn: row
        orchestrator.advance_on_command_event(
            conn, 42, {"command_id": "cmd-active", "state": "CANCELLED"},
        )

    tasks.return_value.set_status.assert_called_once_with(42, "CANCELLED", clear_robot=True)
    robots.return_value.set_task.assert_called_once_with("robot1", "IDLE", None)
