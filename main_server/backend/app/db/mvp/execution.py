from __future__ import annotations

from typing import Any

from app.db.mvp.common import ACTIVE_TASK_STATUSES, DEFAULT_FLOOR, _row_ts


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


class MvpRobotRepository:
    def __init__(self, conn) -> None:
        self.conn = conn

    def list(self) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM robots ORDER BY id").fetchall()
        return [self._map(r) for r in rows]

    def list_idle(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM robots WHERE status = 'IDLE' ORDER BY id"
        ).fetchall()
        return [self._map(r) for r in rows]

    def exists(self, robot_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM robots WHERE id = %s", (robot_id,)).fetchone()
        return row is not None

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
            INSERT INTO robots (id, domain_id, status, battery_level, last_seen_at)
            VALUES (%s, %s, %s, %s, now())
            ON CONFLICT (id) DO UPDATE SET
                status = EXCLUDED.status,
                battery_level = COALESCE(EXCLUDED.battery_level, robots.battery_level),
                last_seen_at = now()
            """,
            (robot_id, int(data.get("domain_id") or 1), data.get("status", "IDLE"), data.get("battery")),
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
            "battery": int(battery) if battery is not None else None,
            "current_task_id": None,
            "last_seen_at": _row_ts(row.get("last_seen_at")),
        }

class MvpTaskRepository:
    ACTIVE = ACTIVE_TASK_STATUSES

    def __init__(self, conn) -> None:
        self.conn = conn

    def create(self, data: dict[str, Any]) -> int:
        row = self.conn.execute(
            """
            INSERT INTO tasks (
                task_type, status, priority, robot_id, item_id, quantity,
                from_location_id, from_floor, to_location_id, to_floor
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (
                data["task_type"],
                data.get("status", "QUEUED"),
                data.get("priority", 0),
                data.get("robot_id"),
                data.get("item_id"),
                data.get("quantity", 1),
                data.get("from_location_id") or data.get("from_location"),
                data.get("from_floor"),
                data.get("to_location_id") or data.get("to_location"),
                data.get("to_floor"),
            ),
        ).fetchone()
        return int(row["id"])

    def add_history(self, task_id: int, from_status: str | None, to_status: str, message: str, source: str) -> None:
        """PG MVP uses task_logs on completion; interim history is optional."""
        return

    def get(self, task_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM tasks WHERE id = %s", (task_id,)).fetchone()
        return self._map(row) if row else None

    def list(self, limit: int = 50, status: str | None = None) -> list[dict[str, Any]]:
        if status:
            rows = self.conn.execute(
                "SELECT * FROM tasks WHERE status = %s ORDER BY created_at DESC LIMIT %s",
                (status, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT %s",
                (limit,),
            ).fetchall()
        return [self._map(r) for r in rows]

    def list_assignable(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM tasks
            WHERE status IN ('CREATED', 'QUEUED') AND robot_id IS NULL
            ORDER BY priority DESC, created_at ASC
            """
        ).fetchall()
        return [self._map(r) for r in rows]

    def assign(self, task_id: int, robot_id: str, status: str = "ASSIGNED") -> None:
        self.conn.execute(
            "UPDATE tasks SET status = %s, robot_id = %s WHERE id = %s",
            (status, robot_id, task_id),
        )

    def set_priority(self, task_id: int, priority: int) -> None:
        self.conn.execute(
            "UPDATE tasks SET priority = %s WHERE id = %s",
            (priority, task_id),
        )

    def set_status(self, task_id: int, status: str, *, clear_robot: bool = False, error_reason: str | None = None) -> None:
        if status == "DONE":
            status = "COMPLETED"
        if status in {"COMPLETED"}:
            sql = "UPDATE tasks SET status = 'COMPLETED', finished_at = now(), error_reason = %s"
            if clear_robot:
                sql += ", robot_id = NULL"
            sql += " WHERE id = %s"
            self.conn.execute(sql, (error_reason, task_id))
        elif status == "RUNNING":
            self.conn.execute(
                "UPDATE tasks SET status = 'RUNNING', started_at = COALESCE(started_at, now()) WHERE id = %s",
                (task_id,),
            )
        elif status == "CANCELLED":
            sql = "UPDATE tasks SET status = 'CANCELLED', finished_at = now()"
            if clear_robot:
                sql += ", robot_id = NULL"
            sql += " WHERE id = %s"
            self.conn.execute(sql, (task_id,))
        elif status == "FAILED":
            sql = "UPDATE tasks SET status = 'FAILED', finished_at = now(), error_reason = %s"
            if clear_robot:
                sql += ", robot_id = NULL"
            sql += " WHERE id = %s"
            self.conn.execute(sql, (error_reason, task_id))
        else:
            self.conn.execute("UPDATE tasks SET status = %s WHERE id = %s", (status, task_id))

    def active_outbound_claims(
        self,
        item_id: str,
        location_id: str,
        floor: int = DEFAULT_FLOOR,
    ) -> int:
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(quantity), 0) AS claimed
            FROM tasks
            WHERE task_type = 'OUTBOUND'
              AND status = ANY(%s)
              AND item_id = %s
              AND from_location_id = %s
              AND from_floor = %s
            """,
            (list(ACTIVE_TASK_STATUSES), item_id, location_id, floor),
        ).fetchone()
        return int(row["claimed"])

    def active_inbound_claims(self, location_id: str, floor: int = DEFAULT_FLOOR) -> int:
        row = self.conn.execute(
            """
            SELECT COALESCE(SUM(quantity), 0) AS claimed
            FROM tasks
            WHERE task_type = 'INBOUND'
              AND status = ANY(%s)
              AND to_location_id = %s
              AND to_floor = %s
            """,
            (list(ACTIVE_TASK_STATUSES), location_id, floor),
        ).fetchone()
        return int(row["claimed"])

    def append_task_log(
        self,
        *,
        task_id: int,
        task_type: str,
        result: str,
        error_reason: str | None = None,
        summary: str | None = None,
        snapshot: dict[str, Any] | None = None,
    ) -> None:
        import json

        self.conn.execute(
            """
            INSERT INTO task_logs (task_id, task_type, result, error_reason, summary, snapshot_json)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            """,
            (task_id, task_type, result, error_reason, summary, json.dumps(snapshot or {})),
        )

    def _map(self, row: dict[str, Any]) -> dict[str, Any]:
        status = row["status"]
        api_status = "DONE" if status == "COMPLETED" else status
        return {
            "task_id": row["id"],
            "id": row["id"],
            "task_type": row["task_type"],
            "status": api_status,
            "db_status": status,
            "priority": row.get("priority", 0),
            "assigned_robot_id": row.get("robot_id"),
            "robot_id": row.get("robot_id"),
            "item_id": row.get("item_id"),
            "item_code": row.get("item_id"),
            "quantity": row.get("quantity", 1),
            "from_location": row.get("from_location_id"),
            "from_location_id": row.get("from_location_id"),
            "from_floor": row.get("from_floor"),
            "to_location": row.get("to_location_id"),
            "to_location_id": row.get("to_location_id"),
            "to_floor": row.get("to_floor"),
            "slot_id": row.get("to_location_id") if row.get("task_type") == "INBOUND" else row.get("from_location_id"),
            "created_at": _row_ts(row.get("created_at")),
            "preset_name": f"{row.get('task_type', '')} {row.get('item_id', '')}",
            "preset_snapshot": {},
        }
