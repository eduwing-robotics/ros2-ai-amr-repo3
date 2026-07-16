"""E-stop recovery plan and operator decision APIs (PHASE_78)."""

from __future__ import annotations

import json
import threading
from collections import defaultdict
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
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
RECOVERY_DISPATCHING = "DISPATCHING"
RECOVERY_DISPATCH_SENT = "SENT"
RECOVERY_ABORT_STOP_REQUESTED = "ABORT_STOP_REQUESTED"
_recovery_command_locks: defaultdict[int, threading.RLock] = defaultdict(threading.RLock)


def _orchestration_fingerprint(orchestration: dict[str, Any]) -> str:
    canonical = json.dumps(
        orchestration,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return sha256(canonical.encode("utf-8")).hexdigest()


def _active_task_safety_stops(conn, task_id: int) -> list[dict[str, Any]]:
    task_evidence_ids = {
        int(row["id"])
        for row in evidence_repo(conn).list_for_task(task_id)
        if row.get("id") is not None
    }
    return [
        row
        for row in safety_stop_repo(conn).list_active()
        if row.get("detected_evidence_id") in task_evidence_ids
        and str(row.get("status") or "").upper() in {"OPEN", "HOLDING"}
    ]


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
    provenance = orch.get("provenance") if isinstance(orch.get("provenance"), dict) else {}
    scenario = orch.get("scenario") if isinstance(orch.get("scenario"), dict) else {}
    decision = (current_step or {}).get("decision") if isinstance((current_step or {}).get("decision"), dict) else recovery.get("gate_decision") or {}
    execution_mode = str(provenance.get("execution_mode") or "physical")
    hold_reason = str(recovery.get("reason") or orch.get("hold_reason") or "")
    evidence_hold = hold_reason in {"evidence_gate", "evidence_not_approved", "manual_fixture_transfer_required"}
    if execution_mode == "evidence_only":
        recommended_actions = ["retry_evidence", "cancel_test"]
    elif evidence_hold:
        recommended_actions = ["retry_evidence_with_safety_checks", "safe_move", "manual_abort"]
    else:
        recommended_actions = ["safe_move", "manual_abort"]
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
        "execution_mode": execution_mode,
        "evidence_class": provenance.get("evidence_class", "physical"),
        "inventory_mutation_allowed": provenance.get("inventory_mutation_allowed", True),
        "hold_reason": hold_reason,
        "recommended_actions": recommended_actions,
        "evidence": {
            "operation": (current_step or {}).get("operation") or ((current_step or {}).get("params") or {}).get("evidence_operation"),
            "vision_zone_id": (current_step or {}).get("vision_zone_id"),
            "expected_marker_id": scenario.get("expected_marker_id"),
            "expected_item_id": scenario.get("expected_item_id"),
            "result": decision.get("result"),
            "reason_code": decision.get("reason_code"),
            "command_satisfying": decision.get("command_satisfying"),
        },
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
        plan = preview_recovery_plan(
            conn,
            task_id,
            cargo_state=cargo_state,
            strategy=strategy,
        )
        task = task_repo(conn).get(task_id)
        if not task:
            raise HTTPException(status_code=404, detail="task not found")
        if task.get("status") != "RUNNING":
            raise HTTPException(status_code=409, detail="task is not running")
        robot_id = task.get("assigned_robot_id") or task.get("robot_id")
        if not robot_id:
            raise HTTPException(status_code=409, detail="task has no assigned robot")
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
            )
            recovery = dict(orch.get("recovery") or {})
            recovery.update(
                {
                    "active_command_kind": "manual_stop",
                    "active_robot_id": str(robot_id),
                    "dispatch_state": RECOVERY_ABORT_STOP_REQUESTED,
                    "strategy": strategy,
                    "cargo_state": cargo_state,
                }
            )
            orch["recovery"] = recovery
            orch_state.set_phase(orch, orch_state.PHASE_RECOVERY_RUNNING)
            evidence_runtime.save_orchestration(conn, task_id, orch)
            evidence_repo(conn).append(
                task_id=task_id,
                event_type="RECOVERY_MANUAL_ABORT_STOP_REQUESTED",
                source="main_recovery",
                trusted=True,
                data_json={"robot_id": str(robot_id), "strategy": strategy},
            )
            conn.commit()

        try:
            _stop_robot_movement(str(robot_id))
        except Exception:
            conn.rollback()
            _hold_unconfirmed_manual_abort(conn, task_id, orch)
            raise

        result = _finalize_manual_abort(
            conn,
            task_id,
            orch,
            robot_id=str(robot_id),
            cargo_state=cargo_state,
            checks=checks,
        )
        # Vision disable is remote I/O.  The task cancellation and robot
        # release above are already committed before this best-effort call.
        person_hazard.on_robot_task_terminal(str(robot_id), conn=conn)
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
    held_orchestration = evidence_repo(conn).get_orchestration(task_id) or {}
    if (
        orch_state.normalize_phase(held_orchestration.get("phase"))
        != orch_state.PHASE_AWAITING_OPERATOR
    ):
        raise HTTPException(status_code=409, detail="recovery_requires_needs_attention_phase")
    held_fingerprint = _orchestration_fingerprint(held_orchestration)
    trusted_safety_gate = dict(
        _verify_recovery_safety_gate(
            conn,
            task_id,
            str(robot_id),
            held_orchestration_fingerprint=held_fingerprint,
        )
    )
    trusted_safety_gate["held_orchestration_fingerprint"] = held_fingerprint
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
        if _active_task_safety_stops(conn, task_id):
            raise HTTPException(status_code=409, detail="recovery_blocked_active_safety_stop")
        if _orchestration_fingerprint(orch) != trusted_safety_gate.get(
            "held_orchestration_fingerprint"
        ):
            raise HTTPException(status_code=409, detail="recovery_safety_gate_stale")
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

    # Vision is remote I/O. Arm it before taking the short task claim; a
    # monitor failure may itself E-stop and persist a newer operator hold.
    if not person_hazard.arm_physical_motion_monitor(
        conn,
        robot_id,
        task_id,
        command_id,
        command_kind,
    ):
        # A real arm failure has already recorded Main's trusted fail-safe
        # E-stop/hold on this connection; make that safety decision durable.
        conn.commit()
        _hold_recovery_dispatch(
            conn,
            task_id,
            command_id,
            orch,
            reason="person_monitor_outage",
            result="PERSON_MONITOR_UNAVAILABLE",
            cargo_state=None,
        )
        raise HTTPException(status_code=503, detail="person_monitor_unavailable")

    claimed = _claim_recovery_dispatch(conn, task_id, command_id, orch)
    if claimed is None:
        raise HTTPException(status_code=409, detail="recovery command superseded")

    try:
        # The DISPATCHING claim above is durable and its advisory lock has been
        # released. A synchronous Nav callback or safety hold can now acquire
        # the same task lock while this network request is in flight.
        result = command_service.dispatch_robot_command(conn, payload, request=None)
    except Exception:
        conn.rollback()
        _fail_close_ambiguous_recovery_dispatch(
            conn,
            task_id,
            command_id,
            robot_id,
            claimed,
        )
        raise

    command_id_mismatch = str(result.command_id) != command_id
    accepted = bool(result.accepted) and not command_id_mismatch
    finalized, stop_requested = _finalize_recovery_dispatch(
        conn,
        task_id,
        command_id,
        claimed,
        accepted=accepted,
        command_kind=command_kind,
    )
    if accepted and finalized and stop_requested:
        _enforce_stop_requested_during_dispatch(
            conn,
            task_id,
            command_id,
            robot_id,
            claimed,
        )
    if not accepted:
        if finalized:
            # Best-effort remote cleanup happens only after the short finalize
            # transaction has released the task lock.
            person_hazard.disable_monitor(robot_id, conn=conn)
        if command_id_mismatch:
            raise HTTPException(status_code=502, detail="recovery command id mismatch")
    return result


