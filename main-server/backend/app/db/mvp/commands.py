from __future__ import annotations

from typing import Any

from app.db.mvp.evidence import MvpEvidenceRepository


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
