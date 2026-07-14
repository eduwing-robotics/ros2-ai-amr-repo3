"""Person hazard advisory polling and Main-owned E-stop policy."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.core.config import settings
from app.db.postgres import runtime_records, safety_stops
from app.domains.execution import evidence
from app.domains.execution import state as orch_state
from app.domains.movement.client import MovementClientError, movement_client
from app.domains.vision.client import (
    VisionUpstreamError,
    fetch_person_hazard_latest,
    put_person_monitor_state,
)
from app.models.person_hazard import validate_person_hazard_payload

logger = logging.getLogger(__name__)

ROBOT_SOURCE_MAP: dict[str, str] = {
    "tb3_1": "tb3_1_picam",
    "tb3_2": "tb3_2_picam",
}

@dataclass(slots=True)
class PersonHazardMonitorRuntime:
    robot_id: str
    source: str
    task_id: int
    enabled: bool = True
    enable_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_command_id: str | None = None
    last_step_kind: str | None = None


_runtime: dict[str, PersonHazardMonitorRuntime] = {}
_cooldown_until: dict[str, float] = {}
_degraded_log_at: dict[str, float] = {}
_pending_estops: dict[str, int] = {}
_processed_advisories: dict[str, float] = {}
_last_reconcile_at = 0.0
RECONCILE_INTERVAL_SEC = 5.0
ADVISORY_REPLAY_TTL_SEC = 3600.0
MAX_PROCESSED_ADVISORIES = 10_000


def robot_source(robot_id: str) -> str:
    source = ROBOT_SOURCE_MAP.get(robot_id)
    if not source:
        raise ValueError(f"unknown robot_id for person hazard: {robot_id}")
    return source


def active_monitors() -> list[PersonHazardMonitorRuntime]:
    return [m for m in _runtime.values() if m.enabled]


def get_runtime(robot_id: str) -> PersonHazardMonitorRuntime | None:
    return _runtime.get(robot_id)


def reconcile_active_monitors(conn, *, force: bool = False) -> int:
    """Restore process-local monitors from durable RUNNING orchestration state."""
    global _last_reconcile_at
    now = time.monotonic()
    if not force and now - _last_reconcile_at < RECONCILE_INTERVAL_SEC:
        return 0
    _last_reconcile_at = now
    restored = 0
    for task in evidence.list_orchestrated_running(conn):
        robot_id = str(task.get("assigned_robot_id") or "")
        if not robot_id or get_runtime(robot_id):
            continue
        orch = (task.get("preset_snapshot") or {}).get("_orchestration") or {}
        steps = orch_state.get_steps(orch)
        step_index = orch_state.get_step_index(orch)
        if step_index >= len(steps):
            continue
        step = steps[step_index]
        if step.get("kind") != "move_to_point" or not orch_state.is_dispatched_robot_task_step(step):
            continue
        enable_monitor(robot_id, int(task["task_id"]), command_id=str(step.get("command_id") or "") or None)
        if get_runtime(robot_id):
            restored += 1
    return restored


def enable_monitor(robot_id: str, task_id: int, *, command_id: str | None = None) -> None:
    if not settings.person_hazard_enabled:
        return
    source = robot_source(robot_id)
    if robot_id in _runtime and _runtime[robot_id].enabled:
        disable_monitor(robot_id, remote=True)
    body = {
        "enabled": True,
        "source": source,
        "operation_state": "DRIVE",
        "task_id": task_id,
        "target_fps": settings.person_hazard_target_fps,
    }
    try:
        put_person_monitor_state(body)
    except VisionUpstreamError as exc:
        logger.warning("person monitor enable failed robot=%s: %s", robot_id, exc)
        return
    now = datetime.now(timezone.utc)
    _runtime[robot_id] = PersonHazardMonitorRuntime(
        robot_id=robot_id,
        source=source,
        task_id=task_id,
        enabled=True,
        enable_time=now,
        last_command_id=command_id,
        last_step_kind="move_to_point",
    )


def disable_monitor(robot_id: str, *, remote: bool = True) -> None:
    runtime = _runtime.get(robot_id)
    if remote and runtime:
        body = {
            "enabled": False,
            "source": runtime.source,
            "operation_state": "IDLE",
            "task_id": runtime.task_id,
            "target_fps": settings.person_hazard_target_fps,
        }
        try:
            put_person_monitor_state(body)
        except VisionUpstreamError as exc:
            logger.warning("person monitor disable failed robot=%s: %s", robot_id, exc)
    _runtime.pop(robot_id, None)


def on_move_to_point_dispatched(conn, task_id: int, robot_id: str, command_id: str) -> None:
    enable_monitor(robot_id, task_id, command_id=command_id)


def on_move_to_point_step_done(robot_id: str) -> None:
    disable_monitor(robot_id)


def on_robot_task_terminal(robot_id: str) -> None:
    disable_monitor(robot_id)


def mark_task_awaiting_operator(conn, task_id: int, *, reason: str, robot_id: str | None = None) -> None:
    orch = runtime_records.get_orchestration(conn, task_id)
    if not orch:
        return
    orch = dict(orch)
    execution = orch_state.RobotTaskExecutionState.wrap(orch)
    execution.transition_to(orch_state.PHASE_AWAITING_OPERATOR)
    execution.replace_recovery({
        "reason": reason,
        "robot_id": robot_id,
        "marked_at": datetime.now(timezone.utc).isoformat(),
    })
    evidence.save_orchestration(conn, task_id, orch)


def mark_running_tasks_awaiting_operator(conn, *, reason: str) -> int:
    count = 0
    for task in evidence.list_orchestrated_running(conn):
        task_id = int(task["task_id"])
        orch = (task.get("preset_snapshot") or {}).get("_orchestration") or {}
        if orch_state.RobotTaskExecutionState.wrap(orch).phase == orch_state.PHASE_AWAITING_OPERATOR:
            continue
        mark_task_awaiting_operator(conn, task_id, reason=reason, robot_id=task.get("assigned_robot_id"))
        robot_id = task.get("assigned_robot_id")
        if robot_id:
            on_robot_task_terminal(str(robot_id))
        count += 1
    return count


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


def _advisory_replay_key(runtime: PersonHazardMonitorRuntime, dedup: str) -> str:
    return f"{runtime.robot_id}:{runtime.source}:{runtime.task_id}:{dedup}"


def _advisory_seen(runtime: PersonHazardMonitorRuntime, dedup: str) -> bool:
    now = time.monotonic()
    expired = [key for key, seen_at in _processed_advisories.items() if now - seen_at > ADVISORY_REPLAY_TTL_SEC]
    for key in expired:
        _processed_advisories.pop(key, None)
    return _advisory_replay_key(runtime, dedup) in _processed_advisories


def _mark_advisory_seen(runtime: PersonHazardMonitorRuntime, dedup: str) -> None:
    if len(_processed_advisories) >= MAX_PROCESSED_ADVISORIES:
        oldest = min(_processed_advisories, key=_processed_advisories.get)
        _processed_advisories.pop(oldest, None)
    _processed_advisories[_advisory_replay_key(runtime, dedup)] = time.monotonic()


def _is_stale(observed_at: datetime | None, enable_time: datetime) -> bool:
    if observed_at is None:
        return True
    now = datetime.now(timezone.utc)
    if observed_at.tzinfo is None:
        observed_at = observed_at.replace(tzinfo=timezone.utc)
    if (observed_at - now).total_seconds() > settings.person_hazard_stale_sec:
        return True
    if observed_at < enable_time:
        return True
    return (now - observed_at).total_seconds() > settings.person_hazard_stale_sec


def _record_degraded(robot_id: str, detail: str) -> None:
    now = time.monotonic()
    if now - _degraded_log_at.get(robot_id, 0.0) < 5.0:
        return
    _degraded_log_at[robot_id] = now
    logger.warning("person hazard degraded robot=%s: %s", robot_id, detail)


def apply_person_hazard_advisory(conn, runtime: PersonHazardMonitorRuntime, payload: dict[str, Any]) -> bool:
    """Return True if E-stop decision was taken."""
    validate_person_hazard_payload(
        payload,
        expected_robot_id=runtime.robot_id,
        expected_source=runtime.source,
        expected_task_id=runtime.task_id,
    )
    event = payload.get("event") or {}
    if not isinstance(event, dict):
        return False
    observed_at = _parse_observed_at(str(event.get("observed_at") or ""))
    if _is_stale(observed_at, runtime.enable_time):
        return False
    dedup = _dedup_key(event)
    if _advisory_seen(runtime, dedup):
        return False
    if _cooldown_active(runtime.robot_id, runtime.source, runtime.task_id, dedup):
        return False

    data_json = event.get("data_json") or {}
    if isinstance(data_json, str):
        import json

        data_json = json.loads(data_json)

    advisory_id = runtime_records.append(
        conn,
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

    estop_ok = False
    estop_error: str | None = None
    if settings.person_hazard_action == "estop":
        try:
            movement_client.estop(runtime.robot_id)
            estop_ok = True
            _pending_estops.pop(runtime.robot_id, None)
        except MovementClientError as exc:
            estop_error = str(exc)
            _pending_estops[runtime.robot_id] = runtime.task_id

    decision_id = runtime_records.append(
        conn,
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
            "estop_ok": estop_ok,
            "estop_error": estop_error,
            "observed_at": event.get("observed_at"),
        },
    )
    safety_stops.open_from_evidence(conn, decision_id)
    mark_task_awaiting_operator(conn, runtime.task_id, reason="person_hazard", robot_id=runtime.robot_id)
    _mark_advisory_seen(runtime, dedup)
    _set_cooldown(runtime.robot_id, runtime.source, runtime.task_id, dedup)
    return estop_ok


def retry_pending_estops(conn) -> int:
    """Retry unconfirmed safety commands independently from advisory deduplication."""
    confirmed = 0
    for robot_id, task_id in list(_pending_estops.items()):
        try:
            movement_client.estop(robot_id)
        except MovementClientError as exc:
            _record_degraded(robot_id, f"E-stop retry failed: {exc}")
            continue
        runtime_records.append(
            conn,
            task_id=task_id,
            event_type="SAFETY_ESTOP_CONFIRMED",
            source="main_safety_policy",
            severity="CRITICAL",
            trusted=True,
            data_json={"robot_id": robot_id, "task_id": task_id, "retry": True},
        )
        _pending_estops.pop(robot_id, None)
        confirmed += 1
    return confirmed


def apply_person_hazard_response(conn, runtime: PersonHazardMonitorRuntime, payload: dict[str, Any]) -> None:
    result = str(payload.get("result") or "").upper()
    reason = str(payload.get("reason_code") or "").upper()
    if result == "ADVISORY" and reason == "HUMAN_DETECTED":
        apply_person_hazard_advisory(conn, runtime, payload)
        return
    if result == "NO_ACTIVE_MONITOR":
        if runtime.enabled:
            logger.warning("NO_ACTIVE_MONITOR during DRIVE robot=%s — reassert enable", runtime.robot_id)
            enable_monitor(runtime.robot_id, runtime.task_id, command_id=runtime.last_command_id)
        return
    if result == "NO_RELEVANT_DETECTION":
        return


def poll_robot_person_hazard(conn, runtime: PersonHazardMonitorRuntime) -> None:
    try:
        payload = fetch_person_hazard_latest(runtime.robot_id)
    except VisionUpstreamError as exc:
        if exc.status_code == 400:
            logger.error("person hazard config error robot=%s: %s", runtime.robot_id, exc)
            return
        _record_degraded(runtime.robot_id, str(exc))
        return
    apply_person_hazard_response(conn, runtime, payload)


def poll_person_hazards_once(conn) -> int:
    if not settings.person_hazard_enabled:
        return 0
    reconcile_active_monitors(conn)
    retry_pending_estops(conn)
    polled = 0
    for runtime in list(active_monitors()):
        poll_robot_person_hazard(conn, runtime)
        polled += 1
    return polled
