from __future__ import annotations

from typing import Any

from app.db.mvp.common import _row_ts


class MvpRobotRepository:
    def __init__(self, conn) -> None:
        self.conn = conn

    def list(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM robots ORDER BY id").fetchall()
        return [self._map(r) for r in rows]

    def list_idle(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM robots WHERE status = 'IDLE' AND enabled = TRUE ORDER BY id"
        ).fetchall()
        return [self._map(r) for r in rows]

    def exists(self, robot_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM robots WHERE id = %s", (robot_id,)).fetchone()
        return row is not None

    def get(self, robot_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM robots WHERE id = %s", (robot_id,)).fetchone()
        return self._map(row) if row else None

    def disable_block_reason(self, robot_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT status FROM tasks WHERE robot_id = %s AND status IN ('ASSIGNED', 'RUNNING') LIMIT 1",
            (robot_id,),
        ).fetchone()
        return "robot_has_active_task" if row else None

    def set_task(self, robot_id: str, status: str, task_id: int | None) -> None:
        self.conn.execute(
            "UPDATE robots SET status = %s, last_seen_at = now() WHERE id = %s",
            (status, robot_id),
        )

    def touch(self, robot_id: str) -> None:
        self.conn.execute(
            "UPDATE robots SET last_seen_at = now() WHERE id = %s",
            (robot_id,),
        )

    def set_battery(self, robot_id: str, level: int) -> None:
        """배터리 잔량만 갱신한다(status는 건드리지 않음). movement /health 수신 값 반영용."""
        self.conn.execute(
            "UPDATE robots SET battery_level = %s, last_seen_at = now() WHERE id = %s",
            (int(level), robot_id),
        )

    def upsert(self, data: dict[str, Any]) -> None:
        robot_id = data["robot_id"]
        self.conn.execute(
            """
            INSERT INTO robots (id, domain_id, status, enabled, battery_level, last_seen_at)
            VALUES (%s, %s, %s, COALESCE(%s, TRUE), %s, now())
            ON CONFLICT (id) DO UPDATE SET
                status = EXCLUDED.status,
                enabled = COALESCE(%s, robots.enabled),
                battery_level = COALESCE(EXCLUDED.battery_level, robots.battery_level),
                last_seen_at = now()
            """,
            (
                robot_id,
                int(data.get("domain_id") or 1),
                data.get("status", "IDLE"),
                data.get("enabled"),
                data.get("battery"),
                data.get("enabled"),
            ),
        )

    def delete(self, robot_id: str) -> bool:
        cur = self.conn.execute("DELETE FROM robots WHERE id = %s", (robot_id,))
        return cur.rowcount > 0

    def update_last_command(self, robot_id: str, command_id: str, status: str) -> None:
        self.conn.execute(
            "UPDATE robots SET status = %s, last_seen_at = now() WHERE id = %s",
            (status, robot_id),
        )

    def _map(self, row: dict[str, Any]) -> dict[str, Any]:
        battery = row.get("battery_level")
        return {
            "robot_id": row["id"],
            "display_name": row["id"],
            "status": row.get("status", "IDLE"),
            "enabled": bool(row.get("enabled", True)),
            "battery": int(battery) if battery is not None else None,
            "current_task_id": None,
            "last_seen_at": _row_ts(row.get("last_seen_at")),
        }
