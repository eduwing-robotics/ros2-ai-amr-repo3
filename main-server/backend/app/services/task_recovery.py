"""E-stop recovery plan and operator decision APIs (PHASE_78)."""

from __future__ import annotations

import threading
from collections import defaultdict
from contextlib import contextmanager
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
RecoveryStrategy = Literal["safe_move", "manual_abort"]
ACTIVE_RECOVERY_PHASES = {
    orch_state.PHASE_AWAITING_OPERATOR,
    orch_state._LEGACY_AWAITING,
    orch_state.PHASE_RECOVERY_RUNNING,
}
RECOVERY_TERMINAL_EVENTS = {
    "ARRIVED",
    "DONE",
    "FAILED",
    "ABORTED",
    "REJECTED",
    "CANCELLED",
    "STOP_UNCONFIRMED",
}
RECOVERY_DISPATCH_PENDING = "PENDING"
RECOVERY_DISPATCH_SENT = "SENT"
_recovery_command_locks: defaultdict[int, threading.RLock] = defaultdict(threading.RLock)


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


@contextmanager
def recovery_command_guard(
    conn,
    task_id: int,
    command_id: str,
    *,
    fallback: dict[str, Any] | None = None,
):
    """Serialize recovery dispatch, operator stop, callback, and retry ordering."""
    repo = evidence_repo(conn)
    if isinstance(repo, MvpEvidenceRepository) and getattr(conn, "is_postgres", False) is True:
        yield repo.lock_recovery_command(task_id, command_id)
        return
    with _recovery_command_locks[task_id]:
        current = repo.get_orchestration(task_id)
        orch = dict(current) if isinstance(current, dict) else dict(fallback or {})
        recovery = orch.get("recovery") or {}
        if (
            orch_state.normalize_phase(orch.get("phase")) != orch_state.PHASE_RECOVERY_RUNNING
            or str(recovery.get("active_command_id") or "") != str(command_id)
        ):
            yield None
        else:
            yield orch


@contextmanager
def recovery_start_guard(
    conn,
    task_id: int,
    *,
    fallback: dict[str, Any] | None = None,
):
    """Serialize the operator transition from held state into recovery."""
    repo = evidence_repo(conn)
    if isinstance(repo, MvpEvidenceRepository) and getattr(conn, "is_postgres", False) is True:
        yield repo.lock_orchestration(task_id)
        return
    with _recovery_command_locks[task_id]:
        current = repo.get_orchestration(task_id)
        orch = dict(fallback or {})
        if isinstance(current, dict):
            orch.update(current)
        yield orch


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
    configured_id = settings.recovery_safe_location_id
    rows = location_repo(conn).list_by_type("home")
    location = next(
        (
            row
            for row in rows
            if (row.get("slot_id") or row.get("location_id")) == configured_id
        ),
        None,
    )
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
    return {
        "task_id": task_id,
        "strategy": strategy,
        "cargo_state": cargo_state,
        "steps": steps,
        "executable": True,
        "dock_transfer_available": False,
        "limitations": ["자동 하역 및 기존 작업 재개는 수행하지 않습니다."],
    }


def _record_recovery_decision(
    conn,
    task_id: int,
    orch: dict[str, Any],
    *,
    cargo_state: CargoState,
    strategy: RecoveryStrategy,
    checks: dict[str, bool],
    plan: dict[str, Any],
    trusted_safety_gate: dict[str, Any] | None = None,
) -> dict[str, Any]:
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
    orch = dict(orch)
    recovery = dict(orch.get("recovery") or {})
    recovery.update({"cargo_state": cargo_state, "strategy": strategy, "checks": checks})
    if trusted_safety_gate is not None:
        recovery["trusted_safety_gate"] = trusted_safety_gate
    orch["recovery"] = recovery
    return orch


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
    orch = evidence_repo(conn).get_orchestration(task_id) or {}
    orch = _record_recovery_decision(
        conn,
        task_id,
        orch,
        cargo_state=cargo_state,
        strategy=strategy,
        checks=checks,
        plan=plan,
        trusted_safety_gate=trusted_safety_gate,
    )
    evidence_runtime.save_orchestration(conn, task_id, orch)
    return {"task_id": task_id, "saved": True, "plan": plan}


