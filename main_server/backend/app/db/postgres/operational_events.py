from __future__ import annotations

import json
from typing import Any

from app.db.postgres import runtime_records
from app.db.postgres.common import row_timestamp


def append(
    conn,
    event_type: str,
    message: str = "",
    *,
    task_id: int | None = None,
    robot_id: str | None = None,
    command_id: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    data = dict(payload or {})
    if message:
        data["message"] = message
    if robot_id:
        data["robot_id"] = robot_id
    if command_id:
        data["movement_command_id"] = command_id
    runtime_records.append(conn, task_id=task_id, event_type=event_type, source="runtime", data_json=data)


def callback_event_exists(conn, event_id: str) -> bool:
    """Return whether a Movement callback event_id was already recorded."""
    row = conn.execute(
        "\n            SELECT 1 FROM evidence_events\n            WHERE source = 'runtime' AND data_json ->> 'callback_event_id' = %s\n            LIMIT 1\n            ",
        (event_id,),
    ).fetchone()
    return row is not None


def list(conn, limit: int = 50) -> list[dict[str, Any]]:

    rows = conn.execute(
        "\n            SELECT * FROM evidence_events\n            WHERE source = 'runtime'\n            ORDER BY observed_at DESC LIMIT %s\n            ",
        (limit,),
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        data = r.get("data_json") or {}
        if isinstance(data, str):
            data = json.loads(data)
        out.append(
            {
                "event_id": r["id"],
                "event_type": r["event_type"],
                "task_id": r.get("task_id"),
                "robot_id": data.get("robot_id"),
                "command_id": data.get("movement_command_id"),
                "message": data.get("message", ""),
                "payload_json": data,
                "created_at": row_timestamp(r.get("observed_at")),
            }
        )
    return out
