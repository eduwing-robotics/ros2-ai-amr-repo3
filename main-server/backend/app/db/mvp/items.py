from __future__ import annotations

from typing import Any


class MvpItemRepository:
    def __init__(self, conn) -> None:
        self.conn = conn

    def exists(self, item_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM items WHERE id = %s", (item_id,)).fetchone()
        return row is not None

    def get(self, item_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT id, name, unit, aruco_marker_id FROM items WHERE id = %s",
            (item_id,),
        ).fetchone()
        return self._map(row) if row else None

    def list(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT id, name, unit, aruco_marker_id FROM items ORDER BY id"
        ).fetchall()
        return [self._map(row) for row in rows]

    def upsert(self, data: dict[str, Any]) -> None:
        item_id = data.get("item_code") or data["id"]
        name = data.get("item_name") or data.get("name") or item_id
        unit = str(data.get("unit") or "EA").strip().upper()
        marker_id = data.get("aruco_marker_id")
        self.conn.execute(
            """
            INSERT INTO items (id, name, unit, aruco_marker_id) VALUES (%s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                unit = EXCLUDED.unit,
                aruco_marker_id = EXCLUDED.aruco_marker_id
            """,
            (item_id, name, unit, marker_id),
        )

    def delete(self, item_id: str) -> bool:
        cur = self.conn.execute("DELETE FROM items WHERE id = %s", (item_id,))
        return cur.rowcount > 0

    @staticmethod
    def _map(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "item_code": row["id"],
            "item_name": row["name"],
            "unit": row.get("unit") or "EA",
            "aruco_marker_id": row.get("aruco_marker_id"),
        }
