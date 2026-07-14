from __future__ import annotations

import json
from typing import Any

from app.db.postgres.common import row_timestamp

ORCHESTRATION_TYPE = "ORCHESTRATION_STATE"


def append(
    conn,
    *,
    task_id: int | None = None,
    command_id: int | None = None,
    event_type: str,
    source: str = "runtime",
    confidence: float | None = None,
    severity: str | None = None,
    trusted: bool = True,
    image_url: str | None = None,
    data_json: dict[str, Any] | None = None,
) -> int:

    if severity is None:
        severity = "INFO"
    row = conn.execute(
        "\n            INSERT INTO evidence_events (\n                task_id, command_id, event_type, source, confidence, severity, trusted, image_url, data_json\n            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)\n            RETURNING id\n            ",
        (
            task_id,
            command_id,
            event_type,
            source,
            confidence,
            severity,
            trusted,
            image_url,
            json.dumps(data_json or {}),
        ),
    ).fetchone()
    return int(row["id"])


def save_orchestration(conn, task_id: int, orchestration: dict[str, Any]) -> None:
    append(conn, task_id=task_id, event_type=ORCHESTRATION_TYPE, source="orchestrator", data_json=orchestration)


def get_orchestration(conn, task_id: int) -> dict[str, Any] | None:

    row = conn.execute(
        "\n            SELECT data_json FROM evidence_events\n            WHERE task_id = %s AND event_type = %s\n            ORDER BY observed_at DESC LIMIT 1\n            ",
        (task_id, ORCHESTRATION_TYPE),
    ).fetchone()
    if not row:
        return None
    data = row.get("data_json") or {}
    if isinstance(data, str):
        data = json.loads(data)
    return data


def find_task_id_by_robot_command(conn, command_id: str) -> int | None:
    rows = conn.execute(
        "\n            SELECT task_id, data_json FROM evidence_events\n            WHERE event_type = %s\n            ORDER BY observed_at DESC\n            ",
        (ORCHESTRATION_TYPE,),
    ).fetchall()
    for row in rows:
        data = row.get("data_json") or {}
        if isinstance(data, str):
            import json

            data = json.loads(data)
        steps = data.get("steps") if isinstance(data.get("steps"), list) else data.get("legs") or []
        for step in steps:
            if str(step.get("command_id") or "") == command_id:
                return int(row["task_id"])
    return None


def list_for_task(conn, task_id: int, limit: int = 100) -> list[dict[str, Any]]:
    rows = conn.execute(
        "\n            SELECT * FROM evidence_events\n            WHERE task_id = %s AND event_type <> %s\n            ORDER BY observed_at DESC LIMIT %s\n            ",
        (task_id, ORCHESTRATION_TYPE, limit),
    ).fetchall()
    return [_map_row(conn, r) for r in rows]


def list(conn, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM evidence_events ORDER BY observed_at DESC LIMIT %s", (limit,)).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(_map_row(conn, r))
    return out


def _map_row(conn, r: dict[str, Any]) -> dict[str, Any]:

    data = r.get("data_json") or {}
    if isinstance(data, str):
        data = json.loads(data)
    return {
        "id": r["id"],
        "task_id": r.get("task_id"),
        "command_id": r.get("command_id"),
        "event_type": r["event_type"],
        "source": r["source"],
        "confidence": r.get("confidence"),
        "severity": r.get("severity"),
        "trusted": r.get("trusted"),
        "image_url": r.get("image_url"),
        "data_json": data,
        "observed_at": row_timestamp(r.get("observed_at")),
    }
