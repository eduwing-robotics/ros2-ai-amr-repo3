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


def latest_failure_message(conn, robot_id: str, *, within_minutes: int = 10) -> str | None:
    """해당 로봇의 최근 Movement 실패 메시지 — error 상태 보고에 원인을 붙일 때 사용.

    오래된 실패를 엉뚱한 원인으로 붙이지 않도록 최근 window 안의 실패만 본다.
    """
    row = conn.execute(
        "\n            SELECT data_json ->> 'message' AS message FROM evidence_events\n"
        "            WHERE source = 'runtime'\n"
        "              AND event_type IN ('MOVEMENT_RESULT_FAILED', 'MOVEMENT_RESULT_ABORTED', 'MOVEMENT_RESULT_REJECTED')\n"
        "              AND data_json ->> 'robot_id' = %s\n"
        "              AND observed_at > now() - make_interval(mins => %s)\n"
        "            ORDER BY observed_at DESC LIMIT 1\n            ",
        (robot_id, within_minutes),
    ).fetchone()
    message = (row or {}).get("message")
    return str(message) if message else None


def callback_event_exists(conn, event_id: str) -> bool:
    """Return whether a Movement callback event_id was already recorded."""
    row = conn.execute(
        "\n            SELECT 1 FROM evidence_events\n            WHERE source = 'runtime' AND data_json ->> 'callback_event_id' = %s\n            LIMIT 1\n            ",
        (event_id,),
    ).fetchone()
    return row is not None


def latest_estop_states(conn, robot_ids: list[str]) -> dict[str, str]:
    """Return the latest persisted ESTOP lifecycle state for each robot."""
    if not robot_ids:
        return {}
    rows = conn.execute(
        """
            SELECT DISTINCT ON (data_json ->> 'robot_id')
                   data_json ->> 'robot_id' AS robot_id, event_type
            FROM evidence_events
            WHERE source = 'runtime'
              AND data_json ->> 'robot_id' = ANY(%s)
              AND event_type IN (
                  'ROBOT_ESTOP_REQUESTED', 'ROBOT_ESTOP_CONFIRMED', 'ROBOT_ESTOP_UNCONFIRMED',
                  'ROBOT_CLEAR_ESTOP_REQUESTED', 'ROBOT_CLEAR_ESTOP_CONFIRMED',
                  'ROBOT_CLEAR_ESTOP_UNCONFIRMED'
              )
            ORDER BY data_json ->> 'robot_id', observed_at DESC, id DESC
        """,
        (robot_ids,),
    ).fetchall()
    event_to_state = {
        "ROBOT_ESTOP_REQUESTED": "stop_requested",
        "ROBOT_ESTOP_CONFIRMED": "stop_confirmed",
        "ROBOT_ESTOP_UNCONFIRMED": "stop_unconfirmed",
        "ROBOT_CLEAR_ESTOP_REQUESTED": "clear_requested",
        "ROBOT_CLEAR_ESTOP_CONFIRMED": "clear_confirmed",
        "ROBOT_CLEAR_ESTOP_UNCONFIRMED": "clear_unconfirmed",
    }
    return {
        str(row["robot_id"]): event_to_state[str(row["event_type"])]
        for row in rows
        if row.get("robot_id") and row.get("event_type") in event_to_state
    }


def list_operational_events(conn, limit: int = 50) -> list[dict[str, Any]]:

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
