"""E-stop recovery plan and operator decision APIs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import HTTPException

from app.core.config import settings
from app.db.postgres import locations, runtime_records, tasks
from app.domains.execution import evidence
from app.domains.execution import state as orch_state
from app.domains.movement import commands
from app.domains.movement import navigation as movement_navigation
from app.domains.movement.client import MovementClientError, movement_client
from app.domains.movement.health import get_movement_health
from app.domains.safety import hazard as person_hazard
from app.models.robot_commands import RobotCommandRequest

CargoState = Literal["LOADED", "EMPTY", "UNKNOWN"]
RecoveryStrategy = Literal["safe_move", "manual_abort"]
ACTIVE_RECOVERY_PHASES = {
    orch_state.PHASE_AWAITING_OPERATOR,
    orch_state.PHASE_RECOVERY_RUNNING,
}
RECOVERY_TERMINAL_EVENTS = {"ARRIVED", "DONE", "FAILED", "ABORTED", "REJECTED"}


def _orch_phase(task: dict[str, Any] | None) -> str:
    if not task:
        return ""
    orch = (task.get("preset_snapshot") or {}).get("_orchestration") or {}
    return orch_state.normalize_phase(str(orch.get("phase") or ""))


def _assert_awaiting_operator_phase(conn, task_id: int) -> None:
    task = evidence.attach_orchestration(tasks.get_task(conn, task_id), conn)
    phase = _orch_phase(task)
    if phase != orch_state.PHASE_AWAITING_OPERATOR:
        raise HTTPException(status_code=409, detail="recovery_requires_awaiting_operator_phase")


def get_recovery_context(conn, task_id: int) -> dict[str, Any]:
    task = evidence.attach_orchestration(tasks.get_task(conn, task_id), conn)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    orch = (task.get("preset_snapshot") or {}).get("_orchestration") or {}
    phase = orch_state.normalize_phase(str(orch.get("phase") or ""))
    steps = orch_state.get_steps(orch)
    step_index = orch_state.get_step_index(orch)
    current_step = steps[step_index] if step_index < len(steps) else None
    recovery = orch.get("recovery") or {}
    active_recovery_cmd = recovery.get("active_command_id")
    return {
        "task_id": task_id,
        "status": task.get("status"),
        "orchestration_phase": phase,
        "awaiting_operator": phase
        in {
            orch_state.PHASE_AWAITING_OPERATOR,
            orch_state.PHASE_RECOVERY_RUNNING,
        }
        or str(orch.get("phase") or "") in ACTIVE_RECOVERY_PHASES,
        "assigned_robot_id": task.get("assigned_robot_id"),
        "last_command_id": active_recovery_cmd or (current_step or {}).get("command_id"),
        "last_step_kind": (current_step or {}).get("kind"),
        "recovery": recovery,
    }


def list_awaiting_operator_tasks(conn, limit: int = 20) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for task in evidence.list_orchestrated_running(conn, limit=limit):
        orch = (task.get("preset_snapshot") or {}).get("_orchestration") or {}
        phase = orch_state.normalize_phase(str(orch.get("phase") or ""))
        if (
            phase in {orch_state.PHASE_AWAITING_OPERATOR, orch_state.PHASE_RECOVERY_RUNNING}
            or str(orch.get("phase") or "") in ACTIVE_RECOVERY_PHASES
        ):
            out.append(get_recovery_context(conn, int(task["task_id"])))
    return out


def _safe_zone_location(conn) -> dict[str, Any]:
    configured_id = settings.recovery_safe_location_id
    location = locations.get_location(conn, configured_id) if configured_id else None
    if not location or not location.get("enabled", True):
        raise HTTPException(status_code=409, detail="recovery safe location not configured")
    if location.get("type") != "home" or location.get("x") is None or location.get("y") is None:
        raise HTTPException(status_code=409, detail="recovery safe location must be an active home")
    return location


def preview_recovery_plan(
    conn,
    task_id: int,
    *,
    cargo_state: CargoState,
    strategy: RecoveryStrategy,
) -> dict[str, Any]:
    if strategy not in {"safe_move", "manual_abort"}:
        raise HTTPException(status_code=422, detail="unsupported recovery strategy")
    if cargo_state == "UNKNOWN":
        raise HTTPException(status_code=409, detail="cargo_state UNKNOWN blocks automated recovery")
    if strategy == "manual_abort":
        return {
            "task_id": task_id,
            "strategy": strategy,
            "cargo_state": cargo_state,
            "steps": [{"kind": "operator", "action": "manual_recovery", "label": "현장 회수 후 작업 종료"}],
            "executable": True,
        }

    steps: list[dict[str, Any]] = []
    safe = _safe_zone_location(conn)
    steps.append(
        {
            "kind": "move_to_point",
            "label": f"safe:{safe.get('slot_id') or safe.get('location_id')}",
            "params": {
                "map_id": settings.movement_active_map_id,
                "x": float(safe["x"]),
                "y": float(safe["y"]),
                "yaw": float(safe.get("yaw") or 0.0),
            },
        }
    )
    return {
        "task_id": task_id,
        "strategy": strategy,
        "cargo_state": cargo_state,
        "steps": steps,
        "executable": True,
        "dock_transfer_available": False,
        "limitations": ["자동 하역 및 기존 작업 재개는 수행하지 않습니다."],
    }


def reconcile_undispatched_task(conn, task_id: int) -> dict[str, Any]:
    """Fail a RUNNING task that never obtained a Movement command."""
    task = evidence.attach_orchestration(tasks.get_task(conn, task_id), conn)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    orch = (task.get("preset_snapshot") or {}).get("_orchestration") or {}
    execution = orch_state.RobotTaskExecutionState.wrap(orch)
    if task.get("status") != "RUNNING" or execution.phase != orch_state.PHASE_RUNNING:
        raise HTTPException(status_code=409, detail="reconcile_requires_running_undispatched_task")
    steps = execution.steps
    if execution.step_index >= len(steps):
        raise HTTPException(status_code=409, detail="reconcile_task_has_no_current_step")
    step = steps[execution.step_index]
    if step.get("command_id") or orch_state.is_dispatched_robot_task_step(step):
        raise HTTPException(status_code=409, detail="reconcile_task_has_active_command")
    if orch_state.cargo_state_after_steps(steps) != "EMPTY":
        raise HTTPException(status_code=409, detail="reconcile_requires_empty_cargo")
    robot_id = task.get("assigned_robot_id")
    if not robot_id:
        raise HTTPException(status_code=409, detail="task has no assigned robot")
    try:
        nav_state = movement_client.nav_state(str(robot_id))
    except MovementClientError as exc:
        raise HTTPException(status_code=409, detail="reconcile_movement_state_unavailable") from exc
    if nav_state.get("active_commands") or nav_state.get("current_command_id"):
        raise HTTPException(status_code=409, detail="reconcile_movement_command_active")
    from app.domains.execution import orchestrator

    failure = HTTPException(
        status_code=502,
        detail={
            "code": "movement_command_not_dispatched",
            "message": "Movement command was not accepted; stale RUNNING state reconciled.",
            "retryable": False,
        },
    )
    result = orchestrator._handle_step_dispatch_exception(
        conn, task_id, failure, source="operator_reconcile"
    )
    return {"ok": True, "task_id": task_id, "status": (result or {}).get("status", "FAILED")}


def save_recovery_decision(
    conn,
    task_id: int,
    *,
    cargo_state: CargoState,
    strategy: RecoveryStrategy,
    checks: dict[str, bool],
) -> dict[str, Any]:
    if not all(checks.values()):
        raise HTTPException(status_code=409, detail="recovery safety checks incomplete")
    if cargo_state == "UNKNOWN":
        raise HTTPException(status_code=409, detail="cargo_state UNKNOWN blocks recovery execution")
    plan = preview_recovery_plan(conn, task_id, cargo_state=cargo_state, strategy=strategy)
    runtime_records.append(
        conn,
        task_id=task_id,
        event_type="RECOVERY_DECISION",
        source="operator",
        severity="INFO",
        trusted=True,
        data_json={
            "cargo_state": cargo_state,
            "strategy": strategy,
            "checks": checks,
            "plan": plan,
            "decided_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    orch = runtime_records.get_orchestration(conn, task_id) or {}
    orch = dict(orch)
    execution = orch_state.RobotTaskExecutionState.wrap(orch)
    execution.update_recovery(cargo_state=cargo_state, strategy=strategy, checks=checks)
    evidence.save_orchestration(conn, task_id, orch)
    return {"task_id": task_id, "saved": True, "plan": plan}


def execute_recovery(
    conn,
    task_id: int,
    *,
    cargo_state: CargoState,
    strategy: RecoveryStrategy,
    checks: dict[str, bool],
    callback_base_url: str | None = None,
) -> dict[str, Any]:
    _assert_awaiting_operator_phase(conn, task_id)
    save_recovery_decision(conn, task_id, cargo_state=cargo_state, strategy=strategy, checks=checks)
    if strategy == "manual_abort":
        return _abort_recovery_task(conn, task_id, cargo_state=cargo_state, checks=checks)
    plan = preview_recovery_plan(conn, task_id, cargo_state=cargo_state, strategy=strategy)
    if not plan.get("executable"):
        if any(s.get("kind") == "dock_transfer" and not s.get("enabled") for s in plan.get("steps") or []):
            raise HTTPException(status_code=409, detail="recovery_unavailable_dock_transfer_missing")
        raise HTTPException(status_code=409, detail="recovery plan not executable")
    task = tasks.get_task(conn, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    robot_id = task.get("assigned_robot_id") or task.get("robot_id")
    if not robot_id:
        raise HTTPException(status_code=409, detail="task has no assigned robot")
    first = next((s for s in plan["steps"] if s.get("kind") == "move_to_point"), None)
    if not first:
        raise HTTPException(status_code=409, detail="no move_to_point step in recovery plan")
    _assert_recovery_robot_ready(str(robot_id), str(first.get("params", {}).get("map_id") or ""))
    command_id = commands.default_command_id(task_id, str(robot_id), "move_to_point")
    payload = RobotCommandRequest(
        robot_id=str(robot_id),
        kind="move_to_point",
        command_id=command_id,
        dry_run=False,
        params=first.get("params") or {},
        task_id=task_id,
        callback_url=commands.resolve_callback_url(None, callback_base_url) if callback_base_url else None,
    )
    result = commands.dispatch_robot_command(conn, payload, request=None)
    if not result.accepted:
        raise HTTPException(status_code=502, detail="recovery command rejected")
    runtime_records.append(
        conn,
        task_id=task_id,
        event_type="RECOVERY_COMMAND_DISPATCHED",
        source="main_recovery",
        trusted=True,
        data_json={"command_id": result.command_id, "kind": "move_to_point", "strategy": strategy},
    )
    orch = runtime_records.get_orchestration(conn, task_id) or {}
    orch = dict(orch)
    execution = orch_state.RobotTaskExecutionState.wrap(orch)
    execution.update_recovery(
        active_command_id=result.command_id,
        active_command_kind="move_to_point",
    )
    execution.transition_to(orch_state.PHASE_RECOVERY_RUNNING)
    evidence.save_orchestration(conn, task_id, orch)
    return {"task_id": task_id, "command_id": result.command_id, "accepted": result.accepted, "plan": plan}


def handle_recovery_command_event(
    conn,
    task_id: int,
    event: dict[str, Any],
    *,
    source: str = "callback",
) -> dict[str, Any] | None:
    """Recovery move_to_point terminal callback — return task to AWAITING_OPERATOR for next operator decision."""
    task = evidence.attach_orchestration(tasks.get_task(conn, task_id), conn)
    if not task or task.get("status") != "RUNNING":
        return None
    orch = (task.get("preset_snapshot") or {}).get("_orchestration") or {}
    if orch_state.normalize_phase(orch.get("phase")) != orch_state.PHASE_RECOVERY_RUNNING:
        return None
    recovery = dict(orch.get("recovery") or {})
    active_command_id = recovery.get("active_command_id")
    event_command_id = event.get("command_id")
    if not active_command_id or not event_command_id or str(event_command_id) != str(active_command_id):
        return None
    event_name = str(event.get("event") or event.get("state") or event.get("status") or "").upper()
    if event_name not in RECOVERY_TERMINAL_EVENTS:
        return None
    recovery.pop("active_command_id", None)
    recovery.pop("active_command_kind", None)
    recovery["last_recovery_result"] = event_name
    recovery["last_recovery_at"] = datetime.now(timezone.utc).isoformat()
    orch = dict(orch)
    execution = orch_state.RobotTaskExecutionState.wrap(orch)
    execution.transition_to(orch_state.PHASE_AWAITING_OPERATOR)
    execution.replace_recovery(recovery)
    evidence.save_orchestration(conn, task_id, orch)
    runtime_records.append(
        conn,
        task_id=task_id,
        event_type="RECOVERY_MOVE_TERMINAL",
        source=source,
        trusted=True,
        data_json={"event": event_name, "command_id": event_command_id or active_command_id},
    )
    return get_recovery_context(conn, task_id)


def poll_recovery_tasks(conn) -> int:
    """Poll recovery active commands when callbacks were missed (task progress poller)."""
    advanced = 0
    for task in evidence.list_orchestrated_running(conn):
        orch = (task.get("preset_snapshot") or {}).get("_orchestration") or {}
        if orch_state.normalize_phase(orch.get("phase")) != orch_state.PHASE_RECOVERY_RUNNING:
            continue
        recovery = orch.get("recovery") or {}
        command_id = recovery.get("active_command_id")
        robot_id = task.get("assigned_robot_id")
        if not command_id or not robot_id:
            continue
        try:
            status = movement_client.command_status(str(robot_id), str(command_id))
        except MovementClientError:
            continue
        state = str(status.get("state") or status.get("status") or "").upper()
        if state in RECOVERY_TERMINAL_EVENTS:
            if handle_recovery_command_event(
                conn,
                int(task["task_id"]),
                {"command_id": command_id, "state": state},
                source="task_progress_poller",
            ):
                advanced += 1
    return advanced


def _assert_recovery_checks(checks: dict[str, bool]) -> None:
    if not all(checks.values()):
        raise HTTPException(status_code=409, detail="recovery safety checks incomplete")


def _assert_recovery_robot_ready(robot_id: str, map_id: str) -> None:
    get_movement_health([robot_id], force=True)
    snapshot = movement_navigation.localization_snapshot(robot_id)
    if not snapshot.get("ok"):
        raise HTTPException(status_code=409, detail="recovery_movement_unreachable")
    if snapshot.get("health", {}).get("is_emergency"):
        raise HTTPException(status_code=409, detail="recovery_estop_active")
    if snapshot.get("robot_online") is False:
        raise HTTPException(status_code=409, detail="recovery_robot_offline")
    if not snapshot.get("localized") or not snapshot.get("pose"):
        raise HTTPException(status_code=409, detail="recovery_localization_required")
    if snapshot.get("command_accepting") is False:
        raise HTTPException(status_code=409, detail="recovery_command_not_accepting")
    movement_navigation.assert_movement_active_map(map_id)


def _stop_robot_movement(robot_id: str) -> None:
    try:
        movement_client.manual_stop(robot_id, {"robot_name": robot_id})
    except MovementClientError as exc:
        raise HTTPException(status_code=409, detail="recovery_stop_unconfirmed") from exc


def _abort_recovery_task(
    conn,
    task_id: int,
    *,
    cargo_state: CargoState,
    checks: dict[str, bool],
) -> dict[str, Any]:
    _assert_recovery_checks(checks)
    task = tasks.get_task(conn, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task.get("status") != "RUNNING":
        raise HTTPException(status_code=409, detail="task is not running")
    robot_id = task.get("assigned_robot_id")
    if robot_id:
        _stop_robot_movement(str(robot_id))
    tasks.set_status(conn, task_id, "CANCELLED", clear_robot=True)
    if robot_id:
        from app.db.postgres import robots

        robots.set_task(conn, str(robot_id), "IDLE", None)
        person_hazard.on_robot_task_terminal(str(robot_id))
    orch = runtime_records.get_orchestration(conn, task_id) or {}
    orch = dict(orch)
    orch_state.RobotTaskExecutionState.wrap(orch).transition_to(
        orch_state.RobotTaskOrchestrationPhase.ABORTED
    )
    evidence.save_orchestration(conn, task_id, orch)
    runtime_records.append(
        conn,
        task_id=task_id,
        event_type="RECOVERY_MANUAL_ABORT",
        source="operator",
        trusted=True,
        data_json={"cargo_state": cargo_state, "checks": checks},
    )
    return {
        "task_id": task_id,
        "strategy": "manual_abort",
        "status": "CANCELLED",
        "message": "작업이 중단되었습니다. 필요 시 새 입출고 요청을 생성하세요.",
    }
