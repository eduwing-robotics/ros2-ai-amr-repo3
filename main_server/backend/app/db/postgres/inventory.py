from __future__ import annotations

from typing import Any

from app.db.postgres.common import DEFAULT_FLOOR, row_timestamp


def list_inventory(
    conn, slot_id: str | None = None, item_code: str | None = None, floor: int | None = None
) -> list[dict[str, Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if slot_id:
        clauses.append("location_id = %s")
        params.append(slot_id)
    if item_code:
        clauses.append("item_id = %s")
        params.append(item_code)
    if floor is not None:
        clauses.append("floor = %s")
        params.append(floor)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT item_id, location_id, floor, quantity, updated_at FROM inventory {where} ORDER BY location_id, floor, item_id",
        tuple(params),
    ).fetchall()
    return [
        {
            "slot_id": r["location_id"],
            "location_id": r["location_id"],
            "item_code": r["item_id"],
            "item_id": r["item_id"],
            "floor": r["floor"],
            "quantity": r["quantity"],
            "updated_at": row_timestamp(r.get("updated_at")),
        }
        for r in rows
    ]


def get_quantity(conn, location_id: str, item_id: str, floor: int = DEFAULT_FLOOR) -> int:
    row = conn.execute(
        "SELECT quantity FROM inventory WHERE location_id = %s AND item_id = %s AND floor = %s",
        (location_id, item_id, floor),
    ).fetchone()
    return int(row["quantity"]) if row else 0


def location_total(conn, location_id: str, floor: int = DEFAULT_FLOOR) -> int:
    row = conn.execute(
        "SELECT COALESCE(SUM(quantity), 0) AS total FROM inventory WHERE location_id = %s AND floor = %s",
        (location_id, floor),
    ).fetchone()
    return int(row["total"])


def adjust(conn, location_id: str, item_id: str, delta: int, floor: int = DEFAULT_FLOOR) -> int:
    row = conn.execute(
        "\n            SELECT quantity FROM inventory\n            WHERE location_id = %s AND item_id = %s AND floor = %s\n            FOR UPDATE\n            ",
        (location_id, item_id, floor),
    ).fetchone()
    before = int(row["quantity"]) if row else 0
    after = before + delta
    if after < 0:
        raise ValueError("insufficient_inventory")
    if row:
        conn.execute(
            "UPDATE inventory SET quantity = %s, updated_at = now() WHERE location_id = %s AND item_id = %s AND floor = %s",
            (after, location_id, item_id, floor),
        )
    else:
        if after == 0:
            return 0
        conn.execute(
            "INSERT INTO inventory (item_id, location_id, floor, quantity) VALUES (%s, %s, %s, %s)",
            (item_id, location_id, floor, after),
        )
    return after


def upsert(conn, data: dict[str, Any]) -> None:
    location_id = data.get("slot_id") or data["location_id"]
    item_id = data.get("item_code") or data["item_id"]
    floor = int(data.get("floor") or DEFAULT_FLOOR)
    quantity = int(data["quantity"])
    conn.execute(
        "\n            INSERT INTO inventory (item_id, location_id, floor, quantity)\n            VALUES (%s, %s, %s, %s)\n            ON CONFLICT (item_id, location_id, floor) DO UPDATE SET\n                quantity = EXCLUDED.quantity, updated_at = now()\n            ",
        (item_id, location_id, floor, quantity),
    )


def append_change_log(
    conn,
    *,
    task_id: int | None,
    item_id: str,
    location_id: str | None,
    floor: int | None,
    event_type: str,
    quantity_change: int,
    quantity_before: int | None,
    quantity_after: int | None,
    reason: str | None = None,
) -> None:
    conn.execute(
        "\n            INSERT INTO item_change_logs (\n                task_id, item_id, location_id, floor, event_type,\n                quantity_change, quantity_before, quantity_after, reason\n            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)\n            ",
        (task_id, item_id, location_id, floor, event_type, quantity_change, quantity_before, quantity_after, reason),
    )


def has_task_event(conn, task_id: int, event_type: str) -> bool:
    """Return whether this task already applied the given inventory transition."""
    row = conn.execute(
        "\n            SELECT 1 FROM item_change_logs\n            WHERE task_id = %s AND event_type = %s\n            LIMIT 1\n            ",
        (task_id, event_type),
    ).fetchone()
    return row is not None
