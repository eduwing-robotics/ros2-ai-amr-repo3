from __future__ import annotations

from typing import Any

from app.db.postgres.common import row_timestamp


def list(conn, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM task_logs ORDER BY finished_at DESC LIMIT %s", (limit,)).fetchall()
    return [_map(conn, r) for r in rows]


def _map(conn, row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "task_id": row["task_id"],
        "task_type": row["task_type"],
        "result": row["result"],
        "result_evidence_type": row.get("result_evidence_type"),
        "started_at": row_timestamp(row.get("started_at")),
        "finished_at": row_timestamp(row.get("finished_at")),
        "error_reason": row.get("error_reason"),
        "summary": row.get("summary"),
        "logged_at": row_timestamp(row.get("logged_at")),
    }
