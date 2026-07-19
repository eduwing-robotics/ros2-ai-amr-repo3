"""책임: 검증·멱등 처리된 Movement command callback의 증거 기록과 Task 반영 순서를 소유한다.
비책임: callback 인증·중복 lock, 상태 전이 규칙과 물리 제어."""

from __future__ import annotations

from typing import Any

from app.db.postgres import operational_events
from app.domains.execution import orchestrator


def apply_command_event(conn, payload: dict[str, Any]) -> bool:
    """callback 증거를 저장한 뒤 일치하는 Task에 반영하고 실제 진행 여부를 반환한다."""
    command_id = payload.get("command_id")
    robot_id = payload.get("robot_name") or payload.get("robot_id")
    event = payload.get("event") or payload.get("state") or "UNKNOWN"
    event_payload = dict(payload)
    if payload.get("event_id"):
        event_payload["callback_event_id"] = payload["event_id"]
    operational_events.append(
        conn,
        event_type=f"MOVEMENT_COMMAND_{event}",
        robot_id=robot_id,
        command_id=command_id,
        task_id=payload.get("task_id"),
        message=payload.get("message") or str(event),
        payload=event_payload,
    )
    return orchestrator.handle_command_event(conn, payload) is not None
