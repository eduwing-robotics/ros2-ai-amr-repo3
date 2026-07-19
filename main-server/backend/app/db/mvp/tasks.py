from __future__ import annotations

from typing import Any

from app.db.mvp.common import ACTIVE_TASK_STATUSES, DEFAULT_FLOOR, _row_ts


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

    def lock_work_order_resource(self, operation: str, item_id: str, location_id: str, floor: int) -> None:
        """Serialize creation of a durable INBOUND/OUTBOUND task claim.

        The lock lasts for the caller's database transaction.  INBOUND claims
        own a slot/floor, while OUTBOUND claims own the inventory item at a
        slot/floor; terminal task statuses release both claims naturally.
        """
        resource = (
            f"work-order:inbound:{location_id}:{floor}"
            if operation == "inbound"
            else f"work-order:outbound:{item_id}:{location_id}:{floor}"
        )
        self.conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            (resource,),
        ).fetchone()

    def add_history(self, task_id: int, from_status: str | None, to_status: str, message: str, source: str) -> None:
        """PG MVP uses task_logs on completion; interim history is optional."""
        return

    def get(self, task_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM tasks WHERE id = %s", (task_id,)).fetchone()
        return self._map(row) if row else None

    def lock_for_completion(self, task_id: int) -> dict[str, Any] | None:
        """Serialize orchestration claims and terminal inventory application."""
        self.conn.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            (int(task_id),),
        ).fetchone()
        row = self.conn.execute(
            "SELECT * FROM tasks WHERE id = %s FOR UPDATE",
            (task_id,),
        ).fetchone()
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

    def claim_assignment(self, task_id: int, robot_id: str) -> dict[str, Any] | None:
        """Atomically claim one assignable task and one idle robot.

        Manual assignment and the background auto-assigner can contend for the
        same resources. Lock both logical resources in stable order before
        locking their rows, then make conditional updates the final ownership
        check. ``None`` means another transaction won the claim.
        """
        resources = sorted((f"task-assignment:robot:{robot_id}", f"task-assignment:task:{task_id}"))
        for resource in resources:
            self.conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (resource,),
            ).fetchone()

        task = self.conn.execute("SELECT * FROM tasks WHERE id = %s FOR UPDATE", (task_id,)).fetchone()
        robot = self.conn.execute("SELECT * FROM robots WHERE id = %s FOR UPDATE", (robot_id,)).fetchone()
        if not task or not robot:
            return None
        if (
            task["status"] not in {"CREATED", "QUEUED"}
            or task.get("robot_id")
            or robot["status"] != "IDLE"
            or not robot.get("enabled", True)
        ):
            return None

        claimed_robot = self.conn.execute(
            """
            UPDATE robots
            SET status = 'ASSIGNED', last_seen_at = now()
            WHERE id = %s AND status = 'IDLE' AND enabled = TRUE
            RETURNING id
            """,
            (robot_id,),
        ).fetchone()
        if not claimed_robot:
            return None

        claimed_task = self.conn.execute(
            """
            UPDATE tasks
            SET status = 'ASSIGNED', robot_id = %s
            WHERE id = %s
              AND status IN ('CREATED', 'QUEUED')
              AND robot_id IS NULL
            RETURNING *
            """,
            (robot_id, task_id),
        ).fetchone()
        if not claimed_task:
            raise RuntimeError("assignment task claim lost after robot claim")
        return self._map(claimed_task)

    def prepare_chained_assignment(
        self,
        current_task_id: int,
        next_task_id: int,
        robot_id: str,
    ) -> dict[str, Any] | None:
        """Lock one possible hand-off without violating one-live-task-per-robot.

        PostgreSQL's partial unique index rejects even a temporary second live
        task for the same robot.  This first phase therefore only locks and
        validates the current task, candidate task and robot.  The caller must
        finish the current task and call ``claim_chained_assignment`` in the
        same transaction.
        """
        resources = sorted(
            (
                f"task-assignment:robot:{robot_id}",
                f"task-assignment:task:{current_task_id}",
                f"task-assignment:task:{next_task_id}",
            )
        )
        for resource in resources:
            self.conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (resource,),
            ).fetchone()

        current = self.conn.execute(
            "SELECT * FROM tasks WHERE id = %s FOR UPDATE",
            (current_task_id,),
        ).fetchone()
        next_task = self.conn.execute(
            "SELECT * FROM tasks WHERE id = %s FOR UPDATE",
            (next_task_id,),
        ).fetchone()
        robot = self.conn.execute(
            "SELECT * FROM robots WHERE id = %s FOR UPDATE",
            (robot_id,),
        ).fetchone()
        if not current or not next_task or not robot:
            return None
        if (
            current.get("robot_id") != robot_id
            or current.get("status") != "RUNNING"
            or next_task.get("status") not in {"CREATED", "QUEUED"}
            or next_task.get("robot_id")
            or robot.get("status") != "RUNNING"
            or not robot.get("enabled", True)
        ):
            return None

        return self._map(next_task)

    def claim_chained_assignment(
        self,
        current_task_id: int,
        next_task_id: int,
        robot_id: str,
    ) -> dict[str, Any] | None:
        """Assign a prepared hand-off after the current task is terminal.

        Reacquiring the same advisory locks is harmless in one transaction and
        also makes this method fail closed if it is called without preparation.
        The completed task no longer participates in ``uq_tasks_active_robot``,
        so the next task can be assigned without weakening that invariant.
        """
        resources = sorted(
            (
                f"task-assignment:robot:{robot_id}",
                f"task-assignment:task:{current_task_id}",
                f"task-assignment:task:{next_task_id}",
            )
        )
        for resource in resources:
            self.conn.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (resource,),
            ).fetchone()

        current = self.conn.execute(
            "SELECT * FROM tasks WHERE id = %s FOR UPDATE",
            (current_task_id,),
        ).fetchone()
        next_task = self.conn.execute(
            "SELECT * FROM tasks WHERE id = %s FOR UPDATE",
            (next_task_id,),
        ).fetchone()
        robot = self.conn.execute(
            "SELECT * FROM robots WHERE id = %s FOR UPDATE",
            (robot_id,),
        ).fetchone()
        if not current or not next_task or not robot:
            return None
        if (
            current.get("robot_id") != robot_id
            or current.get("status") != "COMPLETED"
            or next_task.get("status") not in {"CREATED", "QUEUED"}
            or next_task.get("robot_id")
            or robot.get("status") != "IDLE"
            or not robot.get("enabled", True)
        ):
            return None

        claimed_robot = self.conn.execute(
            """
            UPDATE robots
            SET status = 'ASSIGNED', last_seen_at = now()
            WHERE id = %s AND status = 'IDLE' AND enabled = TRUE
            RETURNING id
            """,
            (robot_id,),
        ).fetchone()
        if not claimed_robot:
            return None

        claimed = self.conn.execute(
            """
            UPDATE tasks
            SET status = 'ASSIGNED', robot_id = %s
            WHERE id = %s
              AND status IN ('CREATED', 'QUEUED')
              AND robot_id IS NULL
            RETURNING *
            """,
            (robot_id, next_task_id),
        ).fetchone()
        if not claimed:
            raise RuntimeError("chained task claim lost after robot claim")
        return self._map(claimed)

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