def _clear_active_recovery_command(recovery: dict[str, Any]) -> None:
    recovery.pop("active_command_id", None)
    recovery.pop("active_command_kind", None)
    recovery.pop("active_robot_id", None)
    recovery.pop("active_command_params", None)


def _claim_recovery_dispatch(
    conn,
    task_id: int,
    command_id: str,
    fallback: dict[str, Any],
) -> dict[str, Any] | None:
    """Persist PENDING -> DISPATCHING and release the task lock before HTTP."""
    with recovery_command_guard(conn, task_id, command_id, fallback=fallback) as latest:
        if latest is None:
            conn.rollback()
            return None
        recovery = dict(latest.get("recovery") or {})
        if recovery.get("stop_requested") is True:
            if recovery.get("dispatch_state") == RECOVERY_DISPATCH_PENDING:
                _clear_active_recovery_command(recovery)
                recovery.pop("dispatch_state", None)
                recovery["cargo_state"] = "UNKNOWN"
                recovery["reason"] = "operator_safe_stop_before_dispatch"
                latest["recovery"] = recovery
                orch_state.set_phase(latest, orch_state.PHASE_AWAITING_OPERATOR)
                evidence_runtime.save_orchestration(conn, task_id, latest)
                conn.commit()
            else:
                conn.rollback()
            raise HTTPException(status_code=409, detail="recovery stop already requested")
        if recovery.get("dispatch_state") != RECOVERY_DISPATCH_PENDING:
            conn.rollback()
            return None
        recovery["dispatch_state"] = RECOVERY_DISPATCHING
        latest["recovery"] = recovery
        evidence_runtime.save_orchestration(conn, task_id, latest)
        conn.commit()
        return latest


