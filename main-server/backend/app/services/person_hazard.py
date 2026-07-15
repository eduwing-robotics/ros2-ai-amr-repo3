"""Person hazard advisory polling and Main-owned E-stop policy (PHASE_77)."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.db.mvp.evidence import MvpEvidenceRepository
from app.db.repo_bridge import evidence_repo, safety_stop_repo
from app.services import evidence_runtime
from app.services import orchestration_state as orch_state
from app.services.movement import movement_client
from app.services.vision_proxy import (
    VisionUpstreamError,
    fetch_person_hazard_latest,
    put_person_monitor_state,
)

logger = logging.getLogger(__name__)

ROBOT_SOURCE_MAP: dict[str, str] = {
    "tb3_1": "tb3_1_picam",
    "tb3_2": "tb3_2_picam",
}

_PHYSICAL_MOTION_KINDS = frozenset({
    "move_to_point", "aruco_align", "dock_transfer", "leave_dock",
})
_ACTIVE_MOTION_STATES = frozenset({"DISPATCHING", "DISPATCHED", "RUNNING"})
_ACTIVE_RECOVERY_DISPATCH_STATES = frozenset({"PENDING", "DISPATCHING", "SENT"})

FORBIDDEN_PAYLOAD_KEYS = frozenset({
    "bbox", "bbox_xyxy", "mask", "mask_rle", "polygon", "raw_detections", "detections",
})

FORBIDDEN_MOTION_STRINGS = frozenset({
    "HOLD", "E_STOP", "STOP_COMMAND", "MOTION_CANCELLED", "BLOCKED",
})


@dataclass
class MonitorRuntime:
    robot_id: str
    source: str
    task_id: int
    enabled: bool = True
    enable_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_command_id: str | None = None
    last_leg_kind: str | None = None
    # Once the monitor is unavailable during a drive, Main has already made its
    # trusted stop decision.  Repeated failed polls must not create an E-stop
    # or safety-stop storm.
    fail_safe_triggered: bool = False


_runtime: dict[str, MonitorRuntime] = {}
_cooldown_until: dict[str, float] = {}
_degraded_log_at: dict[str, float] = {}


def robot_source(robot_id: str) -> str:
    source = ROBOT_SOURCE_MAP.get(robot_id)
    if not source:
        raise ValueError(f"unknown robot_id for person hazard: {robot_id}")
    return source


def validate_hazard_payload(payload: dict[str, Any]) -> None:
    """Reject compact-contract violations before DB write or E-stop."""

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, val in obj.items():
                if key in FORBIDDEN_PAYLOAD_KEYS:
                    raise ValueError(f"forbidden field: {key}")
                if isinstance(val, str) and val.upper() in FORBIDDEN_MOTION_STRINGS:
                    raise ValueError(f"forbidden motion string: {val}")
                _walk(val)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(payload)
    event = payload.get("event")
    if isinstance(event, dict) and event.get("trusted") is not False:
        raise ValueError("person hazard event.trusted must be false")


def active_monitors() -> list[MonitorRuntime]:
    return [m for m in _runtime.values() if m.enabled]


def get_runtime(robot_id: str) -> MonitorRuntime | None:
    return _runtime.get(robot_id)


def enable_monitor(robot_id: str, task_id: int, *, command_id: str | None = None) -> bool:
    """Arm the remote monitor and report whether movement may be dispatched."""
    if not getattr(settings, "person_hazard_enabled", True):
        return True
    source = robot_source(robot_id)
    existing = _runtime.get(robot_id)
    # A task's monitor is a continuous physical-motion envelope.  Do not
    # briefly disarm it between Nav2, ArUco, dock/lift, or leave-dock legs.
    if existing and existing.enabled and existing.task_id == task_id:
        existing.last_command_id = command_id
        return True
    if existing and existing.enabled:
        disable_monitor(robot_id, remote=True)
    body = {
        "enabled": True,
        "source": source,
        "operation_state": "DRIVE",
        "task_id": task_id,
        "target_fps": getattr(settings, "person_hazard_target_fps", 3),
    }
    try:
        put_person_monitor_state(body)
    except Exception as exc:
        logger.warning("person monitor enable failed robot=%s: %s", robot_id, exc)
        return False
    now = datetime.now(timezone.utc)
    _runtime[robot_id] = MonitorRuntime(
        robot_id=robot_id,
        source=source,
        task_id=task_id,
        enabled=True,
        enable_time=now,
        last_command_id=command_id,
        last_leg_kind="move_to_point",
    )
    return True


def disable_monitor(robot_id: str, *, remote: bool = True, conn=None) -> None:
    runtime = _runtime.get(robot_id)
    if remote and runtime:
        body = {
            "enabled": False,
            "source": runtime.source,
            "operation_state": "IDLE",
            "task_id": runtime.task_id,
            "target_fps": getattr(settings, "person_hazard_target_fps", 3),
        }
        try:
            put_person_monitor_state(body)
        except Exception as exc:
            logger.warning("person monitor disable failed robot=%s: %s", robot_id, exc)
            if conn is not None:
                evidence_repo(conn).append(
                    task_id=runtime.task_id,
                    event_type="PERSON_MONITOR_DISABLE_FAILURE",
                    source="vision_person_monitor",
                    severity="WARNING",
                    trusted=False,
                    data_json={"robot_id": robot_id, "task_id": runtime.task_id, "detail": str(exc)},
                )
    _runtime.pop(robot_id, None)


def on_move_to_point_dispatched(conn, task_id: int, robot_id: str, command_id: str) -> bool:
    """Compatibility hook for callers that cannot arm before dispatch."""
    armed = enable_monitor(robot_id, task_id, command_id=command_id)
    if not armed:
        fail_safe_monitor_outage(conn, robot_id, task_id, detail="monitor_enable_failed_after_dispatch")
    return armed


def on_move_to_point_leg_done(robot_id: str, *, conn=None) -> None:
    """Compatibility no-op: retain monitoring until the task is terminal."""


def arm_physical_motion_monitor(
    conn, robot_id: str, task_id: int, command_id: str, kind: str
) -> bool:
    """Arm or retain the person monitor before every physical-motion command."""
    existing = _runtime.get(robot_id)
    if existing and existing.enabled and existing.task_id == task_id and not existing.fail_safe_triggered:
        # Do not create a monitoring gap between adjacent movement legs.  The
        # remote monitor remains armed through approach, alignment, lift, and
        # reverse; Main only refreshes its local command/stage attribution.
        existing.last_command_id = command_id
        existing.last_leg_kind = kind
        return True
    if not enable_monitor(robot_id, task_id, command_id=command_id):
        fail_safe_monitor_outage(
            conn, robot_id, task_id, detail=f"monitor_enable_failed_before_{kind}",
        )
        return False
    runtime = _runtime.get(robot_id)
    if runtime:
        runtime.last_leg_kind = kind
    return True


def on_robot_task_terminal(robot_id: str, *, conn=None) -> None:
    disable_monitor(robot_id, conn=conn)


def mark_task_needs_attention(conn, task_id: int, *, reason: str, robot_id: str | None = None) -> None:
    repo = evidence_repo(conn)
    if isinstance(repo, MvpEvidenceRepository) and getattr(conn, "is_postgres", False) is True:
        orch = repo.lock_orchestration(task_id)
    else:
        orch = repo.get_orchestration(task_id)
    if not orch:
        return
    orch = dict(orch)
    orch_state.set_phase(orch, orch_state.PHASE_AWAITING_OPERATOR)
    orch["recovery"] = {
        "reason": reason,
        "robot_id": robot_id,
        "marked_at": datetime.now(timezone.utc).isoformat(),
    }
    evidence_runtime.save_orchestration(conn, task_id, orch)


def mark_running_tasks_needs_attention(conn, *, reason: str) -> int:
    count = 0
    for task in evidence_runtime.list_orchestrated_running(conn):
        task_id = int(task["task_id"])
        orch = (task.get("preset_snapshot") or {}).get("_orchestration") or {}
        if orch_state.normalize_phase(orch.get("phase")) == orch_state.PHASE_AWAITING_OPERATOR:
            continue
        mark_task_needs_attention(conn, task_id, reason=reason, robot_id=task.get("assigned_robot_id"))
        count += 1
    if count:
        # Fleet E-stop calls Movement only after these holds are durable and
        # every transaction-scoped task lock has been released.
        conn.commit()
    return count


def reconcile_startup_person_hazard_safety(conn) -> int:
    """Fail closed before startup pollers advance persisted physical motion."""
    if not getattr(settings, "person_hazard_enabled", True):
        return 0

    held = 0
    for task in evidence_runtime.list_orchestrated_running(conn):
        if str(task.get("status") or "").upper() != "RUNNING":
            continue
        task_id = int(task["task_id"])
        orch = (task.get("preset_snapshot") or {}).get("_orchestration") or {}
        phase = orch_state.normalize_phase(orch.get("phase"))
        robot_id = str(task.get("assigned_robot_id") or "")
        steps = orch_state.get_steps(orch)
        step_index = orch_state.get_step_index(orch)
        step = steps[step_index] if 0 <= step_index < len(steps) else {}
        preserve_existing_hold = False

        if phase == orch_state.PHASE_RUNNING:
            kind = str(step.get("kind") or "")
            command_id = str(step.get("command_id") or "")
            if (
                kind not in _PHYSICAL_MOTION_KINDS
                or str(step.get("status") or "").upper() not in _ACTIVE_MOTION_STATES
            ):
                continue
        elif phase == orch_state.PHASE_ADVANCING:
            kind = str(step.get("kind") or "")
            command_id = str(step.get("command_id") or "")
            if (
                kind not in _PHYSICAL_MOTION_KINDS
                or str(step.get("status") or "").lower() != "transition_claimed"
            ):
                continue
        elif phase == orch_state.PHASE_CANCEL_REQUESTED:
            stop_request = orch.get("stop_request") or {}
            robot_id = str(stop_request.get("robot_id") or robot_id)
            kind = str(step.get("kind") or "cancel_requested")
            command_id = str(stop_request.get("command_id") or step.get("command_id") or "")
        elif phase == orch_state.PHASE_RECOVERY_RUNNING:
            recovery = orch.get("recovery") or {}
            robot_id = str(recovery.get("active_robot_id") or robot_id)
            kind = str(recovery.get("active_command_kind") or "move_to_point")
            command_id = str(recovery.get("active_command_id") or "")
            dispatch_state = str(recovery.get("dispatch_state") or "").upper()
            pending_manual_abort = (
                recovery.get("strategy") == "manual_abort"
                and kind == "manual_stop"
                and dispatch_state == "ABORT_STOP_REQUESTED"
            )
            if not pending_manual_abort and (
                kind not in _PHYSICAL_MOTION_KINDS
                or dispatch_state not in _ACTIVE_RECOVERY_DISPATCH_STATES
            ):
                continue
        elif phase == orch_state.PHASE_AWAITING_OPERATOR:
            recovery = orch.get("recovery") or {}
            robot_id = str(recovery.get("robot_id") or robot_id)
            kind = str(step.get("kind") or "")
            command_id = str(recovery.get("command_id") or step.get("command_id") or "")
            if (
                kind not in _PHYSICAL_MOTION_KINDS
                or str(step.get("status") or "").upper() not in _ACTIVE_MOTION_STATES
            ):
                continue
            preserve_existing_hold = True
        else:
            continue
        if not robot_id:
            continue

        runtime = _runtime.get(robot_id)
        if runtime and runtime.task_id == task_id:
            if runtime.enabled and not runtime.fail_safe_triggered:
                continue
            if runtime.fail_safe_triggered:
                continue

        runtime = MonitorRuntime(
            robot_id=robot_id,
            source=robot_source(robot_id),
            task_id=task_id,
            enabled=False,
            last_command_id=command_id or None,
            last_leg_kind=kind,
        )
        _runtime[robot_id] = runtime
        logger.critical(
            "Main restart found active physical motion without person monitor "
            "task=%s robot=%s command=%s kind=%s",
            task_id,
            robot_id,
            command_id,
            kind,
        )
        if fail_safe_monitor_outage(
            conn,
            robot_id,
            task_id,
            detail="main_restart_active_motion_without_person_monitor",
            runtime=runtime,
            preserve_existing_hold=preserve_existing_hold,
        ):
            held += 1
            # Release this task's transaction-scoped lock before the next
            # robot's Vision/E-stop network calls.
            conn.commit()
    return held


def _parse_observed_at(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        text = value.replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _dedup_key(event: dict[str, Any]) -> str:
    data = event.get("data_json") or {}
    if isinstance(data, str):
        import json
        data = json.loads(data)
    source_event_id = data.get("source_event_id")
    if source_event_id:
        return str(source_event_id)
    return f"{event.get('event_id')}:{event.get('observed_at')}"


def _cooldown_active(robot_id: str, source: str, task_id: int, dedup: str) -> bool:
    key = f"{robot_id}:{source}:{task_id}:{dedup}"
    until = _cooldown_until.get(key, 0.0)
    return time.monotonic() < until


def _set_cooldown(robot_id: str, source: str, task_id: int, dedup: str) -> None:
    key = f"{robot_id}:{source}:{task_id}:{dedup}"
    _cooldown_until[key] = time.monotonic() + settings.person_hazard_cooldown_sec


def _is_stale(observed_at: datetime | None, enable_time: datetime) -> bool:
    if observed_at is None:
        return True
    now = datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    if observed_at < enable_time:
        return True
    return (now - observed_at).total_seconds() > settings.person_hazard_stale_sec


def _record_degraded(robot_id: str, detail: str) -> None:
    now = time.monotonic()
    if now - _degraded_log_at.get(robot_id, 0.0) < 5.0:
        return
    _degraded_log_at[robot_id] = now
    logger.warning("person hazard degraded robot=%s: %s", robot_id, detail)


def _attempt_estop(robot_id: str) -> tuple[bool, str | None]:
    try:
        response = movement_client.estop(robot_id)
    except Exception as exc:
        logger.error("person hazard E-stop failed robot=%s: %s", robot_id, exc)
        return False, str(exc)
    if not isinstance(response, dict):
        detail = f"invalid estop response: expected object, got {type(response).__name__}"
        logger.error("person hazard E-stop failed robot=%s: %s", robot_id, detail)
        return False, detail
    return True, None


def _record_estop_outcome(
    conn,
    *,
    decision_id: int,
    robot_id: str,
    task_id: int,
    reason_code: str,
    estop_ok: bool,
    estop_error: str | None,
) -> None:
    evidence_repo(conn).append(
        task_id=task_id,
        event_type="SAFETY_ESTOP_OUTCOME",
        source="main_safety_policy",
        severity="CRITICAL",
        trusted=True,
        data_json={
            "decision_evidence_id": decision_id,
            "robot_id": robot_id,
            "task_id": task_id,
            "reason_code": reason_code,
            "estop_ok": estop_ok,
            "estop_error": estop_error,
        },
    )
    conn.commit()


def _commit_hold_before_estop(conn, robot_id: str) -> None:
    try:
        conn.commit()
    except Exception:
        # A database outage must not suppress the physical safety action.  Do
        # not mark runtime dedup state: the next poll must retry persistence.
        _attempt_estop(robot_id)
        raise


def fail_safe_monitor_outage(
    conn,
    robot_id: str,
    task_id: int,
    *,
    detail: str,
    runtime: MonitorRuntime | None = None,
    preserve_existing_hold: bool = False,
) -> bool:
    """Persist an AI-health advisory, then make Main's idempotent trusted stop.

    The vision service is untrusted: its outage is evidence, not the stop
    authority.  Main owns the E-stop/hold decision and deliberately fails
    closed for every active or just-dispatched move.
    """
    runtime = runtime or _runtime.get(robot_id)
    if runtime is None:
        runtime = MonitorRuntime(robot_id=robot_id, source=robot_source(robot_id), task_id=task_id, enabled=False)
        _runtime[robot_id] = runtime
    if runtime.fail_safe_triggered:
        return False

    advisory_id = evidence_repo(conn).append(
        task_id=task_id,
        event_type="PERSON_MONITOR_HEALTH_FAILURE",
        source="vision_person_monitor",
        severity="CRITICAL",
        trusted=False,
        data_json={
            "robot_id": robot_id,
            "task_id": task_id,
            "detail": detail,
            "reason_code": "AI_MONITOR_UNAVAILABLE",
        },
    )
    decision_id = evidence_repo(conn).append(
        task_id=task_id,
        event_type="SAFETY_ESTOP_DECISION",
        source="main_safety_policy",
        severity="CRITICAL",
        trusted=True,
        data_json={
            "advisory_evidence_id": advisory_id,
            "robot_id": robot_id,
            "task_id": task_id,
            "reason_code": "PERSON_MONITOR_OUTAGE",
            "estop_ok": None,
            "estop_error": None,
        },
    )
    safety_stop_repo(conn).open_from_evidence(decision_id)
    if not preserve_existing_hold:
        mark_task_needs_attention(conn, task_id, reason="person_monitor_outage", robot_id=robot_id)
    # The trusted decision, safety stop, and operator hold must survive even if
    # Movement returns malformed data or raises an unexpected exception.  This
    # transaction boundary also releases the task advisory lock before HTTP.
    _commit_hold_before_estop(conn, robot_id)
    runtime.fail_safe_triggered = True
    runtime.enabled = False

    estop_ok, estop_error = _attempt_estop(robot_id)
    _record_estop_outcome(
        conn,
        decision_id=decision_id,
        robot_id=robot_id,
        task_id=task_id,
        reason_code="PERSON_MONITOR_OUTAGE",
        estop_ok=estop_ok,
        estop_error=estop_error,
    )
    return True


def process_advisory(conn, runtime: MonitorRuntime, payload: dict[str, Any]) -> bool:
    """Return True if E-stop decision was taken."""
    validate_hazard_payload(payload)
    event = payload.get("event") or {}
    if not isinstance(event, dict):
        return False
    event_task = event.get("task_id")
    if event_task is not None and str(event_task) != str(runtime.task_id):
        return False
    observed_at = _parse_observed_at(str(event.get("observed_at") or ""))
    if _is_stale(observed_at, runtime.enable_time):
        return False
    dedup = _dedup_key(event)
    if _cooldown_active(runtime.robot_id, runtime.source, runtime.task_id, dedup):
        return False

    data_json = event.get("data_json") or {}
    if isinstance(data_json, str):
        import json
        data_json = json.loads(data_json)

    advisory_id = evidence_repo(conn).append(
        task_id=runtime.task_id,
        event_type="HUMAN_DETECTED",
        source=str(event.get("source") or runtime.source),
        confidence=event.get("confidence"),
        severity="CRITICAL",
        trusted=False,
        data_json={
            "event_id": event.get("event_id"),
            "source_event_id": data_json.get("source_event_id"),
            "observed_at": event.get("observed_at"),
            "policy_version": event.get("policy_version"),
            "profile_id": event.get("profile_id"),
            "threshold_set_id": event.get("threshold_set_id"),
            "robot_id": runtime.robot_id,
        },
    )

    decision_id = evidence_repo(conn).append(
        task_id=runtime.task_id,
        event_type="SAFETY_ESTOP_DECISION",
        source="main_safety_policy",
        severity="CRITICAL",
        trusted=True,
        data_json={
            "advisory_evidence_id": advisory_id,
            "robot_id": runtime.robot_id,
            "source": runtime.source,
            "task_id": runtime.task_id,
            "dedup_key": dedup,
            "estop_ok": None,
            "estop_error": None,
            "observed_at": event.get("observed_at"),
        },
    )
    safety_stop_repo(conn).open_from_evidence(decision_id)
    mark_task_needs_attention(conn, runtime.task_id, reason="person_hazard", robot_id=runtime.robot_id)
    # Persist Main's safety authority and release its task lock before calling
    # the untrusted remote movement boundary.
    _commit_hold_before_estop(conn, runtime.robot_id)
    _set_cooldown(runtime.robot_id, runtime.source, runtime.task_id, dedup)
    estop_ok, estop_error = _attempt_estop(runtime.robot_id)
    _record_estop_outcome(
        conn,
        decision_id=decision_id,
        robot_id=runtime.robot_id,
        task_id=runtime.task_id,
        reason_code="PERSON_HAZARD",
        estop_ok=estop_ok,
        estop_error=estop_error,
    )
    return estop_ok


def handle_hazard_response(conn, runtime: MonitorRuntime, payload: dict[str, Any]) -> None:
    result = str(payload.get("result") or "").upper()
    reason = str(payload.get("reason_code") or "").upper()
    if result == "ADVISORY" and reason == "HUMAN_DETECTED":
        process_advisory(conn, runtime, payload)
        return
    if result == "NO_ACTIVE_MONITOR":
        if runtime.enabled:
            logger.warning("NO_ACTIVE_MONITOR during DRIVE robot=%s — reassert enable", runtime.robot_id)
            if not enable_monitor(runtime.robot_id, runtime.task_id, command_id=runtime.last_command_id):
                fail_safe_monitor_outage(
                    conn,
                    runtime.robot_id,
                    runtime.task_id,
                    detail="monitor_lost_and_rearm_failed",
                    runtime=runtime,
                )
        return
    if result == "NO_RELEVANT_DETECTION":
        return


def poll_robot(conn, runtime: MonitorRuntime) -> None:
    if runtime.fail_safe_triggered:
        return
    try:
        payload = fetch_person_hazard_latest(runtime.robot_id)
    except VisionUpstreamError as exc:
        _record_degraded(runtime.robot_id, str(exc))
        fail_safe_monitor_outage(
            conn, runtime.robot_id, runtime.task_id, detail=f"poll_failed: {exc}", runtime=runtime,
        )
        return
    except Exception as exc:
        logger.exception("unexpected person hazard poll failure robot=%s", runtime.robot_id)
        fail_safe_monitor_outage(
            conn, runtime.robot_id, runtime.task_id, detail=f"poll_exception: {exc}", runtime=runtime,
        )
        return
    handle_hazard_response(conn, runtime, payload)


def poll_once(conn) -> int:
    if not settings.person_hazard_enabled:
        return 0
    polled = 0
    for runtime in list(active_monitors()):
        poll_robot(conn, runtime)
        # A hazard or monitor outage may have acquired the task advisory lock.
        # Persist that hold before polling the next robot over the network.
        conn.commit()
        polled += 1
    return polled
