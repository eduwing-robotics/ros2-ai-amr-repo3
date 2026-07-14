from __future__ import annotations

from typing import Any


def list_cameras(conn) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT source_id, label, robot_id, status, stream_url FROM cameras ORDER BY source_id"
    ).fetchall()
    return [dict(r) for r in rows]


def upsert(conn, data: dict[str, Any]) -> None:
    conn.execute(
        "\n            INSERT INTO cameras (source_id, label, robot_id, status, stream_url)\n            VALUES (%s, %s, %s, %s, %s)\n            ON CONFLICT (source_id) DO UPDATE SET\n                label = EXCLUDED.label,\n                robot_id = EXCLUDED.robot_id,\n                status = EXCLUDED.status,\n                stream_url = EXCLUDED.stream_url\n            ",
        (
            data["source_id"],
            data.get("label") or data["source_id"],
            data.get("robot_id"),
            data.get("status", "not_connected"),
            data.get("stream_url"),
        ),
    )


def delete_camera(conn, source_id: str) -> bool:
    cur = conn.execute("DELETE FROM cameras WHERE source_id = %s", (source_id,))
    return cur.rowcount > 0
