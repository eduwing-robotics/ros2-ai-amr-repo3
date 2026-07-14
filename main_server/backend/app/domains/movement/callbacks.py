"""Movement callback application coordinator."""

from __future__ import annotations

from typing import Any

from app.db.postgres import operational_events, robot_command_records
from app.domains.execution import orchestrator
from app.domains.movement.navigation import report_pose_for_robot
from app.models.robots import RobotPoseUpdate

RESULT_EVENT_MAP = {
    "OK": "DONE",
    "SUCCESS": "DONE",
    "SUCCEEDED": "DONE",
    "COMPLETED": "DONE",
    "CANCELED": "CANCELED",
    "CANCELLED": "CANCELLED",
    "STOPPED": "STOPPED",
    "ABORTED": "ABORTED",
    "FAILED": "FAILED",
    "REJECTED": "REJECTED",
}


def _is_duplicate_callback(conn, payload: dict[str, Any]) -> bool:
    event_id = str(payload.get("event_id") or "")
    return bool(event_id and operational_events.callback_event_exists(conn, event_id))


def _event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    if payload.get("event_id"):
        out["callback_event_id"] = payload["event_id"]
    return out


def ingest_command_event(conn, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist a command callback and advance Execution when applicable."""
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
        message=payload.get("message") or str(event),
        payload=_event_payload(payload),
    )
    advanced = orchestrator.handle_command_event(conn, payload) is not None
    return {"message": "movement command event saved", "duplicate": False, "task_advanced": advanced}


def ingest_result(conn, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist a result callback and update its command record and Execution."""
    if _is_duplicate_callback(conn, payload):
        return {"message": "duplicate movement result ignored", "duplicate": True, "task_advanced": False}
    command_id = payload.get("command_id")
    robot_id = payload.get("robot_name") or payload.get("robot_id")
    result = str(payload.get("result") or "UNKNOWN").upper()
    operational_events.append(
        conn,
        event_type=f"MOVEMENT_RESULT_{result}",
        robot_id=robot_id,
        command_id=command_id,
        message=payload.get("message") or str(result),
        payload=_event_payload(payload),
    )
    if not command_id:
        return {"message": "movement result saved without command", "duplicate": False, "task_advanced": False}
    robot_command_records.record_result(
        conn,
        command_id,
        str(result),
        payload.get("message") or str(result),
        payload,
    )
    normalized = {**payload, "event": RESULT_EVENT_MAP.get(result, result)}
    advanced = orchestrator.handle_command_event(conn, normalized) is not None
    return {"message": "movement result saved", "duplicate": False, "task_advanced": advanced}


def ingest_robot_status(conn, robot_name: str, payload: dict[str, Any]) -> None:
    """Apply a Movement robot status callback to pose and the event timeline."""
    pose = payload.get("pose") or {}
    if pose and payload.get("localized", True):
        update = RobotPoseUpdate(
            map_id=pose.get("frame_id") or "map",
            x=pose["x"],
            y=pose["y"],
            yaw=pose.get("yaw", 0.0),
            source=pose.get("source") or "movement_status",
            reported_at=pose.get("reported_at") or payload.get("reported_at"),
        )
        report_pose_for_robot(conn, robot_name, update, source=update.source)
    message = str(payload.get("state") or "status")
    if message.lower() == "error":
        # 상태 하트비트의 "error"만으로는 원인을 알 수 없다 — 직전 실패 메시지를 붙여 준다.
        cause = operational_events.latest_failure_message(conn, robot_name)
        if cause:
            message = f"error — 직전 실패: {cause}"
    operational_events.append(
        conn,
        event_type="MOVEMENT_ROBOT_STATUS",
        robot_id=robot_name,
        command_id=payload.get("current_command_id"),
        message=message,
        payload=payload,
    )
