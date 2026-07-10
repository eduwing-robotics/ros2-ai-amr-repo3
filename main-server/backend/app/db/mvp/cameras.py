from __future__ import annotations

from typing import Any


class MvpCameraRepository:
    def __init__(self, conn) -> None:
        self.conn = conn

    def list(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT source_id, label, robot_id, status, stream_url FROM cameras ORDER BY source_id"
        ).fetchall()
        return [dict(r) for r in rows]

    def upsert(self, data: dict[str, Any]) -> None:
        self.conn.execute(
            """
            INSERT INTO cameras (source_id, label, robot_id, status, stream_url)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (source_id) DO UPDATE SET
                label = EXCLUDED.label,
                robot_id = EXCLUDED.robot_id,
                status = EXCLUDED.status,
                stream_url = EXCLUDED.stream_url
            """,
            (
                data["source_id"],
                data.get("label") or data["source_id"],
                data.get("robot_id"),
                data.get("status", "not_connected"),
                data.get("stream_url"),
            ),
        )

    def delete(self, source_id: str) -> bool:
        cur = self.conn.execute("DELETE FROM cameras WHERE source_id = %s", (source_id,))
        return cur.rowcount > 0
