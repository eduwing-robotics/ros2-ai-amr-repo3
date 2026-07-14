from __future__ import annotations

from typing import Any


def exists(conn, item_id: str) -> bool:
    row = conn.execute("SELECT 1 FROM items WHERE id = %s", (item_id,)).fetchone()
    return row is not None


def list_items(conn) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT id, name FROM items ORDER BY id").fetchall()
    return [{"item_code": r["id"], "item_name": r["name"], "unit": "ea"} for r in rows]


def upsert(conn, data: dict[str, Any]) -> None:
    item_id = data.get("item_code") or data["id"]
    name = data.get("item_name") or data.get("name") or item_id
    conn.execute(
        "\n            INSERT INTO items (id, name) VALUES (%s, %s)\n            ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name\n            ",
        (item_id, name),
    )


def delete_item(conn, item_id: str) -> bool:
    cur = conn.execute("DELETE FROM items WHERE id = %s", (item_id,))
    return cur.rowcount > 0
