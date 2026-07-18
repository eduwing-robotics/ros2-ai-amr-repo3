"""책임: Movement callback의 인증 후 멱등 적용과 runtime pose 반영을 조정한다.
비책임: Movement 상태 생성과 로봇 물리 제어."""

from __future__ import annotations

import zlib
from typing import Any

from app.core.config import settings
from app.db.connection import MOVEMENT_CALLBACK_LOCK_NAMESPACE, advisory_xact_lock_for_key
from app.db.postgres import operational_events
from app.domains.execution import orchestrator
from app.domains.movement.pose_runtime import pose_runtime


def _callback_event_id(payload: dict[str, Any], channel: str) -> str:
    event_id = str(payload.get("event_id") or "")
    if event_id:
        return event_id
    command_id = str(payload.get("command_id") or "")
    state = str(payload.get("result") or payload.get("event") or payload.get("state") or "")
    reported_at = str(payload.get("reported_at") or "")
    if command_id and state and reported_at:
        return f"movement:{channel}:{command_id}:{state.upper()}:{reported_at}"
    return ""


def _with_callback_event_id(payload: dict[str, Any], channel: str) -> dict[str, Any]:
    out = dict(payload)
    event_id = _callback_event_id(payload, channel)
    if event_id:
        out["event_id"] = event_id
    return out


def _is_duplicate_callback(conn, payload: dict[str, Any]) -> bool:
    event_id = str(payload.get("event_id") or "")
    return bool(event_id and operational_events.callback_event_exists(conn, event_id))


def _lock_callback_event(conn, payload: dict[str, Any]) -> None:
    event_id = str(payload.get("event_id") or "")
    if not event_id:
        return
    key = zlib.crc32(event_id.encode("utf-8"))
    if key >= 2**31:
        key -= 2**32
    advisory_xact_lock_for_key(conn, MOVEMENT_CALLBACK_LOCK_NAMESPACE, key)


def _event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    if payload.get("event_id"):
        out["callback_event_id"] = payload["event_id"]
    return out


def ingest_command_event(conn, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist a command callback and advance Execution when applicable."""
    payload = _with_callback_event_id(payload, "event")
    _lock_callback_event(conn, payload)
    if _is_duplicate_callback(conn, payload):
        return {"message": "duplicate movement callback ignored", "duplicate": True, "task_advanced": False}
    command_id = payload.get("command_id")
    robot_id = payload.get("robot_name") or payload.get("robot_id")
    event = payload.get("event") or payload.get("state") or "UNKNOWN"
    operational_events.append(
        conn,
        event_type=f"MOVEMENT_COMMAND_{event}",
        robot_id=robot_id,
        command_id=command_id,
        task_id=payload.get("task_id"),
        message=payload.get("message") or str(event),
        payload=_event_payload(payload),
    )
    advanced = orchestrator.handle_command_event(conn, payload) is not None
    return {"message": "movement command event saved", "duplicate": False, "task_advanced": advanced}


def ingest_robot_status_pose(robot_name: str, payload: dict[str, Any]) -> bool:
    """상태 콜백의 pose를 DB 없이 실시간 메모리에 즉시 반영한다."""
    pose = payload.get("pose") or {}
    if not pose:
        localized = payload.get("localized")
        return pose_runtime.update_localization(robot_name, localized) if localized is not None else False
    update = {
        "map_id": pose.get("frame_id") or "map",
        "x": pose["x"],
        "y": pose["y"],
        "yaw": pose.get("yaw", 0.0),
        "linear_velocity": pose.get("linear_velocity"),
        "angular_velocity": pose.get("angular_velocity"),
        "source": pose.get("source") or "movement_status",
        "command_id": payload.get("current_command_id"),
        "reported_at": pose.get("reported_at") or payload.get("reported_at"),
        "source_age_sec": pose.get("age_sec"),
    }
    return pose_runtime.ingest(
        robot_name,
        update,
        source_kind="status",
        localized=payload.get("localized"),
    )


def robot_status_is_fresh(payload: dict[str, Any]) -> bool:
    """True only for a live robot heartbeat or a fresh pose sample."""
    state = str(payload.get("state") or "").strip().lower()
    if state in {"offline", "disconnected", "error", "fault", "failed"}:
        return False
    if payload.get("robot_online") is False:
        return False
    pose = payload.get("pose") or {}
    if pose:
        try:
            age = float(pose.get("age_sec"))
        except (TypeError, ValueError):
            return False
        return age <= settings.pose_source_lost_sec and payload.get("localized") is not False
    return payload.get("robot_online") is True


def robot_status_requires_event(payload: dict[str, Any]) -> bool:
    """정상 heartbeat는 버리고 운영자가 확인할 이상 상태만 DB에 남긴다."""
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


def ingest_robot_status(conn, robot_name: str, payload: dict[str, Any]) -> bool:
    """이상 상태 콜백만 운영 이벤트 타임라인에 기록한다."""
    if not operational_events.should_append_robot_status_issue(conn, robot_name, payload):
        return False
    message = str(payload.get("state") or "status issue")
    if message.lower() == "error":
        cause = operational_events.latest_failure_message(conn, robot_name)
        if cause:
            message = f"error — 직전 실패: {cause}"
    operational_events.append(
        conn,
        event_type="MOVEMENT_ROBOT_STATUS_ISSUE",
        robot_id=robot_name,
        command_id=payload.get("current_command_id"),
        message=message,
        payload=payload,
    )
    return True


def ingest_estop_status(conn, robot_name: str, payload: dict[str, Any]) -> bool:
    """Reconcile Main's safety latch from an explicit Movement status callback."""
    if "is_emergency" not in payload:
        return False
    from app.domains.movement.client import set_robot_emergency

    active = bool(payload["is_emergency"])
    set_robot_emergency(robot_name, active)
    expected = "stop_confirmed" if active else "clear_confirmed"
    if operational_events.latest_estop_states(conn, [robot_name]).get(robot_name) == expected:
        return False
    operational_events.append(
        conn,
        event_type="ROBOT_ESTOP_CONFIRMED" if active else "ROBOT_CLEAR_ESTOP_CONFIRMED",
        robot_id=robot_name,
        message=("estop confirmed" if active else "estop clear confirmed") + f": {robot_name}",
        payload=payload,
    )
    return True
