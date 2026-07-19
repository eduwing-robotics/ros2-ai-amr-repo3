"""책임: task orchestration과 callback 기반 상태 전이를 소유한다.
비책임: Movement 주행 방식과 운영자의 복구 판단."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from app.db.connection import TASK_EVENT_LOCK_NAMESPACE, advisory_xact_lock_for_key
from app.db.postgres import operational_events, robots, runtime_records, tasks
from app.domains.execution import evidence, recovery, transitions
from app.domains.execution import state as orch_state
from app.domains.execution import steps as scenario_steps
from app.domains.movement import commands
from app.domains.movement.client import movement_robot_key
from app.domains.movement.health import get_movement_health
from app.domains.movement.navigation import movement_reason
from app.domains.safety import hazard as person_hazard
from app.domains.vision import evidence as lift_load_evidence
from app.domains.warehouse import inventory as inventory_ops
from app.models.robot_commands import RobotCommandRequest
from app.models.tasks import RobotTaskStepStatus

logger = logging.getLogger(__name__)

TERMINAL_STEP_STATES = {"DONE", "FAILED", "ABORTED", "CANCELLED"}


def _accept_event_sequence(step: dict[str, Any], event: dict[str, Any], source: str) -> bool:
    sequence = event.get("sequence")
    if sequence is None:
        return True
    sequence = int(sequence)
    last_sequence = step.get("last_event_sequence")
    if last_sequence is not None and sequence <= int(last_sequence):
        return False
    expected_sequence = int(last_sequence) + 1 if last_sequence is not None else 0
    if sequence > expected_sequence:
        step["callback_sequence_gap"] = {"expected": expected_sequence, "received": sequence}
    elif source == "task_progress_poller":
        step.pop("callback_sequence_gap", None)
    step["last_event_sequence"] = sequence
    return True


def _handle_cancel_requested(
    conn,
    task_id: int,
    task: dict[str, Any],
    execution: orch_state.RobotTaskExecutionState,
    event: dict[str, Any],
    event_name: str,
    scenario_progress: dict[str, Any],
    source: str,
) -> tuple[bool, dict[str, Any] | None]:
    """중단 callback을 화물·업무 완료 상태에 맞게 확정하고 처리 여부와 Task를 반환한다."""
    if execution.phase != orch_state.RobotTaskOrchestrationPhase.CANCEL_REQUESTED:
        return False, None
    step = execution.steps[execution.step_index]
    stop_request = execution.data.get("stop_request") or {}
    if event_name not in {"CANCELLED", "CANCELED", "STOPPED", "ABORTED"}:
        if event_name in _step_done_events(str(step.get("kind") or "move_to_point")):
            execution.transition_to(orch_state.RobotTaskOrchestrationPhase.RUNNING)
            execution.data.pop("stop_request", None)
            evidence.save_orchestration(conn, task_id, execution.data)
            return False, None
        return True, None

    step["status"] = "CANCELLED"
    business_completed = bool(
        scenario_progress.get("business_completed")
        if str(step.get("kind")) == "inout_scenario"
        else stop_request.get("business_completed")
    )
    reported_cargo = str(scenario_progress.get("cargo_state") or "").upper()
    cargo_state = (
        reported_cargo
        if reported_cargo in {"EMPTY", "LOADED", "UNKNOWN"}
        else str(stop_request.get("cargo_state") or "UNKNOWN")
    )
    robot_id = task.get("assigned_robot_id")
    if business_completed:
        execution.return_status = "PARK_FAILED"
        execution.data["parking_error"] = {
            "state": event_name,
            "reason": "operator_safe_stop",
            "event": event,
        }
        execution.transition_to(orch_state.RobotTaskOrchestrationPhase.DONE)
        evidence.save_orchestration(conn, task_id, execution.data)
        result = finalize_running_task_as_done(conn, task_id, source=source)
    elif cargo_state == "LOADED":
        execution.transition_to(orch_state.RobotTaskOrchestrationPhase.AWAITING_OPERATOR)
        execution.replace_recovery({"reason": "operator_safe_stop", "robot_id": robot_id, "cargo_state": cargo_state})
        evidence.save_orchestration(conn, task_id, execution.data)
        result = _task(conn, task_id)
    else:
        execution.transition_to(orch_state.RobotTaskOrchestrationPhase.CANCELLED)
        evidence.save_orchestration(conn, task_id, execution.data)
        tasks.set_status(conn, task_id, "CANCELLED", clear_robot=True)
        if robot_id:
            robots.set_task(conn, str(robot_id), "IDLE", None)
            person_hazard.on_robot_task_terminal(str(robot_id))
        result = _task(conn, task_id)
    operational_events.append(
        conn,
        event_type="WORK_ORDER_STOPPED",
        task_id=task_id,
        robot_id=robot_id,
        message=f"work order {task_id} safe stop confirmed ({cargo_state})",
        payload={"event": event, "cargo_state": cargo_state, "business_completed": business_completed},
    )
    return True, result


def _handle_failed_event(
    conn,
    task_id: int,
    task: dict[str, Any],
    execution: orch_state.RobotTaskExecutionState,
    event: dict[str, Any],
    event_name: str,
    scenario_progress: dict[str, Any],
    source: str,
) -> dict[str, Any] | None:
    """실패 callback을 주차 실패·운영자 복구·일반 실패 중 하나로 확정해 반환한다."""
    step_index = execution.step_index
    step = execution.steps[step_index]
    event_command_id = event.get("command_id")
    step["status"] = event_name
    if execution.business_completed and str(step.get("kind")) in {"move_to_point", "aruco_align", "inout_scenario"}:
        execution.return_status = "PARK_FAILED"
        execution.data["parking_error"] = {
            "state": event_name,
            "command_id": event_command_id,
            "event": event,
        }
        execution.transition_to(orch_state.RobotTaskOrchestrationPhase.DONE)
        evidence.save_orchestration(conn, task_id, execution.data)
        finished = finalize_running_task_as_done(conn, task_id, source=source)
        operational_events.append(
            conn,
            event_type="TASK_PARKING_FAILED",
            task_id=task_id,
            robot_id=task.get("assigned_robot_id"),
            message=f"task {task_id} business completed; parking {event_name.lower()}",
            payload={"task_id": task_id, "event": event},
        )
        return finished

    event_payload = event.get("event") if isinstance(event.get("event"), dict) else event
    reason = str((event_payload or {}).get("reason_code") or (event_payload or {}).get("reason") or "").lower()
    cargo_state = str(scenario_progress.get("cargo_state") or "").upper()
    if cargo_state not in {"EMPTY", "LOADED"}:
        cargo_state = (
            "UNKNOWN"
            if str(step.get("kind")) == "inout_scenario"
            else orch_state.cargo_state_after_steps(execution.steps)
        )
    estop_failure = event_name == "ABORTED" and "estop" in reason
    if cargo_state in {"LOADED", "UNKNOWN"} or estop_failure:
        recovery_reason = "movement_failure_loaded_cargo" if cargo_state in {"LOADED", "UNKNOWN"} else "movement_estop"
        execution.transition_to(orch_state.RobotTaskOrchestrationPhase.AWAITING_OPERATOR)
        execution.replace_recovery(
            {
                "reason": recovery_reason,
                "robot_id": task.get("assigned_robot_id"),
                "cargo_state": cargo_state,
                "failed_step_index": step_index,
                "failed_command_id": event_command_id,
                "movement_state": event_name,
            }
        )
        evidence.save_orchestration(conn, task_id, execution.data)
        operational_events.append(
            conn,
            event_type=orch_state.EVENT_AWAITING_OPERATOR,
            task_id=task_id,
            robot_id=task.get("assigned_robot_id"),
            message=f"task {task_id} step {step_index} {event_name.lower()} — recovery required ({cargo_state})",
            payload={
                "task_id": task_id,
                "event": event,
                "step_index": step_index,
                "cargo_state": cargo_state,
                "reason": recovery_reason,
            },
        )
        return _task(conn, task_id)

    execution.transition_to(event_name)
    evidence.save_orchestration(conn, task_id, execution.data)
    tasks.set_status(conn, task_id, "FAILED", clear_robot=True)
    robot_id = task.get("assigned_robot_id")
    if robot_id:
        robots.set_task(conn, robot_id, "IDLE", None)
        person_hazard.on_robot_task_terminal(str(robot_id))
    operational_events.append(
        conn,
        event_type=f"TASK_STEP_{event_name}",
        task_id=task_id,
        robot_id=robot_id,
        message=f"task {task_id} step {step_index} {event_name}",
        payload={"task_id": task_id, "event": event, "step_index": step_index},
    )
    return _task(conn, task_id)


def _settle_scenario_unload(
    conn,
    task_id: int,
    task: dict[str, Any],
    execution: orch_state.RobotTaskExecutionState,
    event: dict[str, Any],
    scenario_progress: dict[str, Any],
) -> None:
    """검증된 UNLOAD 완료에서만 재고와 업무 완료를 같은 transaction에 한 번 반영한다."""
    unload_completed = (
        str(event.get("event") or event.get("state") or "").upper() == "STEP_COMPLETED"
        and str(scenario_progress.get("current_step_code") or "") == "UNLOAD"
        and int(scenario_progress.get("last_completed_step_index") or -1) == scenario_steps.UNLOAD_STEP_INDEX
        and str(scenario_progress.get("cargo_state") or "").upper() == "EMPTY"
        and scenario_progress.get("business_completed") is True
    )
    if str(execution.steps[execution.step_index].get("kind")) != "inout_scenario":
        return
    if execution.business_completed or not unload_completed:
        return
    inventory_ops.settle_inventory_for_completed_task(conn, task_id)
    execution.mark_business_completed(at_step=scenario_steps.UNLOAD_STEP_INDEX)
    operational_events.append(
        conn,
        event_type="TASK_BUSINESS_COMPLETED",
        task_id=task_id,
        robot_id=task.get("assigned_robot_id"),
        command_id=str(event.get("command_id")),
        message=f"task {task_id} scenario UNLOAD completed; parking remains",
        payload={"task_id": task_id, "scenario_progress": scenario_progress},
    )


def _handle_successful_event(
    conn,
    task_id: int,
    task: dict[str, Any],
    execution: orch_state.RobotTaskExecutionState,
    event: dict[str, Any],
    source: str,
    command_definition_id: int,
) -> dict[str, Any] | None:
    """정상 callback을 현재 단계 완료 또는 진행 증거로 저장하고 다음 명령 접수 결과를 반환한다."""
    steps = execution.steps
    step_index = execution.step_index
    step = steps[step_index]
    event_name = transitions.normalize_movement_event(event)
    event_command_id = event.get("command_id")
    scenario_progress = execution.data.get("scenario_progress") or {}
    if event_name == "DONE" and str(step.get("kind")) == "inout_scenario":
        gate_errors = transitions.scenario_done_gate_errors(scenario_progress)
        if gate_errors:
            step["completion_gate_errors"] = gate_errors
            evidence.save_orchestration(conn, task_id, execution.data)
            operational_events.append(
                conn,
                event_type="TASK_SCENARIO_DONE_GATE_BLOCKED",
                task_id=task_id,
                robot_id=task.get("assigned_robot_id"),
                command_id=str(event_command_id),
                message=f"task {task_id} COMMAND_DONE missing final safety fields",
                payload={"missing_or_invalid": gate_errors, "scenario_progress": scenario_progress},
            )
            return None
        step.pop("completion_gate_errors", None)

    if event_name not in _step_done_events(str(step.get("kind") or "move_to_point")):
        if event.get("sequence") is not None or str(step.get("kind")) == "inout_scenario":
            evidence.save_orchestration(conn, task_id, execution.data)
        return None

    if str(step.get("kind")) == "dock_transfer":
        try:
            lift_load_evidence.evaluate_lift_load_evidence_and_record(conn, task, step, command_definition_id)
        except Exception:
            logger.exception("lift-load evidence record-only hook failed")

    transfer_action = str(step.get("transfer_action") or (step.get("params") or {}).get("action") or "").lower()
    if transfer_action == "unload":
        inventory_ops.settle_inventory_for_completed_task(conn, task_id)
        execution.mark_business_completed(at_step=step_index)

    step["status"] = "DONE"
    if str(step.get("kind")) == "move_to_point" and task.get("assigned_robot_id"):
        person_hazard.on_move_to_point_step_done(str(task["assigned_robot_id"]))
    step_index = execution.advance_step()
    if execution.business_completed and step_index < len(steps):
        next_kind = str(steps[step_index].get("kind") or "")
        execution.return_status = "PARKING" if next_kind == "aruco_align" else "RETURNING_HOME"

    if step_index >= len(steps):
        if execution.business_completed:
            execution.return_status = "PARKED"
        execution.transition_to(orch_state.RobotTaskOrchestrationPhase.DONE)
        evidence.save_orchestration(conn, task_id, execution.data)
        finished = finalize_running_task_as_done(conn, task_id, source=source)
        operational_events.append(
            conn,
            event_type="TASK_ORCHESTRATION_DONE",
            task_id=task_id,
            robot_id=task.get("assigned_robot_id"),
            message=f"task {task_id} all steps done",
            payload={"task_id": task_id},
        )
        return finished

    evidence.save_orchestration(conn, task_id, execution.data)
    try:
        dispatch_current_step(conn, task_id)
    except HTTPException as exc:
        return _handle_step_dispatch_exception(conn, task_id, exc, source)
    operational_events.append(
        conn,
        event_type="TASK_STEP_DONE",
        task_id=task_id,
        robot_id=task.get("assigned_robot_id"),
        message=f"task {task_id} step advanced to {step_index}",
        payload={"task_id": task_id, "step_index": step_index, "event": event},
    )
    return _task(conn, task_id)


def _orchestration_phase(conn, task_id: int) -> str | None:
    task = evidence.attach_orchestration(tasks.get_task(conn, task_id), conn)
    if not task:
        return None
    orchestration = (task.get("preset_snapshot") or {}).get("_orchestration") or {}
    phase = str(orchestration.get("phase") or "") or None
    return orch_state.normalize_phase(phase) if phase else None


def finalize_running_task_as_done(conn, task_id: int, source: str = "operator") -> dict[str, Any]:
    """RUNNING task만 DONE으로 확정하며 재고·종료 증적을 같은 transaction에 기록한다."""
    task = tasks.get_task(conn, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task["status"] != "RUNNING":
        raise HTTPException(status_code=409, detail=f"task is not running (status={task['status']})")
    if _orchestration_phase(conn, task_id) in orch_state.HOLD_PHASES:
        raise HTTPException(status_code=409, detail="held_task_complete_blocked_use_recovery")
    return _finish_task(conn, task_id, "DONE", source)


def finalize_non_running_task_as_cancelled(conn, task_id: int, source: str = "operator") -> dict[str, Any]:
    """미실행 task만 CANCELLED로 확정하며 활성 작업의 안전 중단에는 사용하지 않는다."""
    task = tasks.get_task(conn, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task["status"] == "RUNNING":
        raise HTTPException(status_code=409, detail="running_task_cancel_blocked_use_recovery")
    return _finish_task(conn, task_id, "CANCELLED", source)


def _finish_task(conn, task_id: int, to_status: str, source: str) -> dict[str, Any]:
    task = tasks.get_task(conn, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task["status"] in {"DONE", "CANCELLED"}:
        raise HTTPException(status_code=409, detail=f"task already {task['status']}")
    robot_id = task.get("assigned_robot_id")
    if to_status == "DONE":
        inventory_ops.settle_inventory_for_completed_task(conn, task_id)
    tasks.set_status(conn, task_id, to_status, clear_robot=bool(robot_id and to_status in {"CANCELLED", "FAILED"}))
    if robot_id:
        robots.set_task(conn, robot_id, "IDLE", None)
        person_hazard.on_robot_task_terminal(str(robot_id))
    tasks.add_history(conn, task_id, task["status"], to_status, to_status.lower(), source)
    operational_events.append(
        conn,
        event_type=f"TASK_{to_status}",
        task_id=task_id,
        robot_id=robot_id,
        message=f"task {task_id} {to_status.lower()}",
        payload={"task_id": task_id, "robot_id": robot_id},
    )
    db_result = "COMPLETED" if to_status == "DONE" else to_status
    if not (to_status == "DONE" and str(task.get("task_type") or "").upper() in {"INBOUND", "OUTBOUND"}):
        evidence.finalize_task_log(conn, task, db_result)
    return tasks.get_task(conn, task_id)


def _step_done_events(kind: str) -> set[str]:
    if kind == "move_to_point":
        return {"ARRIVED", "DONE"}
    return {"DONE"}


def _task(conn, task_id: int) -> dict[str, Any] | None:
    return evidence.attach_orchestration(tasks.get_task(conn, task_id), conn)


def _orch(task: dict[str, Any]) -> dict[str, Any]:
    snap = task.get("preset_snapshot") or {}
    orch = snap.get("_orchestration")
    if not orch:
        raise HTTPException(status_code=409, detail="task has no orchestration state")
    return orch


# commands 시드는 move/dock 5-step만 정의하므로, leave_dock·aruco_align 같은
# 시드 외 step를 건너뛴 위치로 step_index를 환산해야 seq 매핑이 어긋나지 않는다.
_SEEDED_STEP_KINDS = {"move_to_point", "dock_transfer"}


def _seed_step_index(steps: list[dict[str, Any]], step_index: int) -> int:
    return sum(1 for step in steps[:step_index] if str(step.get("kind")) in _SEEDED_STEP_KINDS)


def start_task_orchestration(
    conn, task_id: int, callback_base_url: str | None = None, source: str = "operator"
) -> dict[str, Any]:
    """task lock 후 단일 Movement scenario를 전송하며 반환은 시작 접수이지 완료가 아니다."""
    advisory_xact_lock_for_key(conn, TASK_EVENT_LOCK_NAMESPACE, task_id)
    task = _task(conn, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task["status"] != "ASSIGNED":
        raise HTTPException(status_code=409, detail=f"task is not assigned (status={task['status']})")
    robot_id = task.get("assigned_robot_id")
    if not robot_id:
        raise HTTPException(status_code=409, detail="task has no assigned robot")

    fresh_health = get_movement_health([str(robot_id)], force=True).get(str(robot_id), {})
    readiness_reason, _ = movement_reason(fresh_health)
    if readiness_reason != "ok":
        tasks.unassign_to_queue(conn, task_id)
        robots.set_task(conn, str(robot_id), "IDLE", None)
        tasks.add_history(
            conn,
            task_id,
            "ASSIGNED",
            "QUEUED",
            f"Movement readiness deferred: {readiness_reason}",
            source,
        )
        operational_events.append(
            conn,
            event_type="TASK_READINESS_DEFERRED",
            task_id=task_id,
            robot_id=str(robot_id),
            message=f"task {task_id} returned to queue: {readiness_reason}",
            payload={"reason": readiness_reason, "source": source},
        )
        raise HTTPException(
            status_code=409,
            detail={"code": "movement_not_ready", "reason": readiness_reason},
        )

    scenario = evidence.build_scenario_from_task(conn, task)
    steps = evidence.plan_command_steps(conn, scenario, task_id, robot_id)
    orchestration = orch_state.new_orchestration(steps, callback_base_url=callback_base_url)
    evidence.save_orchestration(conn, task_id, orchestration)

    tasks.set_status(conn, task_id, "RUNNING")
    robots.set_task(conn, robot_id, "RUNNING", task_id)
    tasks.add_history(conn, task_id, "ASSIGNED", "RUNNING", "orchestrator started", source)

    try:
        command_id = dispatch_current_step(conn, task_id)
    except HTTPException as exc:
        _handle_step_dispatch_exception(conn, task_id, exc, source)
        raise
    operational_events.append(
        conn,
        event_type="TASK_ORCHESTRATION_STARTED",
        robot_id=robot_id,
        message=f"task {task_id} step0 dispatched ({command_id})",
        payload={"task_id": task_id, "command_id": command_id, "step_count": len(steps)},
    )
    return {
        "task": _task(conn, task_id),
        "robot_id": robot_id,
        "command_id": command_id,
        "step_count": len(steps),
    }


def dispatch_current_step(conn, task_id: int) -> str:
    """현재 미전송 step 하나만 전송·영속화하며 중복 dispatch를 거부한다."""
    task = _task(conn, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    robot_id = task.get("assigned_robot_id")
    if not robot_id:
        raise HTTPException(status_code=409, detail="task has no robot")

    orch = _orch(task)
    steps = orch_state.get_steps(orch)
    step_index = orch_state.get_step_index(orch)
    if step_index >= len(steps):
        raise HTTPException(status_code=409, detail="no step to dispatch")

    step = steps[step_index]
    task = _task(conn, task_id) or {}
    command_definition_id = evidence.resolve_command_definition_id(
        conn,
        task,
        _seed_step_index(steps, step_index),
        str(step.get("kind") or "move_to_point"),
    )
    command_id = commands.default_command_id(task_id, robot_id, str(step.get("kind")))
    callback_url = ""
    base = orch.get("callback_base_url")
    if base:
        callback_url = commands.resolve_callback_url(None, base)

    if str(step.get("kind")) in {"move_to_point", "inout_scenario"}:
        monitor_ready = person_hazard.enable_monitor(
            robot_id,
            task_id,
            command_id=command_id,
            step_kind=str(step.get("kind")),
        )
        if not monitor_ready:
            raise HTTPException(
                status_code=503,
                detail={"code": "person_hazard_monitor_unavailable", "robot_id": robot_id},
            )

    payload = RobotCommandRequest(
        robot_id=robot_id,
        kind=step["kind"],
        command_id=command_id,
        dry_run=False,
        params=step.get("params") or {},
        task_id=task_id,
        callback_url=callback_url or None,
    )
    result = commands.dispatch_robot_command(conn, payload, request=None)
    if not result.accepted:
        step["status"] = "FAILED"
        cargo_state = orch_state.cargo_state_after_steps(steps)
        if cargo_state == "LOADED":
            orch_state.set_phase(orch, orch_state.RobotTaskOrchestrationPhase.AWAITING_OPERATOR)
            orch_state.RobotTaskExecutionState.wrap(orch).replace_recovery(
                {
                    "reason": "movement_dispatch_rejected_loaded_cargo",
                    "robot_id": robot_id,
                    "cargo_state": cargo_state,
                    "failed_step_index": step_index,
                }
            )
        else:
            orch_state.set_phase(orch, orch_state.RobotTaskOrchestrationPhase.FAILED)
            tasks.set_status(conn, task_id, "FAILED", clear_robot=True)
            robots.set_task(conn, robot_id, "IDLE", None)
            person_hazard.on_robot_task_terminal(robot_id)
        orch_state.set_steps(orch, steps)
        evidence.save_orchestration(conn, task_id, orch)
        raise HTTPException(status_code=502, detail="step dispatch rejected")

    step["status"] = RobotTaskStepStatus.DISPATCHED
    step["command_id"] = result.command_id
    if str(step.get("kind")) == "inout_scenario":
        for timeline_step in step.get("route_timeline") or []:
            timeline_step["command_id"] = result.command_id
    orch_state.set_steps(orch, steps)
    evidence.save_orchestration(conn, task_id, orch)
    evidence.record_movement_evidence(
        conn,
        task_id=task_id,
        command_definition_id=command_definition_id,
        event_type="DISPATCHED",
        data_json={
            "command_id": result.command_id,
            "robot_id": robot_id,
            "kind": step["kind"],
            "command_definition_id": command_definition_id,
        },
    )
    return result.command_id


def _handle_step_dispatch_exception(conn, task_id: int, exc: HTTPException, source: str) -> dict[str, Any] | None:
    """완료된 step_index를 저장하고 다음 명령 전송 실패 시 안전하게 중단한다."""

    task = _task(conn, task_id)
    if not task or task.get("status") != "RUNNING":
        return task
    orch = _orch(task)
    execution = orch_state.RobotTaskExecutionState.wrap(orch)
    steps = execution.steps
    step_index = execution.step_index
    if 0 <= step_index < len(steps):
        steps[step_index]["status"] = "FAILED"
        steps[step_index]["dispatch_error"] = str(exc.detail)
        execution.steps = steps

    robot_id = task.get("assigned_robot_id")
    cargo_state = orch_state.cargo_state_after_steps(steps)
    if execution.business_completed:
        execution.return_status = "PARK_FAILED"
        orch["parking_error"] = {"state": "DISPATCH_FAILED", "reason": str(exc.detail)}
        execution.transition_to(orch_state.RobotTaskOrchestrationPhase.DONE)
        evidence.save_orchestration(conn, task_id, orch)
        result = finalize_running_task_as_done(conn, task_id, source=source)
    elif cargo_state == "LOADED":
        execution.transition_to(orch_state.RobotTaskOrchestrationPhase.AWAITING_OPERATOR)
        execution.replace_recovery(
            {
                "reason": "movement_dispatch_failed_loaded_cargo",
                "robot_id": robot_id,
                "cargo_state": cargo_state,
                "failed_step_index": step_index,
                "detail": str(exc.detail),
            }
        )
        evidence.save_orchestration(conn, task_id, orch)
        result = _task(conn, task_id)
    else:
        execution.transition_to(orch_state.RobotTaskOrchestrationPhase.FAILED)
        evidence.save_orchestration(conn, task_id, orch)
        tasks.set_status(conn, task_id, "FAILED", clear_robot=True)
        if robot_id:
            robots.set_task(conn, str(robot_id), "IDLE", None)
            person_hazard.on_robot_task_terminal(str(robot_id))
        result = _task(conn, task_id)

    operational_events.append(
        conn,
        event_type=(
            orch_state.EVENT_AWAITING_OPERATOR
            if cargo_state == "LOADED" and not execution.business_completed
            else "TASK_STEP_DISPATCH_FAILED"
        ),
        task_id=task_id,
        robot_id=robot_id,
        message=f"task {task_id} step {step_index} dispatch failed ({cargo_state})",
        payload={"detail": str(exc.detail), "step_index": step_index, "cargo_state": cargo_state},
    )
    return result


def advance_on_command_event(
    conn, task_id: int, event: dict[str, Any], source: str = "callback"
) -> dict[str, Any] | None:
    """일치하는 callback만 반영하며 역순·중복 event가 업무를 중복 진행시키지 않는다."""
    advisory_xact_lock_for_key(conn, TASK_EVENT_LOCK_NAMESPACE, task_id)
    task = _task(conn, task_id)
    if not task or task["status"] not in {"RUNNING"}:
        return None

    orch = _orch(task)
    execution = orch_state.RobotTaskExecutionState.wrap(orch)
    if orch_state.is_hold_phase(execution.phase):
        return None
    steps = execution.steps
    step_index = execution.step_index
    if step_index >= len(steps):
        return None

    step = steps[step_index]
    event_name = transitions.normalize_movement_event(event)
    event_command_id = event.get("command_id")
    if not event_command_id or str(event_command_id) != str(step.get("command_id") or ""):
        return None
    if step.get("status") in TERMINAL_STEP_STATES:
        return None
    if str(step.get("kind")) == "inout_scenario":
        contract_errors = transitions.scenario_event_contract_errors(step, event)
        if contract_errors:
            operational_events.append(
                conn,
                event_type="MOVEMENT_SCENARIO_CONTRACT_REJECTED",
                task_id=task_id,
                robot_id=task.get("assigned_robot_id"),
                command_id=str(event_command_id),
                message=f"task {task_id} scenario callback rejected",
                payload={"fields": contract_errors, "event": event},
            )
            return None
    if source == "task_progress_poller":
        step.pop("callback_sequence_gap", None)
    if not _accept_event_sequence(step, event, source):
        return None

    scenario_progress: dict[str, Any] = {}
    if str(step.get("kind")) == "inout_scenario":
        scenario_progress = transitions.update_scenario_progress(orch, step, event)
        transitions.update_route_timeline(step, event, event_name)

    cancel_handled, cancel_result = _handle_cancel_requested(
        conn, task_id, task, execution, event, event_name, scenario_progress, source
    )
    if cancel_handled:
        return cancel_result

    task = _task(conn, task_id) or {}
    command_definition_id = evidence.resolve_command_definition_id(
        conn,
        task,
        _seed_step_index(steps, step_index),
        str(step.get("kind") or "move_to_point"),
    )
    evidence.record_movement_evidence(
        conn,
        task_id=task_id,
        command_definition_id=command_definition_id,
        event_type=event_name or "MOVEMENT_EVENT",
        data_json={"command_id": event_command_id, "event": event, "command_definition_id": command_definition_id},
    )

    _settle_scenario_unload(conn, task_id, task, execution, event, scenario_progress)

    if event_name in {"FAILED", "ABORTED", "REJECTED", "CANCELLED"}:
        return _handle_failed_event(conn, task_id, task, execution, event, event_name, scenario_progress, source)

    return _handle_successful_event(conn, task_id, task, execution, event, source, command_definition_id)


def _bind_missing_callback_command(conn, task_id: int, task: dict[str, Any], payload: dict[str, Any]) -> bool:
    """Repair a dispatch/result persistence race only from a fully matching Movement callback."""
    command_id = payload.get("command_id")
    if not command_id:
        return False
    orch = _orch(task)
    execution = orch_state.RobotTaskExecutionState.wrap(orch)
    if execution.phase != orch_state.RobotTaskOrchestrationPhase.RUNNING:
        return False
    steps = execution.steps
    step_index = execution.step_index
    if not 0 <= step_index < len(steps):
        return False
    step = steps[step_index]
    if step.get("command_id") or orch_state.normalize_robot_task_step_status(step.get("status")) != "PENDING":
        return False
    if str(step.get("kind")) != "inout_scenario":
        try:
            callback_step_index = int(payload.get("current_step_index"))
        except (TypeError, ValueError):
            return False
        callback_action = str(payload.get("current_step_action") or "")
        if callback_step_index != step_index or callback_action != str(step.get("kind") or ""):
            return False

    step["command_id"] = str(command_id)
    step["status"] = RobotTaskStepStatus.DISPATCHED
    execution.steps = steps
    evidence.save_orchestration(conn, task_id, orch)
    operational_events.append(
        conn,
        event_type="TASK_COMMAND_LINK_REPAIRED",
        task_id=task_id,
        robot_id=task.get("assigned_robot_id"),
        command_id=str(command_id),
        message=f"task {task_id} step {step_index} command link repaired from Movement callback",
        payload={"step_index": step_index, "kind": step.get("kind"), "command_id": command_id},
    )
    return True


def handle_command_event(conn, payload: dict[str, Any]) -> dict[str, Any] | None:
    """Movement event를 task lock 안에서 적용하며 terminal 전이는 안전 gate를 요구한다."""
    task_id = payload.get("task_id")
    if task_id is None:
        command_id = payload.get("command_id")
        if not command_id:
            return None
        task_id = runtime_records.find_task_id_by_robot_command(conn, str(command_id))
        if task_id is None:
            return None
    task = _task(conn, int(task_id))
    if not task:
        return None
    assigned_robot = str(task.get("assigned_robot_id") or "")
    event_robot = str(payload.get("robot_name") or payload.get("robot_id") or "")
    if event_robot and assigned_robot and event_robot not in {assigned_robot, movement_robot_key(assigned_robot)}:
        return None
    _bind_missing_callback_command(conn, int(task_id), task, payload)
    orch = _orch(task)
    recovery_state = orch.get("recovery") or {}
    if str(orch.get("phase") or "") == orch_state.RobotTaskOrchestrationPhase.RECOVERY_RUNNING and recovery_state.get(
        "active_command_id"
    ):
        result = recovery.handle_recovery_command_event(conn, int(task_id), payload)
        if result is not None:
            return result
    return advance_on_command_event(conn, int(task_id), payload)