def execute_recovery(
    conn,
    task_id: int,
    *,
    cargo_state: CargoState,
    strategy: RecoveryStrategy,
    checks: dict[str, bool],
) -> dict[str, Any]:
    _assert_needs_attention_phase(conn, task_id)
    _assert_recovery_checks(checks)
    if strategy == "manual_abort":
        with recovery_start_guard(
            conn,
            task_id,
            fallback={"phase": orch_state.PHASE_AWAITING_OPERATOR},
        ) as orch:
            if (
                orch is None
                or orch_state.normalize_phase(orch.get("phase"))
                != orch_state.PHASE_AWAITING_OPERATOR
            ):
                raise HTTPException(status_code=409, detail="recovery_requires_needs_attention_phase")
            save_recovery_decision(
                conn,
                task_id,
                cargo_state=cargo_state,
                strategy=strategy,
                checks=checks,
            )
            result = _abort_recovery_task(conn, task_id, cargo_state=cargo_state, checks=checks)
            conn.commit()
            return result

    plan = preview_recovery_plan(conn, task_id, cargo_state=cargo_state, strategy=strategy)
    if not plan.get("executable"):
        raise HTTPException(status_code=409, detail="recovery plan not executable")
    task = task_repo(conn).get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="task not found")
    robot_id = task.get("assigned_robot_id") or task.get("robot_id")
    if not robot_id:
        raise HTTPException(status_code=409, detail="task has no assigned robot")
    trusted_safety_gate = _verify_recovery_safety_gate(conn, task_id, str(robot_id))
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
    with recovery_start_guard(
        conn,
        task_id,
        fallback={"phase": orch_state.PHASE_AWAITING_OPERATOR},
    ) as orch:
        if (
            orch is None
            or orch_state.normalize_phase(orch.get("phase"))
            != orch_state.PHASE_AWAITING_OPERATOR
        ):
            raise HTTPException(status_code=409, detail="recovery_requires_needs_attention_phase")
        orch = _record_recovery_decision(
            conn,
            task_id,
            orch,
            cargo_state=cargo_state,
            strategy=strategy,
            checks=checks,
            plan=plan,
            trusted_safety_gate=trusted_safety_gate,
        )
        recovery = dict(orch.get("recovery") or {})
        recovery.update(
            {
                "active_command_id": command_id,
                "active_command_kind": "move_to_point",
                "active_robot_id": str(robot_id),
                "active_command_params": dict(first.get("params") or {}),
                "dispatch_state": RECOVERY_DISPATCH_PENDING,
                "strategy": strategy,
                "cargo_state": cargo_state,
            }
        )
        orch["recovery"] = recovery
        orch_state.set_phase(orch, orch_state.PHASE_RECOVERY_RUNNING)
        evidence_runtime.save_orchestration(conn, task_id, orch)
        evidence_repo(conn).append(
            task_id=task_id,
            event_type="RECOVERY_COMMAND_PENDING",
            source="main_recovery",
            trusted=True,
            data_json={"command_id": command_id, "kind": "move_to_point", "strategy": strategy},
        )
        conn.commit()

    result = _dispatch_persisted_recovery_command(conn, task_id, orch, payload=payload)
    if not result.accepted:
        raise HTTPException(status_code=502, detail="recovery command rejected")
    return {"task_id": task_id, "command_id": result.command_id, "accepted": result.accepted, "plan": plan}


