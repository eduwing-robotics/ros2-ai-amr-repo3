from __future__ import annotations

from typing import Any

from app.db.mvp.common import DEFAULT_FLOOR, _row_ts


class MvpInventoryRepository:
    def __init__(self, conn) -> None:
        self.conn = conn

    def list(self, slot_id: str | None = None, item_code: str | None = None, floor: int | None = None) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if slot_id:
            clauses.append("inv.location_id = %s")
            params.append(slot_id)
        if item_code:
            clauses.append("inv.item_id = %s")
            params.append(item_code)
        if floor is not None:
            clauses.append("inv.floor = %s")
            params.append(floor)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT inv.item_id, inv.location_id, inv.floor, inv.quantity, inv.updated_at,
                   item.name AS item_name, item.unit, item.aruco_marker_id
            FROM inventory AS inv
            JOIN items AS item ON item.id = inv.item_id
            {where}
            ORDER BY inv.location_id, inv.floor, inv.item_id
            """,
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
                "item_name": r.get("item_name"),
                "unit": r.get("unit") or "EA",
                "aruco_marker_id": r.get("aruco_marker_id"),
                "updated_at": _row_ts(r.get("updated_at")),
            }
            for r in rows
        ]

    def get_quantity(self, location_id: str, item_id: str, floor: int = DEFAULT_FLOOR) -> int:
        row = self.conn.execute(
            "SELECT quantity FROM inventory WHERE location_id = %s AND item_id = %s AND floor = %s",
            (location_id, item_id, floor),
        ).fetchone()
        return int(row["quantity"]) if row else 0

    def location_total(self, location_id: str, floor: int = DEFAULT_FLOOR) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(quantity), 0) AS total FROM inventory WHERE location_id = %s AND floor = %s",
            (location_id, floor),
        ).fetchone()
        return int(row["total"])

    def adjust(self, location_id: str, item_id: str, delta: int, floor: int = DEFAULT_FLOOR) -> int:
        row = self.conn.execute(
            """
            SELECT quantity FROM inventory
            WHERE location_id = %s AND item_id = %s AND floor = %s
            FOR UPDATE
            """,
            (location_id, item_id, floor),
        ).fetchone()
        before = int(row["quantity"]) if row else 0
        after = before + delta
        if after < 0:
            raise ValueError("insufficient_inventory")
        if row:
            self.conn.execute(
                "UPDATE inventory SET quantity = %s, updated_at = now() WHERE location_id = %s AND item_id = %s AND floor = %s",
                (after, location_id, item_id, floor),
            )
        else:
            if after == 0:
                return 0
            self.conn.execute(
                "INSERT INTO inventory (item_id, location_id, floor, quantity) VALUES (%s, %s, %s, %s)",
                (item_id, location_id, floor, after),
            )
        return after

    def upsert(self, data: dict[str, Any]) -> None:
        location_id = data.get("slot_id") or data["location_id"]
        item_id = data.get("item_code") or data["item_id"]
        floor = int(data.get("floor") or DEFAULT_FLOOR)
        quantity = int(data["quantity"])
        self.conn.execute(
            """
            INSERT INTO inventory (item_id, location_id, floor, quantity)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (item_id, location_id, floor) DO UPDATE SET
                quantity = EXCLUDED.quantity, updated_at = now()
            """,
            (item_id, location_id, floor, quantity),
        )

    def append_change_log(
        self,
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
        self.conn.execute(
            """
            INSERT INTO item_change_logs (
                task_id, item_id, location_id, floor, event_type,
                quantity_change, quantity_before, quantity_after, reason
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (task_id, item_id, location_id, floor, event_type, quantity_change, quantity_before, quantity_after, reason),
        )
