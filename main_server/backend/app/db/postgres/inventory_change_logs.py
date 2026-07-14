from __future__ import annotations

from typing import Any

from app.db.postgres.common import row_timestamp


def list(conn, limit: int = 50) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM item_change_logs ORDER BY changed_at DESC LIMIT %s", (limit,)).fetchall()
    return [
        {
            "id": r["id"],
            "task_id": r.get("task_id"),
            "item_id": r["item_id"],
            "item_code": r["item_id"],
            "location_id": r.get("location_id"),
            "slot_id": r.get("location_id"),
            "floor": r.get("floor"),
            "event_type": r["event_type"],
            "quantity_change": r["quantity_change"],
            "quantity_before": r.get("quantity_before"),
            "quantity_after": r.get("quantity_after"),
            "reason": r.get("reason"),
            "changed_at": row_timestamp(r.get("changed_at")),
        }
        for r in rows
    ]
