"""Movement callback ingestion and fleet estop helpers."""

from __future__ import annotations

import logging
from typing import Any

from app.db.repo_bridge import event_repo, evidence_repo, movement_repo, robot_repo, safety_stop_repo, task_repo
from app.services import orchestration_state as orch_state
from app.services import orchestrator as orchestrator_service
from app.services.health_cache import clear_cache
from app.services.movement import (
    MovementClientError,
    movement_client,
    robot_emergency_state,
    set_robot_emergency,
)
from app.services.movement_health import get_movement_health

logger = logging.getLogger(__name__)


def _callback_event_id(payload: dict[str, Any], channel: str) -> str:
    explicit = str(payload.get("event_id") or "").strip()
    if explicit:
        return explicit
    command_id = str(payload.get("command_id") or "").strip()
    state = str(payload.get("result") or payload.get("event") or payload.get("state") or "").strip()
    reported_at = str(payload.get("reported_at") or "").strip()
    if command_id and state and reported_at:
        return f"movement:{channel}:{command_id}:{state.upper()}:{reported_at}"
    return ""


def _prepare_callback(conn, payload: dict[str, Any], channel: str) -> tuple[dict[str, Any], bool]:
    prepared = dict(payload)
    event_id = _callback_event_id(prepared, channel)
    if not event_id:
        return prepared, False
    prepared["event_id"] = event_id
    if getattr(conn, "is_postgres", False) is True:
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (f"movement-callback:{event_id}",),
        ).fetchone()
    duplicate = event_repo(conn).callback_event_exists(event_id) is True
    return prepared, duplicate


def _event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    stored = dict(payload)
    if payload.get("event_id"):
        stored["callback_event_id"] = payload["event_id"]
    return stored


def _resolved_task_id(conn, payload: dict[str, Any]) -> int | None:
    value = payload.get("task_id")
    command_id = payload.get("command_id")
    if value is None and command_id:
        value = evidence_repo(conn).find_task_id_by_leg_command(str(command_id))
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _rollback_best_effort(conn) -> None:
    try:
        conn.rollback()
    except Exception:
        logger.exception("failed to roll back after fleet E-stop database error")


def _record_fleet_estop_result(conn, events, **event: Any) -> None:
    """Keep an audit write failure from blocking later physical E-stops."""
    try:
        events.append(**event)
        conn.commit()
    except Exception:
        _rollback_best_effort(conn)
        logger.exception("failed to record fleet E-stop result")