def _hold_recovery_dispatch(
    conn,
    task_id: int,
    command_id: str,
    fallback: dict[str, Any],
    *,
    reason: str,
    result: str,
    cargo_state: str | None,
) -> bool:
    """Fail closed only if the same recovery command still owns the task."""
    with recovery_command_guard(conn, task_id, command_id, fallback=fallback) as latest:
        if latest is None:
            conn.rollback()
            return False
        recovery = dict(latest.get("recovery") or {})
        _clear_active_recovery_command(recovery)
        recovery["dispatch_state"] = "REJECTED"
        recovery["last_recovery_result"] = result
        recovery["reason"] = reason
        if cargo_state is not None:
            recovery["cargo_state"] = cargo_state
        latest["recovery"] = recovery
        orch_state.set_phase(latest, orch_state.PHASE_AWAITING_OPERATOR)
        evidence_runtime.save_orchestration(conn, task_id, latest)
        conn.commit()
        return True


def _fail_close_ambiguous_recovery_dispatch(
    conn,
    task_id: int,
    command_id: str,
    robot_id: str,
    fallback: dict[str, Any],
) -> None:
    """E-stop an ambiguous HTTP delivery, then persist an operator hold."""
    estop_ok = False
    estop_error: str | None = None
    try:
        movement_client.estop(robot_id)
        estop_ok = True
    except Exception as exc:
        estop_error = str(exc)
    held = _hold_recovery_dispatch(
        conn,
        task_id,
        command_id,
        fallback,
        reason="recovery_dispatch_ambiguous",
        result="DISPATCH_ERROR",
        cargo_state="UNKNOWN",
    )
    if held:
        evidence_repo(conn).append(
            task_id=task_id,
            event_type="RECOVERY_DISPATCH_AMBIGUOUS_STOP",
            source="main_recovery",
            severity="CRITICAL",
            trusted=True,
            data_json={
                "command_id": command_id,
                "robot_id": robot_id,
                "estop_ok": estop_ok,
                "estop_error": estop_error,
            },
        )
        conn.commit()


def _finalize_recovery_dispatch(
    conn,
    task_id: int,
    command_id: str,
    fallback: dict[str, Any],
    *,
    accepted: bool,
    command_kind: str,
) -> tuple[bool, bool]:
    """Finalize only the exact durable DISPATCHING claim after Movement HTTP."""
    with recovery_command_guard(conn, task_id, command_id, fallback=fallback) as latest:
        if latest is None:
            conn.rollback()
            return False, False
        recovery = dict(latest.get("recovery") or {})
        if recovery.get("dispatch_state") != RECOVERY_DISPATCHING:
            conn.rollback()
            return False, False
        stop_requested = recovery.get("stop_requested") is True
        if accepted:
            recovery["dispatch_state"] = RECOVERY_DISPATCH_SENT
            latest["recovery"] = recovery
            evidence_runtime.save_orchestration(conn, task_id, latest)
            evidence_repo(conn).append(
                task_id=task_id,
                event_type="RECOVERY_COMMAND_DISPATCHED",
                source="main_recovery",
                trusted=True,
                data_json={
                    "command_id": command_id,
                    "kind": command_kind,
                    "strategy": recovery.get("strategy"),
                },
            )
        else:
            _clear_active_recovery_command(recovery)
            recovery["dispatch_state"] = "REJECTED"
            recovery["last_recovery_result"] = "REJECTED"
            latest["recovery"] = recovery
            orch_state.set_phase(latest, orch_state.PHASE_AWAITING_OPERATOR)
            evidence_runtime.save_orchestration(conn, task_id, latest)
        conn.commit()
        return True, stop_requested


