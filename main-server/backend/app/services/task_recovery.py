"""E-stop recovery plan and operator decision APIs (PHASE_78)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import HTTPException

from app.core.config import settings
from app.db.mvp.evidence import MvpEvidenceRepository
from app.db.repo_bridge import evidence_repo, location_repo, safety_stop_repo, task_repo
from app.models.schemas import RobotCommandRequest
from app.services import evidence_runtime, person_hazard
from app.services import orchestration_state as orch_state
from app.services import robot_commands as command_service
from app.services.movement import MovementClientError, movement_client
from app.services.movement_health import get_movement_health

CargoState = Literal["LOADED", "EMPTY", "UNKNOWN"]
RecoveryStrategy = Literal["safe_replan", "restart", "manual_abort"]
ACTIVE_RECOVERY_PHASES = {
    orch_state.PHASE_AWAITING_OPERATOR,
    orch_state._LEGACY_AWAITING,
    orch_state.PHASE_RECOVERY_RUNNING,
}
RECOVERY_TERMINAL_EVENTS = {"ARRIVED", "DONE", "FAILED", "ABORTED", "REJECTED"}


def _claim_recovery_terminal_transition(
    conn, task_id: int, command_id: str, event_name: str
) -> dict[str, Any] | None:
    """Claim one terminal recovery transition across callback and poller."""
    repo = evidence_repo(conn)
    if isinstance(repo, MvpEvidenceRepository) and getattr(conn, "is_postgres", False) is True:
        return repo.claim_recovery_terminal_transition(task_id, command_id, event_name)
    # Repository doubles retain the legacy in-memory path; production always
    # uses the PostgreSQL advisory-lock claim above.
    return None


def _orch_phase(task: dict[str, Any] | None) -> str:
    if not task:
        return ""
    orch = (task.get("preset_snapshot") or {}).get("_orchestration") or {}
    return orch_state.normalize_phase(str(orch.get("phase") or ""))


def _assert_needs_attention_phase(conn, task_id: int) -> None:
    task = evidence_runtime.attach_orchestration(task_repo(conn).get(task_id), conn)
    phase = _orch_phase(task)
    if phase != orch_state.PHASE_AWAITING_OPERATOR:
        raise HTTPException(status_code=409, detail="recovery_requires_needs_attention_phase")


def get_recovery_context(conn, task_id: int) -> dict[str, Any]:
    task = evidence_runtime.attach_orchestration(task_repo(conn).get(task_id), conn)
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
        "needs_attention": phase in {
            orch_state.PHASE_AWAITING_OPERATOR,
            orch_state.PHASE_RECOVERY_RUNNING,
        } or str(orch.get("phase") or "") in ACTIVE_RECOVERY_PHASES,
        "assigned_robot_id": task.get("assigned_robot_id"),
        "last_command_id": active_recovery_cmd or (current_step or {}).get("command_id"),
        "last_leg_kind": (current_step or {}).get("kind"),
        "last_step_kind": (current_step or {}).get("kind"),
        "recovery": recovery,
    }


def list_needs_attention_tasks(conn, limit: int = 20) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for task in evidence_runtime.list_orchestrated_running(conn, limit=limit):
        orch = (task.get("preset_snapshot") or {}).get("_orchestration") or {}
        phase = orch_state.normalize_phase(str(orch.get("phase") or ""))
        if phase in {orch_state.PHASE_AWAITING_OPERATOR, orch_state.PHASE_RECOVERY_RUNNING} or str(orch.get("phase") or "") in ACTIVE_RECOVERY_PHASES:
            out.append(get_recovery_context(conn, int(task["task_id"])))
    return out


def _safe_zone_location(conn) -> dict[str, Any]:
    for loc_type in ("home", "storage"):
        rows = location_repo(conn).list_by_type(loc_type)
        for row in rows:
            if row.get("x") is not None and row.get("y") is not None:
                return row
    raise HTTPException(status_code=409, detail="safe zone location not configured")


def preview_recovery_plan(
    conn,
    task_id: int,
    *,
    cargo_state: CargoState,
    strategy: RecoveryStrategy,
) -> dict[str, Any]:
    if cargo_state == "UNKNOWN":
        raise HTTPException(status_code=409, detail="cargo_state UNKNOWN blocks automated recovery")
    if strategy == "manual_abort":
        return {"task_id": task_id, "strategy": strategy, "steps": [], "executable": False}

    steps: list[dict[str, Any]] = []
    if strategy == "restart":
        steps.append({"kind": "operator", "action": "cancel_and_recreate", "label": "기존 task 취소 후 새 work order 생성"})
        return {"task_id": task_id, "strategy": strategy, "cargo_state": cargo_state, "steps": steps, "executable": False}

    if cargo_state == "EMPTY":
        steps.append({"kind": "operator", "action": "cancel_and_recreate", "label": "EMPTY — task 취소 후 처음부터 다시 시작"})
        return {"task_id": task_id, "strategy": strategy, "cargo_state": cargo_state, "steps": steps, "executable": False}

    safe = _safe_zone_location(conn)
    steps.append({
        "kind": "move_to_point",
        "label": f"safe:{safe.get('slot_id') or safe.get('location_id')}",
        "params": {
            "map_id": settings.movement_active_map_id,
            "x": float(safe["x"]),
            "y": float(safe["y"]),
            "yaw": float(safe.get("yaw") or 0.0),
        },
    })
    if settings.recovery_dock_transfer_enabled:
        steps.append({
            "kind": "dock_transfer",
            "label": "recovery_unload",
            "params": {"action": "unload"},
            "enabled": True,
        })
    return {
        "task_id": task_id,
        "strategy": strategy,
        "cargo_state": cargo_state,
        "steps": steps,
        "executable": True,
        "dock_transfer_available": settings.recovery_dock_transfer_enabled,
    }


def save_recovery_decision(
    conn,
    task_id: int,
    *,
    cargo_state: CargoState,
    strategy: RecoveryStrategy,
    checks: dict[str, bool],
    trusted_safety_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not all(checks.values()):
        raise HTTPException(status_code=409, detail="recovery safety checks incomplete")
    if cargo_state == "UNKNOWN":
        raise HTTPException(status_code=409, detail="cargo_state UNKNOWN blocks recovery execution")
    plan = preview_recovery_plan(conn, task_id, cargo_state=cargo_state, strategy=strategy)
    evidence_repo(conn).append(
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
            "trusted_safety_gate": trusted_safety_gate,
            "decided_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    orch = evidence_repo(conn).get_orchestration(task_id) or {}
    orch = dict(orch)
    recovery = dict(orch.get("recovery") or {})
    recovery.update({"cargo_state": cargo_state, "strategy": strategy, "checks": checks})
    if trusted_safety_gate is not None:
        recovery["trusted_safety_gate"] = trusted_safety_gate
    orch["recovery"] = recovery
    evidence_runtime.save_orchestration(conn, task_id, orch)
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
    _assert_needs_attention_phase(conn, task_id)
    if strategy == "manual_abort":
        save_recovery_decision(conn, task_id, cargo_state=cargo_state, strategy=strategy, checks=checks)
        return _abort_recovery_task(conn, task_id, cargo_state=cargo_state, checks=checks)
    if strategy == "restart":
        save_recovery_decision(conn, task_id, cargo_state=cargo_state, strategy=strategy, checks=checks)
        return _restart_recovery_task(conn, task_id, cargo_state=cargo_state, checks=checks)

    plan = preview_recovery_plan(conn, task_id, cargo_state=cargo_state, strategy=strategy)
    if not plan.get("executable"):
        if any(s.get("kind") == "dock_transfer" and not s.get("enabled") for s in plan.get("steps") or []):
            raise HTTPException(status_code=409, detail="recovery_unavailable_dock_transfer_missing")
        raise HTTPException(status_code=409, detail="recovery plan not executable")
    task = task_repo(conn).get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    robot_id = task.get("assigned_robot_id") or task.get("robot_id")
    if not robot_id:
        raise HTTPException(status_code=409, detail="task has no assigned robot")
    trusted_safety_gate = _verify_recovery_safety_gate(conn, task_id, str(robot_id))
    save_recovery_decision(
        conn,
        task_id,
        cargo_state=cargo_state,
        strategy=strategy,
        checks=checks,
        trusted_safety_gate=trusted_safety_gate,
    )
    first = next((s for s in plan["steps"] if s.get("kind") == "move_to_point"), None)
    if not first:
        raise HTTPException(status_code=409, detail="no move_to_point step in recovery plan")
    command_id = command_service.default_command_id(task_id, str(robot_id), "move_to_point")
    payload = RobotCommandRequest(
        robot_id=str(robot_id),
        kind="move_to_point",
        command_id=command_id,
        dry_run=False,
        params=first.get("params") or {},
        task_id=task_id,
    )
    result = command_service.dispatch_robot_command(conn, payload, request=None)
    evidence_repo(conn).append(
        task_id=task_id,
        event_type="RECOVERY_COMMAND_DISPATCHED",
        source="main_recovery",
        trusted=True,
        data_json={"command_id": result.command_id, "kind": "move_to_point", "strategy": strategy},
    )
    orch = evidence_repo(conn).get_orchestration(task_id) or {}
    orch = dict(orch)
    recovery = dict(orch.get("recovery") or {})
    recovery["active_command_id"] = result.command_id
    recovery["active_command_kind"] = "move_to_point"
    orch["recovery"] = recovery
    orch["phase"] = "RECOVERY_RUNNING"
    evidence_runtime.save_orchestration(conn, task_id, orch)
    return {"task_id": task_id, "command_id": result.command_id, "accepted": result.accepted, "plan": plan}


def _verify_recovery_safety_gate(conn, task_id: int, robot_id: str) -> dict[str, Any]:
    """Require DB stop closure and a fresh, unambiguous non-emergency health response.

    Operator-provided checkboxes are intentionally not safety authority.  The
    health probe is forced to bypass SWR cache so a prior clear acknowledgement
    cannot authorize recovery after a newer emergency state.
    """
    task_evidence_ids = {
        int(row["id"])
        for row in evidence_repo(conn).list_for_task(task_id)
        if row.get("id") is not None
    }
    active_stops = [
        row
        for row in safety_stop_repo(conn).list_active()
        if row.get("detected_evidence_id") in task_evidence_ids
        and str(row.get("status") or "").upper() in {"OPEN", "HOLDING"}
    ]
    if active_stops:
        raise HTTPException(status_code=409, detail="recovery_blocked_active_safety_stop")

    try:
        health_by_robot = get_movement_health([robot_id], force=True)
    except Exception as exc:
        raise HTTPException(status_code=409, detail="recovery_live_health_unavailable") from exc
    health = health_by_robot.get(robot_id) if isinstance(health_by_robot, dict) else None
    if not isinstance(health, dict) or health.get("ok") is not True or health.get("is_emergency") is not False:
        raise HTTPException(status_code=409, detail="recovery_live_health_unsafe")

    clear_acknowledgement = {
        "confirmed": True,
        "robot_id": robot_id,
        "checked_at": health.get("checked_at"),
        "mode": health.get("mode"),
        "health_ok": True,
        "is_emergency": False,
    }
    gate = {
        "active_safety_stop_ids": [],
        "live_health": dict(health),
        "clear_acknowledgement": clear_acknowledgement,
    }
    evidence_repo(conn).append(
        task_id=task_id,
        event_type="RECOVERY_SAFETY_GATE_PASSED",
        source="main_recovery",
        trusted=True,
        data_json=gate,
    )
    return gate


def _recovery_can_auto_resume(recovery: dict[str, Any]) -> bool:
    checks = recovery.get("checks")
    return (
        recovery.get("reason") == "person_hazard"
        and recovery.get("strategy") == "safe_replan"
        and isinstance(checks, dict)
        and bool(checks)
        and all(bool(value) for value in checks.values())
    )


def _reset_interrupted_step_for_resume(orch: dict[str, Any]) -> dict[str, Any] | None:
    steps = orch_state.get_steps(orch)
    step_index = orch_state.get_step_index(orch)
    if step_index >= len(steps):
        return None
    step = steps[step_index]
    step["status"] = "pending"
    step["command_id"] = None
    orch_state.set_steps(orch, steps)
    return step


def handle_recovery_command_event(
    conn,
    task_id: int,
    event: dict[str, Any],
    *,
    source: str = "callback",
) -> dict[str, Any] | None:
    """Handle recovery command terminal callback.

    DONE/ARRIVED after an operator-approved person-hazard recovery resumes the
    interrupted current step. Failed recovery movement stays held for another
    operator decision. Duplicate callbacks are idempotent because the active
    command is cleared before returning.
    """
    task = evidence_runtime.attach_orchestration(task_repo(conn).get(task_id), conn)
    if not task or task.get("status") != "RUNNING":
        return None
    orch = (task.get("preset_snapshot") or {}).get("_orchestration") or {}
    if str(orch.get("phase") or "") != "RECOVERY_RUNNING":
        return None
    recovery = dict(orch.get("recovery") or {})
    active_command_id = recovery.get("active_command_id")
    event_command_id = event.get("command_id")
    if not active_command_id or not event_command_id or str(event_command_id) != str(active_command_id):
        return None
    event_name = str(event.get("event") or event.get("state") or event.get("status") or "").upper()
    if event_name not in RECOVERY_TERMINAL_EVENTS:
        return None

    claimed_orch = _claim_recovery_terminal_transition(conn, task_id, str(event_command_id), event_name)
    if isinstance(evidence_repo(conn), MvpEvidenceRepository) and getattr(conn, "is_postgres", False) is True:
        if claimed_orch is None:
            return None
        orch = claimed_orch
        recovery = dict(orch.get("recovery") or {})

    now = datetime.now(timezone.utc).isoformat()
    recovery.pop("active_command_id", None)
    recovery.pop("active_command_kind", None)
    transition_id = recovery.get("terminal_transition_id") or f"{task_id}:recovery:{event_command_id}:{event_name}"
    recovery["last_recovery_result"] = event_name
    recovery["last_result"] = event_name
    recovery["last_recovery_at"] = now
    orch = dict(orch)

    evidence_repo(conn).append(
        task_id=task_id,
        event_type="RECOVERY_MOVE_TERMINAL",
        source=source,
        trusted=True,
        data_json={"event": event_name, "command_id": event_command_id, "transition_id": transition_id},
    )

    if event_name in {"DONE", "ARRIVED"} and _recovery_can_auto_resume(recovery):
        recovery["resumed_at"] = now
        _reset_interrupted_step_for_resume(orch)
        orch_state.set_phase(orch, orch_state.PHASE_RUNNING)
        orch["recovery"] = recovery
        evidence_runtime.save_orchestration(conn, task_id, orch)
        evidence_repo(conn).append(
            task_id=task_id,
            event_type="RECOVERY_RESUMED",
            source="main_recovery",
            trusted=True,
            data_json={
                "event": event_name,
                "command_id": event_command_id,
                "transition_id": transition_id,
                "resumed_at": now,
            },
        )
        from app.db.repo_bridge import event_repo
        event_repo(conn).append(
            event_type="RECOVERY_RESUMED",
            task_id=task_id,
            robot_id=task.get("assigned_robot_id"),
            message=f"task {task_id} recovery completed; resuming interrupted step",
            payload={
                "task_id": task_id,
                "event": event_name,
                "command_id": event_command_id,
                "transition_id": transition_id,
                "resumed_at": now,
            },
        )
        from app.services import orchestrator as orchestrator_service
        orchestrator_service.dispatch_current_step(conn, task_id)
        return evidence_runtime.attach_orchestration(task_repo(conn).get(task_id), conn)

    orch_state.set_phase(orch, orch_state.PHASE_AWAITING_OPERATOR)
    orch["recovery"] = recovery
    evidence_runtime.save_orchestration(conn, task_id, orch)
    return get_recovery_context(conn, task_id)


def poll_recovery_tasks(conn) -> int:
    """Poll recovery active commands when callbacks were missed (task progress poller)."""
    advanced = 0
    for task in evidence_runtime.list_orchestrated_running(conn):
        orch = (task.get("preset_snapshot") or {}).get("_orchestration") or {}
        if str(orch.get("phase") or "") != "RECOVERY_RUNNING":
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


def _stop_robot_movement(robot_id: str) -> None:
    try:
        movement_client.manual_stop(robot_id, {"robot_name": robot_id})
    except MovementClientError:
        pass


def _abort_recovery_task(
    conn,
    task_id: int,
    *,
    cargo_state: CargoState,
    checks: dict[str, bool],
) -> dict[str, Any]:
    _assert_recovery_checks(checks)
    task = task_repo(conn).get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task.get("status") != "RUNNING":
        raise HTTPException(status_code=409, detail="task is not running")
    robot_id = task.get("assigned_robot_id")
    if robot_id:
        _stop_robot_movement(str(robot_id))
    task_repo(conn).set_status(task_id, "CANCELLED", clear_robot=True)
    if robot_id:
        from app.db.repo_bridge import robot_repo
        robot_repo(conn).set_task(str(robot_id), "IDLE", None)
        person_hazard.on_robot_task_terminal(str(robot_id))
    orch = evidence_repo(conn).get_orchestration(task_id) or {}
    orch = dict(orch)
    orch["phase"] = "ABORTED"
    evidence_runtime.save_orchestration(conn, task_id, orch)
    evidence_repo(conn).append(
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


def _restart_recovery_task(
    conn,
    task_id: int,
    *,
    cargo_state: CargoState,
    checks: dict[str, bool],
) -> dict[str, Any]:
    _assert_recovery_checks(checks)
    if cargo_state == "UNKNOWN":
        raise HTTPException(status_code=409, detail="cargo_state UNKNOWN blocks restart")
    task = task_repo(conn).get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    if task.get("status") != "RUNNING":
        raise HTTPException(status_code=409, detail="task is not running")
    robot_id = task.get("assigned_robot_id")
    if robot_id:
        _stop_robot_movement(str(robot_id))
    task_repo(conn).set_status(task_id, "CANCELLED", clear_robot=True)
    if robot_id:
        from app.db.repo_bridge import robot_repo
        robot_repo(conn).set_task(str(robot_id), "IDLE", None)
        person_hazard.on_robot_task_terminal(str(robot_id))
    orch = evidence_repo(conn).get_orchestration(task_id) or {}
    orch = dict(orch)
    orch["phase"] = "RESTART_PENDING"
    evidence_runtime.save_orchestration(conn, task_id, orch)
    evidence_repo(conn).append(
        task_id=task_id,
        event_type="RECOVERY_RESTART",
        source="operator",
        trusted=True,
        data_json={"cargo_state": cargo_state, "checks": checks},
    )
    return {
        "task_id": task_id,
        "strategy": "restart",
        "status": "CANCELLED",
        "message": "기존 작업을 종료했습니다. 동일 품목·수량으로 새 입출고 요청을 생성하세요.",
    }
