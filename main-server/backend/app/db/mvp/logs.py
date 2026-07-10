from __future__ import annotations

from typing import Any

from app.db.mvp.common import _row_ts


class MvpTaskLogRepository:
    def __init__(self, conn) -> None:
        self.conn = conn

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM task_logs ORDER BY finished_at DESC LIMIT %s",
            (limit,),
        ).fetchall()
        return [self._map(r) for r in rows]

    def _map(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "task_id": row["task_id"],
            "task_type": row["task_type"],
            "result": row["result"],
            "result_evidence_type": row.get("result_evidence_type"),
            "started_at": _row_ts(row.get("started_at")),
            "finished_at": _row_ts(row.get("finished_at")),
            "error_reason": row.get("error_reason"),
            "summary": row.get("summary"),
            "logged_at": _row_ts(row.get("logged_at")),
        }


class MvpItemChangeLogRepository:
    def __init__(self, conn) -> None:
        self.conn = conn

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM item_change_logs ORDER BY changed_at DESC LIMIT %s",
            (limit,),
        ).fetchall()
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
                "changed_at": _row_ts(r.get("changed_at")),
            }
            for r in rows
        ]