def _dispatch_persisted_recovery_command(
    conn,
    task_id: int,
    orch: dict[str, Any],
    *,
    payload: RobotCommandRequest | None = None,
):
    """Deliver one durable recovery command identity; retries reuse that id."""
    recovery = dict(orch.get("recovery") or {})
    command_id = str(recovery.get("active_command_id") or "")
    robot_id = str(recovery.get("active_robot_id") or "")
    command_kind = str(recovery.get("active_command_kind") or "move_to_point")
    if not command_id or not robot_id:
        raise HTTPException(status_code=409, detail="recovery command identity missing")
    if payload is None:
        payload = RobotCommandRequest(
            robot_id=robot_id,
            kind=command_kind,
            command_id=command_id,
            dry_run=False,
            params=dict(recovery.get("active_command_params") or {}),
            task_id=task_id,
        )

    with recovery_command_guard(
        conn,
        task_id,
        command_id,
        fallback=orch,
    ) as latest:
        if latest is None:
            raise HTTPException(status_code=409, detail="recovery command superseded")
        latest_recovery = dict(latest.get("recovery") or {})
        if latest_recovery.get("stop_requested") is True:
            if latest_recovery.get("dispatch_state") == RECOVERY_DISPATCH_PENDING:
                latest_recovery.pop("active_command_id", None)
                latest_recovery.pop("active_command_kind", None)
                latest_recovery.pop("active_robot_id", None)
                latest_recovery.pop("active_command_params", None)
                latest_recovery.pop("dispatch_state", None)
                latest_recovery["cargo_state"] = "UNKNOWN"
                latest_recovery["reason"] = "operator_safe_stop_before_dispatch"
                latest["recovery"] = latest_recovery
                orch_state.set_phase(latest, orch_state.PHASE_AWAITING_OPERATOR)
                evidence_runtime.save_orchestration(conn, task_id, latest)
                conn.commit()
            raise HTTPException(status_code=409, detail="recovery stop already requested")

        if not person_hazard.arm_physical_motion_monitor(
            conn,
            robot_id,
            task_id,
            command_id,
            command_kind,
        ):
            # The command was never dispatched. Restore a durable operator hold
            # without discarding the operator's cargo/strategy decision.
            latest_recovery.pop("active_command_id", None)
            latest_recovery.pop("active_command_kind", None)
            latest_recovery.pop("active_robot_id", None)
            latest_recovery.pop("active_command_params", None)
            latest_recovery["dispatch_state"] = "REJECTED"
            latest_recovery["last_recovery_result"] = "PERSON_MONITOR_UNAVAILABLE"
            latest_recovery["reason"] = "person_monitor_outage"
            latest["recovery"] = latest_recovery
            orch_state.set_phase(latest, orch_state.PHASE_AWAITING_OPERATOR)
            evidence_runtime.save_orchestration(conn, task_id, latest)
            conn.commit()
            raise HTTPException(status_code=503, detail="person_monitor_unavailable")

        try:
            result = command_service.dispatch_robot_command(conn, payload, request=None)
        except Exception:
            conn.rollback()
            raise

        command_id_mismatch = str(result.command_id) != command_id
        if not result.accepted or command_id_mismatch:
            latest_recovery.pop("active_command_id", None)
            latest_recovery.pop("active_command_kind", None)
            latest_recovery.pop("active_robot_id", None)
            latest_recovery.pop("active_command_params", None)
            latest_recovery["dispatch_state"] = "REJECTED"
            latest_recovery["last_recovery_result"] = "REJECTED"
            latest["recovery"] = latest_recovery
            orch_state.set_phase(latest, orch_state.PHASE_AWAITING_OPERATOR)
            evidence_runtime.save_orchestration(conn, task_id, latest)
            person_hazard.disable_monitor(robot_id, conn=conn)
            conn.commit()
            if command_id_mismatch:
                raise HTTPException(status_code=502, detail="recovery command id mismatch")
            return result

        latest_recovery["dispatch_state"] = RECOVERY_DISPATCH_SENT
        latest["recovery"] = latest_recovery
        evidence_runtime.save_orchestration(conn, task_id, latest)
        evidence_repo(conn).append(
            task_id=task_id,
            event_type="RECOVERY_COMMAND_DISPATCHED",
            source="main_recovery",
            trusted=True,
            data_json={
                "command_id": command_id,
                "kind": command_kind,
                "strategy": latest_recovery.get("strategy"),
            },
        )
        conn.commit()
        return result


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
    authoritative_health = isinstance(health, dict) and (
        health.get("health_endpoint_reached") is True
        or health.get("mode") in {"fake", "offline"}
    )
    if (
        not authoritative_health
        or health.get("source") == "pose_fallback"
        or health.get("ok") is not True
        or health.get("is_emergency") is not False
        or health.get("estop_state") != "clear"
    ):
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


