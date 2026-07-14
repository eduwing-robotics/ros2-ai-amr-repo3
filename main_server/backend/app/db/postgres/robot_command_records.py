from __future__ import annotations

from typing import Any

from app.db.postgres import runtime_records


def create_robot_command_record(
    conn,
    *,
    command_id: str,
    robot_id: str,
    command_type: str,
    command: str,
    status: str,
    request_payload: dict[str, Any] | None = None,
    response_payload: dict[str, Any] | None = None,
    task_id: int | None = None,
) -> None:
    runtime_records.append(
        conn,
        task_id=task_id,
        event_type=command_type or command,
        source="movement",
        data_json={
            "command_id": command_id,
            "robot_id": robot_id,
            "command": command,
            "status": status,
            "request": request_payload or {},
            "response": response_payload or {},
        },
    )


def record_result(conn, command_id: str, result: str, message: str = "", payload: dict[str, Any] | None = None) -> None:
    runtime_records.append(
        conn,
        event_type="MOVEMENT_RESULT",
        source="movement",
        data_json={"command_id": command_id, "result": result, "message": message, "result_payload": payload or {}},
    )