def ingest_command_event(conn, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist Movement command callback and advance orchestration when applicable."""
    payload, duplicate = _prepare_callback(conn, payload, "event")
    if duplicate:
        return {"message": "duplicate movement callback ignored", "duplicate": True, "task_advanced": False}
    command_id = payload.get("command_id")
    robot_id = payload.get("robot_name") or payload.get("robot_id")
    event = payload.get("event") or payload.get("state") or "UNKNOWN"
    task_id = _resolved_task_id(conn, payload)
    event_repo(conn).append(
        event_type=f"MOVEMENT_COMMAND_{event}",
        task_id=task_id,
        robot_id=robot_id,
        command_id=command_id,
        message=payload.get("message") or str(event),
        payload=_event_payload(payload),
    )
    advanced = False
    if _matches_active_orchestration(conn, payload):
        advanced = orchestrator_service.handle_command_event(conn, payload) is not None
    return {"message": "movement command event saved", "duplicate": False, "task_advanced": advanced}


def _matches_active_orchestration(conn, payload: dict[str, Any]) -> bool:
    """Only a callback for the active task command and assigned robot may advance state.

    Unknown/non-orchestrated commands remain auditable but do not cause a state
    transition; terminal duplicates are therefore naturally idempotent.
    """
    command_id = payload.get("command_id")
    if not command_id:
        return False
    task_id = _resolved_task_id(conn, payload)
    if task_id is None:
        return False
    task = task_repo(conn).get(task_id)
    if not task:
        return False
    expected_robot = str(task.get("assigned_robot_id") or task.get("robot_id") or "")
    reported_robot = str(payload.get("robot_name") or payload.get("robot_id") or "")
    if not expected_robot or reported_robot != expected_robot:
        return False
    orch = (task.get("preset_snapshot") or {}).get("_orchestration") or evidence_repo(conn).get_orchestration(task_id) or {}
    recovery = orch.get("recovery") or {}
    phase = orch_state.normalize_phase(orch.get("phase"))
    if (
        phase == orch_state.PHASE_RECOVERY_RUNNING
        and str(recovery.get("active_command_id") or "") == str(command_id)
    ):
        return True
    steps = orch.get("steps") if isinstance(orch.get("steps"), list) else orch.get("legs") or []
    stop_request = orch.get("stop_request") or {}
    active_statuses = {"dispatched"}
    if (
        phase == orch_state.PHASE_CANCEL_REQUESTED
        and str(stop_request.get("command_id") or "") == str(command_id)
    ):
        active_statuses.add("dispatching")
    active = next(
        (
            step
            for step in steps
            if str(step.get("command_id") or "") == str(command_id)
            and step.get("status") in active_statuses
        ),
        None,
    )
    return active is not None


def ingest_result(conn, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist Movement result callback and update movement command record."""
    payload, duplicate = _prepare_callback(conn, payload, "result")
    if duplicate:
        return {"message": "duplicate movement result ignored", "duplicate": True}
    command_id = payload.get("command_id")
    robot_id = payload.get("robot_name") or payload.get("robot_id")
    result = payload.get("result") or "UNKNOWN"
    task_id = _resolved_task_id(conn, payload)
    event_repo(conn).append(
        event_type=f"MOVEMENT_RESULT_{result}",
        task_id=task_id,
        robot_id=robot_id,
        command_id=command_id,
        message=payload.get("message") or str(result),
        payload=_event_payload(payload),
    )
    if command_id:
        movement_repo(conn).record_result(
            command_id,
            str(result),
            payload.get("message") or str(result),
            payload,
        )
    return {"message": "movement result saved", "duplicate": False}


def robot_status_requires_event(payload: dict[str, Any]) -> bool:
    state = str(payload.get("state") or "").strip().lower()
    return payload.get("localized") is False or state in {
        "error",
        "fault",
        "failed",
        "offline",
        "disconnected",
        "estop",
        "emergency",
    }


def ingest_robot_status(conn, robot_name: str, payload: dict[str, Any]) -> None:
    """Persist only issue/status events; realtime pose has one canonical route."""
    event_repo(conn).append(
        event_type="MOVEMENT_ROBOT_STATUS",
        robot_id=robot_name,
        command_id=payload.get("current_command_id"),
        message=payload.get("state") or "status",
        payload=payload,
    )


def estop_all_robots(conn) -> list[dict[str, Any]]:
    """Request estop for every registered robot and record outcomes."""
    from app.services.person_hazard import mark_running_tasks_needs_attention, on_robot_task_terminal

    robots = robot_repo(conn).list()
    hold_error: Exception | None = None
    try:
        mark_running_tasks_needs_attention(conn, reason="operator_estop")
        # Make every task hold durable and release transaction-scoped task
        # locks before the first remote E-stop request.
        conn.commit()
    except Exception as exc:
        hold_error = exc
        _rollback_best_effort(conn)
    events = event_repo(conn)
    results: list[dict[str, Any]] = []
    stopped_robot_ids: list[str] = []
    for robot in robots:
        robot_id = robot["robot_id"]
        try:
            payload = movement_client.estop(robot_id)
            if not isinstance(payload, dict):
                raise ValueError(
                    f"invalid estop response: expected object, got {type(payload).__name__}"
                )
        except Exception as exc:
            set_robot_emergency(robot_id, None)
            error = str(exc)
            results.append({"robot_id": robot_id, "ok": False, "attempted": True, "state": "unknown", "error": error})
            _record_fleet_estop_result(
                conn,
                events,
                event_type="ROBOT_ESTOP_UNKNOWN",
                robot_id=robot_id,
                message=f"estop unconfirmed: {robot_id}",
                payload={"robot_id": robot_id, "state": "unknown", "error": error},
            )
        else:
            set_robot_emergency(robot_id, True)
            stopped_robot_ids.append(str(robot_id))
            results.append({"robot_id": robot_id, "ok": True, "attempted": True, "state": "active", "response": payload})
            _record_fleet_estop_result(
                conn,
                events,
                event_type="ROBOT_ESTOP",
                robot_id=robot_id,
                message=f"estop: {robot_id}",
                payload=payload,
            )
    # Remote monitor cleanup is lower priority than physical stop and runs only
    # after every task hold is committed and all fleet E-stop calls finish.
    for robot_id in stopped_robot_ids:
        try:
            on_robot_task_terminal(robot_id, conn=conn)
        except Exception:
            _rollback_best_effort(conn)
            logger.exception("failed to close person monitor after fleet E-stop robot=%s", robot_id)
    clear_cache()
    if hold_error is not None:
        raise hold_error
    return results


def clear_estop_all_robots(conn) -> list[dict[str, Any]]:
    """Clear estop for every registered robot and record outcomes.

    Active DB safety stops are closed only after every robot clear succeeds. A
    partial clear failure keeps OPEN/HOLDING stops active so recovery cannot be
    mistaken for a globally safe state.
    """
    robot_rows = robot_repo(conn).list()
    robot_ids = [row["robot_id"] for row in robot_rows]
    health = get_movement_health(robot_ids, force=True)
    results: list[dict[str, Any]] = []
    events = event_repo(conn)
    for robot in robot_rows:
        robot_id = robot["robot_id"]
        snapshot = health.get(robot_id) or {}
        snapshot_state = str(snapshot.get("estop_state") or "").strip().lower()
        if snapshot.get("is_emergency") is True or snapshot_state == "active":
            set_robot_emergency(robot_id, True)
        elif snapshot_state == "unknown" and robot_emergency_state(robot_id) is not True:
            set_robot_emergency(robot_id, None)
        online = bool(snapshot.get("ok")) and snapshot.get("robot_online") is not False
        if not online:
            if robot_emergency_state(robot_id) is not True:
                set_robot_emergency(robot_id, None)
            results.append(
                {
                    "robot_id": robot_id,
                    "ok": False,
                    "attempted": False,
                    "state": "unknown",
                    "error": "robot offline; estop clear unconfirmed",
                }
            )
            continue
        try:
            payload = movement_client.clear_estop(robot_id)
            set_robot_emergency(robot_id, False)
            results.append({"robot_id": robot_id, "ok": True, "attempted": True, "state": "cleared", "response": payload})
            events.append(
                event_type="ROBOT_CLEAR_ESTOP",
                robot_id=robot_id,
                message=f"clear estop: {robot_id}",
                payload=payload,
            )
        except MovementClientError as exc:
            if robot_emergency_state(robot_id) is not True:
                set_robot_emergency(robot_id, None)
            results.append({"robot_id": robot_id, "ok": False, "attempted": True, "state": "unknown", "error": str(exc)})

    if results and all(row.get("state") == "cleared" for row in results):
        stops = safety_stop_repo(conn)
        active = stops.list_active()
        stop_ids = [int(row["id"]) for row in active if str(row.get("status") or "") in {"OPEN", "HOLDING"}]
        for stop_id in stop_ids:
            stops.close(stop_id)
        if stop_ids:
            events.append(
                event_type="SAFETY_STOPS_CLOSED",
                message="all robot estops cleared; active safety stops closed",
                payload={"stop_ids": stop_ids},
            )
    clear_cache()
    return results


def clear_estop_robot(conn, robot_id: str) -> dict[str, Any]:
    """Clear one confirmed E-stop without touching unrelated unknown robots."""
    if not robot_repo(conn).exists(robot_id):
        return {
            "robot_id": robot_id,
            "ok": False,
            "attempted": False,
            "state": "unknown",
            "error": "robot not found",
        }

    snapshot = get_movement_health([robot_id], force=True).get(robot_id) or {}
    snapshot_state = str(snapshot.get("estop_state") or "").strip().lower()
    if snapshot.get("is_emergency") is True or snapshot_state == "active":
        set_robot_emergency(robot_id, True)
    elif snapshot_state == "unknown" and robot_emergency_state(robot_id) is not True:
        set_robot_emergency(robot_id, None)

    online = bool(snapshot.get("ok")) and snapshot.get("robot_online") is not False
    if not online:
        if robot_emergency_state(robot_id) is not True:
            set_robot_emergency(robot_id, None)
        clear_cache()
        return {
            "robot_id": robot_id,
            "ok": False,
            "attempted": False,
            "state": "unknown",
            "error": "robot offline; estop clear unconfirmed",
        }

    events = event_repo(conn)
    try:
        payload = movement_client.clear_estop(robot_id)
    except MovementClientError as exc:
        if robot_emergency_state(robot_id) is not True:
            set_robot_emergency(robot_id, None)
        clear_cache()
        return {
            "robot_id": robot_id,
            "ok": False,
            "attempted": True,
            "state": "unknown",
            "error": str(exc),
        }

    set_robot_emergency(robot_id, False)
    events.append(
        event_type="ROBOT_CLEAR_ESTOP",
        robot_id=robot_id,
        message=f"clear estop: {robot_id}",
        payload=payload,
    )
    stop_ids = safety_stop_repo(conn).close_for_robot(robot_id)
    if stop_ids:
        events.append(
            event_type="SAFETY_STOPS_CLOSED",
            robot_id=robot_id,
            message=f"robot estop cleared; safety stops closed: {robot_id}",
            payload={"robot_id": robot_id, "stop_ids": stop_ids},
        )
    clear_cache()
    return {
        "robot_id": robot_id,
        "ok": True,
        "attempted": True,
        "state": "cleared",
        "response": payload,
    }
