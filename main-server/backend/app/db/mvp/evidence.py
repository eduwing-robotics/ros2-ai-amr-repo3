from __future__ import annotations

from typing import Any

from app.db.mvp.common import _row_ts


class MvpEvidenceRepository:
    ORCHESTRATION_TYPE = "ORCHESTRATION_STATE"

    def __init__(self, conn) -> None:
        self.conn = conn

    def append(
        self,
        *,
        task_id: int | None = None,
        command_id: int | None = None,
        event_type: str,
        source: str = "runtime",
        confidence: float | None = None,
        severity: str | None = None,
        trusted: bool = True,
        image_url: str | None = None,
        data_json: dict[str, Any] | None = None,
    ) -> int:
        import json

        if severity is None:
            severity = "INFO"

        row = self.conn.execute(
            """
            INSERT INTO evidence_events (
                task_id, command_id, event_type, source, confidence, severity, trusted, image_url, data_json
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)
            RETURNING id
            """,
            (
                task_id,
                command_id,
                event_type,
                source,
                confidence,
                severity,
                trusted,
                image_url,
                json.dumps(data_json or {}),
            ),
        ).fetchone()
        return int(row["id"])

    def save_orchestration(self, task_id: int, orchestration: dict[str, Any]) -> None:
        self.append(
            task_id=task_id,
            event_type=self.ORCHESTRATION_TYPE,
            source="orchestrator",
            data_json=orchestration,
        )

    def get_orchestration(self, task_id: int) -> dict[str, Any] | None:
        import json

        row = self.conn.execute(
            """
            SELECT data_json FROM evidence_events
            WHERE task_id = %s AND event_type = %s
            ORDER BY id DESC LIMIT 1
            """,
            (task_id, self.ORCHESTRATION_TYPE),
        ).fetchone()
        if not row:
            return None
        data = row.get("data_json") or {}
        if isinstance(data, str):
            data = json.loads(data)
        return data

    def _acquire_task_claim_lock(self, task_id: int) -> None:
        """Serialize append-only orchestration claims for one task.

        This transaction-scoped lock is intentionally acquired in a separate
        statement before selecting the latest orchestration row. A contender
        that waited for the lock therefore starts the subsequent SELECT with a
        fresh READ COMMITTED snapshot and sees the winner's appended state.

        Terminal, dispatch, and future recovery claims share this primitive so
        they cannot independently claim stale snapshots for the same task.
        """
        self.conn.execute(
            "SELECT pg_advisory_xact_lock(%s)",
            (int(task_id),),
        ).fetchone()

    def lock_orchestration(self, task_id: int) -> dict[str, Any] | None:
        """Return the latest task orchestration while holding its transaction lock."""
        import json

        self._acquire_task_claim_lock(task_id)
        row = self.conn.execute(
            """
            SELECT id, data_json FROM evidence_events
            WHERE task_id = %s AND event_type = %s
            ORDER BY id DESC LIMIT 1 FOR UPDATE
            """,
            (task_id, self.ORCHESTRATION_TYPE),
        ).fetchone()
        if not row:
            return None
        orchestration = row.get("data_json") or {}
        if isinstance(orchestration, str):
            orchestration = json.loads(orchestration)
        return json.loads(json.dumps(orchestration))

    def claim_terminal_transition(self, task_id: int, command_id: str, event_name: str) -> dict[str, Any] | None:
        """Atomically claim the active terminal callback/poll observation.

        The row lock ends before any HTTP dispatch. A duplicate worker observes
        ``transition_claimed`` (or a later state) and returns ``None``.
        """
        orchestration = self.lock_orchestration(task_id)
        if orchestration is None:
            return None
        phase = str(orchestration.get("phase") or "")
        if phase not in {"RUNNING", "CANCEL_REQUESTED"}:
            return None
        steps = orchestration.get("steps") if isinstance(orchestration.get("steps"), list) else orchestration.get("legs") or []
        index = int(orchestration.get("step_index", orchestration.get("cursor", 0)) or 0)
        if index >= len(steps):
            return None
        step = steps[index]
        valid_statuses = {"dispatched", "RUNNING"}
        if phase == "CANCEL_REQUESTED":
            valid_statuses.add("dispatching")
        if str(step.get("command_id") or "") != str(command_id) or step.get("status") not in valid_statuses:
            return None
        transition_id = f"{task_id}:{index}:{command_id}:{event_name}"
        step["status"] = "transition_claimed"
        step["transition_id"] = transition_id
        orchestration["phase"] = "ADVANCING"
        orchestration["steps"] = steps
        orchestration["legs"] = steps
        self.save_orchestration(task_id, orchestration)
        # Short transaction boundary: never hold a DB lock across Movement HTTP.
        self.conn.commit()
        return orchestration

    def finalize_terminal_transition(
        self,
        task_id: int,
        transition_id: str,
        orchestration: dict[str, Any],
    ) -> bool:
        """Persist a claimed callback transition only if its short CAS still wins."""
        current = self.lock_orchestration(task_id)
        if current is None or str(current.get("phase") or "") != "ADVANCING":
            self.conn.rollback()
            return False
        steps = current.get("steps") if isinstance(current.get("steps"), list) else current.get("legs") or []
        index = int(current.get("step_index", current.get("cursor", 0)) or 0)
        if index >= len(steps):
            self.conn.rollback()
            return False
        step = steps[index]
        if (
            str(step.get("status") or "") != "transition_claimed"
            or str(step.get("transition_id") or "") != transition_id
        ):
            self.conn.rollback()
            return False
        self.save_orchestration(task_id, orchestration)
        return True

    def claim_recovery_terminal_transition(
        self, task_id: int, command_id: str, event_name: str
    ) -> dict[str, Any] | None:
        """Lock and validate one terminal recovery command observation.

        Callback delivery and the recovery poller can observe the same terminal
        state.  The caller keeps this transaction-scoped task lock until it
        persists the final ``AWAITING_OPERATOR`` state, so there is no durable
        intermediate claim that could strand the task after a process crash.
        """
        orchestration = self.lock_orchestration(task_id)
        if orchestration is None:
            return None
        recovery = dict(orchestration.get("recovery") or {})
        if (
            str(orchestration.get("phase") or "") != "RECOVERY_RUNNING"
            or str(recovery.get("active_command_id") or "") != str(command_id)
        ):
            return None
        transition_id = f"{task_id}:recovery:{command_id}:{event_name}"
        recovery["terminal_transition_id"] = transition_id
        recovery["terminal_event"] = event_name
        orchestration["recovery"] = recovery
        return orchestration

    def lock_recovery_command(
        self,
        task_id: int,
        command_id: str,
    ) -> dict[str, Any] | None:
        """Lock and return the current recovery command until caller commit/rollback."""
        orchestration = self.lock_orchestration(task_id)
        if orchestration is None:
            return None
        recovery = orchestration.get("recovery") or {}
        if (
            str(orchestration.get("phase") or "") != "RECOVERY_RUNNING"
            or str(recovery.get("active_command_id") or "") != str(command_id)
        ):
            return None
        return orchestration

    def claim_step_dispatch(self, task_id: int, step_index: int, command_id: str) -> dict[str, Any] | None:
        """Persist the outgoing command identity before sending it to Movement."""
        import json

        self._acquire_task_claim_lock(task_id)
        row = self.conn.execute(
            """
            SELECT id, data_json FROM evidence_events
            WHERE task_id = %s AND event_type = %s
            ORDER BY id DESC LIMIT 1 FOR UPDATE
            """,
            (task_id, self.ORCHESTRATION_TYPE),
        ).fetchone()
        if not row:
            return None
        orchestration = row.get("data_json") or {}
        if isinstance(orchestration, str):
            orchestration = json.loads(orchestration)
        orchestration = json.loads(json.dumps(orchestration))
        if str(orchestration.get("phase") or "") != "RUNNING":
            return None
        steps = orchestration.get("steps") if isinstance(orchestration.get("steps"), list) else orchestration.get("legs") or []
        index = int(orchestration.get("step_index", orchestration.get("cursor", 0)) or 0)
        if index != step_index or index >= len(steps):
            return None
        step = steps[index]
        status = str(step.get("status") or "pending")
        if status == "dispatched":
            return None
        if status not in {"pending", "dispatching"}:
            return None
        existing = step.get("command_id")
        if existing and str(existing) != command_id:
            return None
        step["command_id"] = command_id
        step["status"] = "dispatching"
        orchestration["steps"] = steps
        orchestration["legs"] = steps
        self.save_orchestration(task_id, orchestration)
        self.conn.commit()
        return orchestration

    def find_task_id_by_leg_command(self, command_id: str) -> int | None:
        rows = self.conn.execute(
            """
            SELECT task_id, data_json FROM evidence_events
            WHERE event_type = %s
            ORDER BY observed_at DESC
            """,
            (self.ORCHESTRATION_TYPE,),
        ).fetchall()
        for row in rows:
            data = row.get("data_json") or {}
            if isinstance(data, str):
                import json
                data = json.loads(data)
            steps = data.get("steps") if isinstance(data.get("steps"), list) else data.get("legs") or []
            for leg in steps:
                if str(leg.get("command_id") or "") == command_id:
                    return int(row["task_id"])
        return None

    def list_for_task(self, task_id: int, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM evidence_events
            WHERE task_id = %s AND event_type <> %s
            ORDER BY observed_at DESC LIMIT %s
            """,
            (task_id, self.ORCHESTRATION_TYPE, limit),
        ).fetchall()
        return [self._map_row(r) for r in rows]

    def list(self, limit: int = 50) -> list[dict[str, Any]]:

        rows = self.conn.execute(
            "SELECT * FROM evidence_events ORDER BY observed_at DESC LIMIT %s",
            (limit,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            out.append(self._map_row(r))
        return out

    def _map_row(self, r: dict[str, Any]) -> dict[str, Any]:
        import json

        data = r.get("data_json") or {}
        if isinstance(data, str):
            data = json.loads(data)
        return {
            "id": r["id"],
            "task_id": r.get("task_id"),
            "command_id": r.get("command_id"),
            "event_type": r["event_type"],
            "source": r["source"],
            "confidence": r.get("confidence"),
            "severity": r.get("severity"),
            "trusted": r.get("trusted"),
            "image_url": r.get("image_url"),
            "data_json": data,
            "observed_at": _row_ts(r.get("observed_at")),
        }


class MvpEventRepository:
    """Audit timeline — backed by evidence_events (PHASE_66-A)."""

    def __init__(self, conn) -> None:
        self.conn = conn

    def append(
        self,
        event_type: str,
        message: str = "",
        *,
        task_id: int | None = None,
        robot_id: str | None = None,
        command_id: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> None:
        data = dict(payload or {})
        if message:
            data["message"] = message
        if robot_id:
            data["robot_id"] = robot_id
        if command_id:
            data["movement_command_id"] = command_id
        MvpEvidenceRepository(self.conn).append(
            task_id=task_id,
            event_type=event_type,
            source="runtime",
            data_json=data,
        )

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        import json

        rows = self.conn.execute(
            """
            SELECT * FROM evidence_events
            WHERE source = 'runtime'
            ORDER BY observed_at DESC LIMIT %s
            """,
            (limit,),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for r in rows:
            data = r.get("data_json") or {}
            if isinstance(data, str):
                data = json.loads(data)
            out.append({
                "event_id": r["id"],
                "event_type": r["event_type"],
                "task_id": r.get("task_id"),
                "robot_id": data.get("robot_id"),
                "command_id": data.get("movement_command_id"),
                "message": data.get("message", ""),
                "payload_json": data,
                "created_at": _row_ts(r.get("observed_at")),
            })
        return out


class MvpMovementCommandRepository:
    """Movement command timeline — backed by evidence_events (PHASE_66-B)."""

    def __init__(self, conn) -> None:
        self.conn = conn

    def create(
        self,
        *,
        command_id: str,
        robot_id: str,
        command_type: str,
        command: str,
        status: str,
        request_payload: dict[str, Any] | None = None,
        response_payload: dict[str, Any] | None = None,
        task_id: int | None = None,
    ) -> None:
        MvpEvidenceRepository(self.conn).append(
            task_id=task_id,
            event_type=command_type or command,
            source="movement",
            data_json={
                "command_id": command_id,
                "robot_id": robot_id,
                "command": command,
                "status": status,
                "request": request_payload or {},
                "response": response_payload or {},
            },
        )

    def record_result(
        self,
        command_id: str,
        result: str,
        message: str = "",
        payload: dict[str, Any] | None = None,
    ) -> None:
        MvpEvidenceRepository(self.conn).append(
            event_type="MOVEMENT_RESULT",
            source="movement",
            data_json={
                "command_id": command_id,
                "result": result,
                "message": message,
                "result_payload": payload or {},
            },
        )

    def list(self, limit: int = 50) -> list[dict[str, Any]]:
        from app.services import evidence_runtime

        return evidence_runtime.derived_movement_commands(self.conn, limit=limit)