def handle_recovery_command_event(
    conn,
    task_id: int,
    event: dict[str, Any],
    *,
    source: str = "callback",
) -> dict[str, Any] | None:
    """Handle recovery command terminal callback.

    Every terminal recovery result returns the task to operator hold; recovery
    never auto-resumes the interrupted business step. PostgreSQL callers keep
    the task lock from claim through this final state write, so duplicate
    callback/poller observations are idempotent without an intermediate phase.
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
    if event_name == "CANCELED":
        event_name = "CANCELLED"
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
    recovery.pop("active_robot_id", None)
    recovery.pop("active_command_params", None)
    recovery.pop("dispatch_state", None)
    stop_requested = recovery.pop("stop_requested", False)
    transition_id = recovery.get("terminal_transition_id") or f"{task_id}:recovery:{event_command_id}:{event_name}"
    recovery["last_recovery_result"] = event_name
    recovery["last_result"] = event_name
    recovery["last_recovery_at"] = now
    if stop_requested or event_name == "STOP_UNCONFIRMED":
        recovery["cargo_state"] = "UNKNOWN"
        recovery["reason"] = (
            "physical_stop_unconfirmed"
            if event_name == "STOP_UNCONFIRMED"
            else "operator_safe_stop"
        )
    orch = dict(orch)

    evidence_repo(conn).append(
        task_id=task_id,
        event_type="RECOVERY_MOVE_TERMINAL",
        source=source,
        trusted=True,
        data_json={"event": event_name, "command_id": event_command_id, "transition_id": transition_id},
    )

    orch_state.set_phase(orch, orch_state.PHASE_AWAITING_OPERATOR)
    orch["recovery"] = recovery
    evidence_runtime.save_orchestration(conn, task_id, orch)
    if isinstance(evidence_repo(conn), MvpEvidenceRepository) and getattr(conn, "is_postgres", False) is True:
        conn.commit()
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
        robot_id = recovery.get("active_robot_id") or task.get("assigned_robot_id")
        if not command_id or not robot_id:
            continue
        if recovery.get("stop_requested") is True:
            try:
                stopped = movement_client.cancel_command(str(robot_id), str(command_id))
            except MovementClientError:
                continue
            stop_state = str(stopped.get("state") or "").upper()
            if stop_state == "CANCELED":
                stop_state = "CANCELLED"
            if not stopped.get("accepted", True) and not stop_state:
                stop_state = "STOP_UNCONFIRMED"
            if stop_state in RECOVERY_TERMINAL_EVENTS and handle_recovery_command_event(
                conn,
                int(task["task_id"]),
                {"command_id": command_id, "state": stop_state},
                source="task_progress_poller",
            ):
                advanced += 1
            continue
        if recovery.get("dispatch_state") == RECOVERY_DISPATCH_PENDING:
            try:
                _dispatch_persisted_recovery_command(
                    conn,
                    int(task["task_id"]),
                    orch,
                )
            except (HTTPException, MovementClientError):
                continue
            refreshed = evidence_runtime.attach_orchestration(
                task_repo(conn).get(int(task["task_id"])),
                conn,
            )
            refreshed_orch = (
                (refreshed.get("preset_snapshot") or {}).get("_orchestration")
                if refreshed
                else None
            )
            if not isinstance(refreshed_orch, dict):
                continue
            if orch_state.normalize_phase(refreshed_orch.get("phase")) != orch_state.PHASE_RECOVERY_RUNNING:
                continue
            orch = refreshed_orch
            recovery = orch.get("recovery") or {}
            command_id = recovery.get("active_command_id")
            robot_id = recovery.get("active_robot_id") or task.get("assigned_robot_id")
            if not command_id or not robot_id:
                continue
        try:
            status = movement_client.command_status(str(robot_id), str(command_id))
        except MovementClientError:
            continue
        state = str(status.get("state") or status.get("status") or "").upper()
        if state == "CANCELED":
            state = "CANCELLED"
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
        result = movement_client.manual_stop(robot_id, {"robot_name": robot_id})
    except MovementClientError as exc:
        raise HTTPException(status_code=409, detail="recovery_stop_unconfirmed") from exc
    if not isinstance(result, dict) or result.get("accepted") is not True or result.get("stopped") is not True:
        raise HTTPException(status_code=409, detail="recovery_stop_unconfirmed")


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
