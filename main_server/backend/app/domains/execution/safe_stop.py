"""Execution coordinator for an immediate Work Order safe-stop request."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.db.postgres import operational_events
from app.db.postgres import tasks as postgres_tasks
from app.domains.execution import evidence
from app.domains.execution import state as orch_state
from app.domains.movement.client import MovementClientError, movement_client


def _cargo_state(steps: list[dict[str, Any]]) -> str:
    return orch_state.cargo_state_after_steps(steps)


def _response(
    order_id: int,
    *,
    command_id: str | None,
    cargo_state: str,
    business_completed: bool,
    accepted: bool,
    status: str = "CANCEL_REQUESTED",
) -> dict[str, Any]:
    return {
        "order_id": order_id,
        "task_id": order_id,
        "status": status,
        "accepted": accepted,
        "command_id": command_id,
        "cargo_state": cargo_state,
        "business_completed": business_completed,
    }


def request_work_order_stop(conn, order_id: int) -> dict[str, Any]:
    """Cancel the active Movement command and persist its recovery context once."""
    task = evidence.attach_orchestration(postgres_tasks.get_task(conn, order_id), conn)
    if not task or task.get("task_type") not in {"INBOUND", "OUTBOUND"}:
        raise HTTPException(status_code=404, detail="work order not found")
    if str(task.get("status") or "").upper() != "RUNNING":
        raise HTTPException(status_code=409, detail="work_order_stop_requires_running")

    robot_id = task.get("assigned_robot_id")
    orch = (task.get("preset_snapshot") or {}).get("_orchestration") or {}
    execution = orch_state.RobotTaskExecutionState.wrap(orch)
    steps = execution.steps
    step_index = execution.step_index
    step = steps[step_index] if 0 <= step_index < len(steps) else {}
    command_id = step.get("command_id")
    if not robot_id:
        raise HTTPException(status_code=409, detail="work_order_has_no_active_command")

    if not command_id or not orch_state.is_dispatched_robot_task_step(step):
        if execution.phase == orch_state.PHASE_AWAITING_OPERATOR:
            return _response(
                order_id,
                command_id=None,
                cargo_state=str(execution.recovery.get("cargo_state") or "UNKNOWN"),
                business_completed=execution.business_completed,
                accepted=True,
                status="AWAITING_OPERATOR",
            )
        try:
            movement_response = movement_client.manual_stop(str(robot_id), {"robot_name": str(robot_id)})
        except MovementClientError as exc:
            raise HTTPException(status_code=409, detail="work_order_stop_unconfirmed") from exc

        execution.transition_to(orch_state.PHASE_AWAITING_OPERATOR)
        execution.replace_recovery({
            "reason": "operator_safe_stop_no_active_command",
            "robot_id": str(robot_id),
            "cargo_state": "UNKNOWN",
        })
        evidence.save_orchestration(conn, order_id, orch)
        operational_events.append(
            conn,
            event_type=orch_state.EVENT_AWAITING_OPERATOR,
            task_id=order_id,
            robot_id=str(robot_id),
            message=f"work order {order_id} stopped without an active command — recovery required",
            payload={"cargo_state": "UNKNOWN", "movement": movement_response, "reason": "missing_active_command"},
        )
        return _response(
            order_id,
            command_id=None,
            cargo_state="UNKNOWN",
            business_completed=execution.business_completed,
            accepted=True,
            status="AWAITING_OPERATOR",
        )

    previous = orch.get("stop_request") or {}
    if execution.phase == orch_state.PHASE_CANCEL_REQUESTED and str(previous.get("command_id") or "") == str(command_id):
        return _response(
            order_id,
            command_id=str(command_id),
            cargo_state=str(previous.get("cargo_state") or "UNKNOWN"),
            business_completed=bool(previous.get("business_completed")),
            accepted=bool(previous.get("accepted", True)),
        )

    try:
        if str(step.get("kind")) == "scenario":
            movement_response = movement_client.scenario_safe_stop(str(robot_id), str(command_id))
        else:
            movement_response = movement_client.cancel_command(str(robot_id), str(command_id))
    except MovementClientError as exc:
        if exc.status_code == 404:
            raise HTTPException(status_code=501, detail="movement_command_cancel_api_missing") from exc
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    scenario_progress = step.get("scenario_progress") or {}
    reported_cargo = str(scenario_progress.get("cargo_state") or "").upper()
    if execution.business_completed:
        cargo_state = "EMPTY"
    elif reported_cargo in {"EMPTY", "LOADED"}:
        cargo_state = reported_cargo
    else:
        cargo_state = _cargo_state(steps)
    accepted = bool(movement_response.get("accepted", True))
    execution.transition_to(orch_state.PHASE_CANCEL_REQUESTED)
    orch["stop_request"] = {
        "command_id": str(command_id),
        "robot_id": str(robot_id),
        "cargo_state": cargo_state,
        "business_completed": execution.business_completed,
        "accepted": accepted,
    }
    evidence.save_orchestration(conn, order_id, orch)
    operational_events.append(
        conn,
        event_type="WORK_ORDER_STOP_REQUESTED",
        task_id=order_id,
        robot_id=str(robot_id),
        message=f"work order {order_id} safe stop requested",
        payload={"command_id": command_id, "cargo_state": cargo_state, "movement": movement_response},
    )
    return _response(
        order_id,
        command_id=str(command_id),
        cargo_state=cargo_state,
        business_completed=execution.business_completed,
        accepted=accepted,
    )