def _mark_recovery_stop_unconfirmed(
    conn,
    task_id: int,
    command_id: str,
    fallback: dict[str, Any],
) -> bool:
    """Keep the command identity retryable when cancel and E-stop are unknown."""
    with recovery_command_guard(conn, task_id, command_id, fallback=fallback) as latest:
        if latest is None:
            conn.rollback()
            return False
        recovery = dict(latest.get("recovery") or {})
        if recovery.get("stop_requested") is not True:
            conn.rollback()
            return False
        recovery["cargo_state"] = "UNKNOWN"
        recovery["reason"] = "physical_stop_unconfirmed"
        recovery["last_recovery_result"] = "STOP_UNCONFIRMED"
        latest["recovery"] = recovery
        evidence_runtime.save_orchestration(conn, task_id, latest)
        conn.commit()
        return True


def _enforce_stop_requested_during_dispatch(
    conn,
    task_id: int,
    command_id: str,
    robot_id: str,
    fallback: dict[str, Any],
) -> None:
    """Close a stop/dispatch race before the dispatching request returns."""
    cancel_state = "STOP_UNCONFIRMED"
    cancel_error: str | None = None
    try:
        stopped = movement_client.cancel_command(robot_id, command_id)
        if isinstance(stopped, dict):
            cancel_state = str(stopped.get("state") or "").upper()
        if cancel_state == "CANCELED" or cancel_state == "STOPPED":
            cancel_state = "CANCELLED"
    except Exception as exc:
        cancel_error = str(exc)

    if cancel_state in RECOVERY_TERMINAL_EVENTS - {"STOP_UNCONFIRMED"}:
        handle_recovery_command_event(
            conn,
            task_id,
            {"command_id": command_id, "state": cancel_state},
            source="post_dispatch_stop_race",
        )
        raise HTTPException(status_code=409, detail="recovery stop already requested")

    estop_ok = False
    estop_error: str | None = None
    try:
        movement_client.estop(robot_id)
        estop_ok = True
    except Exception as exc:
        estop_error = str(exc)

    if estop_ok:
        _hold_recovery_dispatch(
            conn,
            task_id,
            command_id,
            fallback,
            reason="operator_safe_stop_after_dispatch",
            result="ESTOP_CONFIRMED",
            cargo_state="UNKNOWN",
        )
    else:
        _mark_recovery_stop_unconfirmed(conn, task_id, command_id, fallback)
    evidence_repo(conn).append(
        task_id=task_id,
        event_type="RECOVERY_POST_DISPATCH_STOP",
        source="main_recovery",
        severity="CRITICAL",
        trusted=True,
        data_json={
            "command_id": command_id,
            "robot_id": robot_id,
            "cancel_state": cancel_state,
            "cancel_error": cancel_error,
            "estop_ok": estop_ok,
            "estop_error": estop_error,
        },
    )
    conn.commit()
    raise HTTPException(status_code=409, detail="recovery stop already requested")


