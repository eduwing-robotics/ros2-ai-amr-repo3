from __future__ import annotations

from typing import Any


class MvpItemRepository:
    def __init__(self, conn) -> None:
        self.conn = conn

    def exists(self, item_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM items WHERE id = %s", (item_id,)).fetchone()
        return row is not None

    def list(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT id, name FROM items ORDER BY id").fetchall()
        return [{"item_code": r["id"], "item_name": r["name"], "unit": "ea"} for r in rows]

    def upsert(self, data: dict[str, Any]) -> None:
        item_id = data.get("item_code") or data["id"]
        name = data.get("item_name") or data.get("name") or item_id
        self.conn.execute(
            """
            INSERT INTO items (id, name) VALUES (%s, %s)
            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name
            """,
            (item_id, name),
        )

    def delete(self, item_id: str) -> bool:
        cur = self.conn.execute("DELETE FROM items WHERE id = %s", (item_id,))
        return cur.rowcount > 0
