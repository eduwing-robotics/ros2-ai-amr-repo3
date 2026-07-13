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
            ORDER BY observed_at DESC LIMIT 1
            """,
            (task_id, self.ORCHESTRATION_TYPE),
        ).fetchone()
        if not row:
            return None
        data = row.get("data_json") or {}
        if isinstance(data, str):
            data = json.loads(data)
        return data

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
    """Audit timeline — backed by evidence_events."""

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
    """Movement command timeline — backed by evidence_events."""

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
        from app.domains.execution import evidence as evidence_runtime

        return evidence_runtime.derived_movement_commands(self.conn, limit=limit)


class MvpCommandRepository:
    def __init__(self, conn) -> None:
        self.conn = conn

    def list_for_task_type(self, task_type: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM commands
            WHERE task_type = %s AND is_active = true
            ORDER BY sequence_no
            """,
            (task_type,),
        ).fetchall()
        return [dict(r) for r in rows]

    def get(self, command_id: int) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM commands WHERE id = %s", (command_id,)).fetchone()
        return dict(row) if row else None

    def resolve_for_leg(self, task_type: str, sequence_no: int, command_type: str | None = None) -> int | None:
        for cmd in self.list_for_task_type(task_type):
            if int(cmd["sequence_no"]) != sequence_no:
                continue
            if command_type is None or cmd["command_type"] == command_type:
                return int(cmd["id"])
        return None

    def progress_for_task(self, task_id: int, task_type: str) -> list[dict[str, Any]]:
        """Derive command progress from static definitions + evidence."""

        defs = self.list_for_task_type(task_type)
        evidence_rows = self.conn.execute(
            """
            SELECT command_id, event_type, trusted, severity, observed_at
            FROM evidence_events
            WHERE task_id = %s AND event_type <> %s
            ORDER BY observed_at
            """,
            (task_id, MvpEvidenceRepository.ORCHESTRATION_TYPE),
        ).fetchall()
        evidence_by_cmd: dict[int, list[dict[str, Any]]] = {}
        for ev in evidence_rows:
            cid = ev.get("command_id")
            if cid is None:
                continue
            evidence_by_cmd.setdefault(int(cid), []).append(dict(ev))
        out: list[dict[str, Any]] = []
        for cmd in defs:
            cid = int(cmd["id"])
            evs = evidence_by_cmd.get(cid, [])
            latest = evs[-1]["event_type"] if evs else "PENDING"
            satisfied = any(
                e["event_type"] == cmd["required_evidence_type"] and e.get("trusted", True)
                for e in evs
            )
            out.append({
                "command_id": cid,
                "sequence_no": cmd["sequence_no"],
                "command_type": cmd["command_type"],
                "target_system": cmd["target_system"],
                "required_evidence_type": cmd["required_evidence_type"],
                "status": "DONE" if satisfied else latest,
                "evidence_count": len(evs),
            })
        return out


class MvpSafetyStopRepository:
    def __init__(self, conn) -> None:
        self.conn = conn

    def open_from_evidence(self, evidence_id: int, hold_until=None) -> int:
        row = self.conn.execute(
            """
            INSERT INTO safety_stops (detected_evidence_id, status, hold_until)
            VALUES (%s, 'OPEN', %s)
            RETURNING id
            """,
            (evidence_id, hold_until),
        ).fetchone()
        return int(row["id"])

    def list_active(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT * FROM safety_stops
            WHERE status IN ('OPEN', 'HOLDING')
            ORDER BY opened_at DESC
            """
        ).fetchall()
        return [dict(r) for r in rows]

    def close(self, stop_id: int) -> None:
        self.conn.execute(
            "UPDATE safety_stops SET status = 'CLOSED', closed_at = now() WHERE id = %s",
            (stop_id,),
        )

    def promote_holding(self, stop_id: int) -> None:
        self.conn.execute(
            "UPDATE safety_stops SET status = 'HOLDING' WHERE id = %s AND status = 'OPEN'",
            (stop_id,),
        )


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
