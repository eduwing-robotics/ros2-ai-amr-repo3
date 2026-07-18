from __future__ import annotations

import json
from typing import Any

from app.db.postgres.common import ACTIVE_TASK_STATUSES, DEFAULT_FLOOR, row_timestamp


def create_task_record(conn, data: dict[str, Any]) -> int:
    row = conn.execute(
        "\n            INSERT INTO tasks (\n                task_type, status, priority, robot_id, item_id, quantity,\n                from_location_id, from_floor, to_location_id, to_floor\n            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)\n            RETURNING id\n            ",
        (
            data["task_type"],
            data.get("status", "QUEUED"),
            data.get("priority", 0),
            data.get("robot_id"),
            data.get("item_id"),
            data.get("quantity", 1),
            data.get("from_location_id") or data.get("from_location"),
            data.get("from_floor"),
            data.get("to_location_id") or data.get("to_location"),
            data.get("to_floor"),
        ),
    ).fetchone()
    return int(row["id"])


def add_history(conn, task_id: int, from_status: str | None, to_status: str, message: str, source: str) -> None:
    """PG MVP uses task_logs on completion; interim history is optional."""
    return


def get_task(conn, task_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM tasks WHERE id = %s", (task_id,)).fetchone()
    return _map(conn, row) if row else None


def list_tasks(conn, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
    if status:
        rows = conn.execute(
            "SELECT * FROM tasks WHERE status = %s ORDER BY created_at DESC LIMIT %s", (status, limit)
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC LIMIT %s", (limit,)).fetchall()
    return [_map(conn, r) for r in rows]


def list_assignable(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        "\n            SELECT * FROM tasks\n            WHERE status IN ('CREATED', 'QUEUED') AND robot_id IS NULL\n            ORDER BY priority DESC, created_at ASC\n            "
    ).fetchall()
    return [_map(conn, r) for r in rows]


def assign(conn, task_id: int, robot_id: str, status: str = "ASSIGNED") -> None:
    conn.execute("UPDATE tasks SET status = %s, robot_id = %s WHERE id = %s", (status, robot_id, task_id))


def unassign_to_queue(conn, task_id: int) -> None:
    """Release a deferred assignment without failing the queued task."""
    conn.execute("UPDATE tasks SET status = 'QUEUED', robot_id = NULL WHERE id = %s", (task_id,))


def set_priority(conn, task_id: int, priority: int) -> None:
    conn.execute("UPDATE tasks SET priority = %s WHERE id = %s", (priority, task_id))


def set_status(conn, task_id: int, status: str, *, clear_robot: bool = False, error_reason: str | None = None) -> None:
    if status == "DONE":
        status = "COMPLETED"
    if status in {"COMPLETED"}:
        sql = "UPDATE tasks SET status = 'COMPLETED', finished_at = now(), error_reason = %s"
        if clear_robot:
            sql += ", robot_id = NULL"
        sql += " WHERE id = %s"
        conn.execute(sql, (error_reason, task_id))
    elif status == "RUNNING":
        conn.execute(
            "UPDATE tasks SET status = 'RUNNING', started_at = COALESCE(started_at, now()) WHERE id = %s", (task_id,)
        )
    elif status == "CANCELLED":
        sql = "UPDATE tasks SET status = 'CANCELLED', finished_at = now()"
        if clear_robot:
            sql += ", robot_id = NULL"
        sql += " WHERE id = %s"
        conn.execute(sql, (task_id,))
    elif status == "FAILED":
        sql = "UPDATE tasks SET status = 'FAILED', finished_at = now(), error_reason = %s"
        if clear_robot:
            sql += ", robot_id = NULL"
        sql += " WHERE id = %s"
        conn.execute(sql, (error_reason, task_id))
    else:
        conn.execute("UPDATE tasks SET status = %s WHERE id = %s", (status, task_id))


def active_outbound_claims(conn, item_id: str, location_id: str, floor: int = DEFAULT_FLOOR) -> int:
    row = conn.execute(
        "\n            SELECT COALESCE(SUM(quantity), 0) AS claimed\n            FROM tasks\n            WHERE task_type = 'OUTBOUND'\n              AND status = ANY(%s)\n              AND item_id = %s\n              AND from_location_id = %s\n              AND from_floor = %s\n            ",
        (list(ACTIVE_TASK_STATUSES), item_id, location_id, floor),
    ).fetchone()
    return int(row["claimed"])


def active_inbound_claims(conn, location_id: str, floor: int = DEFAULT_FLOOR) -> int:
    row = conn.execute(
        "\n            SELECT COALESCE(SUM(quantity), 0) AS claimed\n            FROM tasks\n            WHERE task_type = 'INBOUND'\n              AND status = ANY(%s)\n              AND to_location_id = %s\n              AND to_floor = %s\n            ",
        (list(ACTIVE_TASK_STATUSES), location_id, floor),
    ).fetchone()
    return int(row["claimed"])


def append_task_log(
    conn,
    *,
    task_id: int,
    task_type: str,
    result: str,
    error_reason: str | None = None,
    summary: str | None = None,
    snapshot: dict[str, Any] | None = None,
) -> None:

    conn.execute(
        "\n            INSERT INTO task_logs (task_id, task_type, result, error_reason, summary, snapshot_json)\n            VALUES (%s, %s, %s, %s, %s, %s::jsonb)\n            ",
        (task_id, task_type, result, error_reason, summary, json.dumps(snapshot or {})),
    )


def _map(conn, row: dict[str, Any]) -> dict[str, Any]:
    status = row["status"]
    api_status = "DONE" if status == "COMPLETED" else status
    return {
        "task_id": row["id"],
        "id": row["id"],
        "task_type": row["task_type"],
        "status": api_status,
        "db_status": status,
        "priority": row.get("priority", 0),
        "assigned_robot_id": row.get("robot_id"),
        "robot_id": row.get("robot_id"),
        "item_id": row.get("item_id"),
        "item_code": row.get("item_id"),
        "quantity": row.get("quantity", 1),
        "from_location": row.get("from_location_id"),
        "from_location_id": row.get("from_location_id"),
        "from_floor": row.get("from_floor"),
        "to_location": row.get("to_location_id"),
        "to_location_id": row.get("to_location_id"),
        "to_floor": row.get("to_floor"),
        "slot_id": row.get("to_location_id") if row.get("task_type") == "INBOUND" else row.get("from_location_id"),
        "created_at": row_timestamp(row.get("created_at")),
        "preset_name": f"{row.get('task_type', '')} {row.get('item_id', '')}",
        "preset_snapshot": {},
    }