def _verify_recovery_safety_gate(
    conn,
    task_id: int,
    robot_id: str,
    *,
    held_orchestration_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Require DB stop closure and a fresh, unambiguous non-emergency health response.

    Operator-provided checkboxes are intentionally not safety authority.  The
    health probe is forced to bypass SWR cache so a prior clear acknowledgement
    cannot authorize recovery after a newer emergency state.
    """
    held_orchestration = evidence_repo(conn).get_orchestration(task_id) or {}
    if (
        orch_state.normalize_phase(held_orchestration.get("phase"))
        != orch_state.PHASE_AWAITING_OPERATOR
    ):
        raise HTTPException(status_code=409, detail="recovery_requires_needs_attention_phase")
    observed_fingerprint = _orchestration_fingerprint(held_orchestration)
    held_fingerprint = held_orchestration_fingerprint or observed_fingerprint
    if observed_fingerprint != held_fingerprint:
        raise HTTPException(status_code=409, detail="recovery_safety_gate_stale")
    active_stops = _active_task_safety_stops(conn, task_id)
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
        "held_orchestration_fingerprint": held_fingerprint,
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


def _hold_unconfirmed_manual_abort(
    conn,
    task_id: int,
    fallback: dict[str, Any],
) -> bool:
    """Restore the operator hold after an unconfirmed unlocked stop request."""
    with recovery_start_guard(conn, task_id, fallback=fallback) as latest:
        if latest is None:
            conn.rollback()
            return False
        recovery = dict(latest.get("recovery") or {})
        if (
            orch_state.normalize_phase(latest.get("phase"))
            != orch_state.PHASE_RECOVERY_RUNNING
            or recovery.get("strategy") != "manual_abort"
            or recovery.get("dispatch_state") != RECOVERY_ABORT_STOP_REQUESTED
        ):
            conn.rollback()
            return False
        _clear_active_recovery_command(recovery)
        recovery["dispatch_state"] = "REJECTED"
        recovery["last_recovery_result"] = "STOP_UNCONFIRMED"
        recovery["reason"] = "physical_stop_unconfirmed"
        recovery["cargo_state"] = "UNKNOWN"
        latest["recovery"] = recovery
        orch_state.set_phase(latest, orch_state.PHASE_AWAITING_OPERATOR)
        evidence_runtime.save_orchestration(conn, task_id, latest)
        evidence_repo(conn).append(
            task_id=task_id,
            event_type="RECOVERY_MANUAL_ABORT_STOP_UNCONFIRMED",
            source="main_recovery",
            severity="CRITICAL",
            trusted=True,
            data_json={"cargo_state": "UNKNOWN"},
        )
        conn.commit()
        return True


def _finalize_manual_abort(
    conn,
    task_id: int,
    fallback: dict[str, Any],
    *,
    robot_id: str,
    cargo_state: CargoState,
    checks: dict[str, bool],
) -> dict[str, Any]:
    """Cancel the task only when the exact durable stop intent still wins."""
    from app.db.repo_bridge import robot_repo

    with recovery_start_guard(conn, task_id, fallback=fallback) as latest:
        if latest is None:
            conn.rollback()
            raise HTTPException(status_code=409, detail="manual_abort_superseded")
        recovery = dict(latest.get("recovery") or {})
        if (
            orch_state.normalize_phase(latest.get("phase"))
            != orch_state.PHASE_RECOVERY_RUNNING
            or recovery.get("strategy") != "manual_abort"
            or recovery.get("dispatch_state") != RECOVERY_ABORT_STOP_REQUESTED
            or str(recovery.get("active_robot_id") or "") != robot_id
        ):
            conn.rollback()
            raise HTTPException(status_code=409, detail="manual_abort_superseded")
        task = task_repo(conn).get(task_id)
        if not task or task.get("status") != "RUNNING":
            conn.rollback()
            raise HTTPException(status_code=409, detail="task is not running")

        task_repo(conn).set_status(task_id, "CANCELLED", clear_robot=True)
        robot_repo(conn).set_task(robot_id, "IDLE", None)
        _clear_active_recovery_command(recovery)
        recovery.pop("dispatch_state", None)
        recovery["last_recovery_result"] = "STOP_CONFIRMED"
        latest["recovery"] = recovery
        orch_state.set_phase(latest, orch_state.PHASE_ABORTED)
        evidence_runtime.save_orchestration(conn, task_id, latest)
        evidence_repo(conn).append(
            task_id=task_id,
            event_type="RECOVERY_MANUAL_ABORT",
            source="operator",
            trusted=True,
            data_json={"cargo_state": cargo_state, "checks": checks},
        )
        conn.commit()

    return {
        "task_id": task_id,
        "strategy": "manual_abort",
        "status": "CANCELLED",
        "message": "작업이 중단되었습니다. 필요 시 새 입출고 요청을 생성하세요.",
    }
