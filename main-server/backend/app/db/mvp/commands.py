from __future__ import annotations

import json
from typing import Any

from app.db.mvp.common import _row_ts
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
            SELECT command_id, event_type, trusted, severity, data_json, observed_at
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
            mapped = dict(ev)
            data = mapped.get("data_json") or {}
            if isinstance(data, str):
                data = json.loads(data)
            mapped["data_json"] = data
            evidence_by_cmd.setdefault(int(cid), []).append(mapped)
        out: list[dict[str, Any]] = []
        for cmd in defs:
            cid = int(cmd["id"])
            evs = evidence_by_cmd.get(cid, [])
            latest = evs[-1]["event_type"] if evs else "PENDING"
            latest_data = (evs[-1].get("data_json") or {}) if evs else {}
            gate_approved = any(
                e["event_type"] == "LIFT_LOAD_GATE_DECISION"
                and e.get("trusted") is True
                and (e.get("data_json") or {}).get("approved") is True
                for e in evs
            )
            satisfied = any(
                e["event_type"] == cmd["required_evidence_type"] and e.get("trusted", True)
                for e in evs
            ) or gate_approved
            if satisfied:
                status = "DONE"
            elif latest == "LIFT_LOAD_GATE_DECISION":
                status = "HOLD"
            else:
                status = latest
            template = cmd.get("request_template_json") or {}
            if isinstance(template, str):
                template = json.loads(template)
            runtime_command_id = latest_data.get("movement_command_id") or latest_data.get("runtime_command_id")
            mode = str(template.get("mode") or "")
            out.append({
                "command_id": cid,
                "command_def_id": cid,
                "sequence_no": cmd["sequence_no"],
                "command_type": cmd["command_type"],
                "target_system": cmd["target_system"],
                "required_evidence_type": cmd["required_evidence_type"],
                "status": status,
                "evidence_count": len(evs),
                "runtime_command_id": runtime_command_id,
                "target": template.get("target"),
                "transfer_action": "load" if mode.endswith("load") else "unload" if mode.endswith("unload") else None,
                "human_hazard_monitor": bool(template.get("human_hazard_monitor")),
                "last_observed_at": _row_ts(evs[-1].get("observed_at")) if evs else None,
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

    def close_for_robot(self, robot_id: str) -> list[int]:
        rows = self.conn.execute(
            """
            UPDATE safety_stops AS stop
            SET status = 'CLOSED', closed_at = now()
            FROM evidence_events AS evidence
            WHERE stop.detected_evidence_id = evidence.id
              AND stop.status IN ('OPEN', 'HOLDING')
              AND evidence.data_json ->> 'robot_id' = %s
            RETURNING stop.id
            """,
            (robot_id,),
        ).fetchall()
        return [int(row["id"]) for row in rows]

    def promote_holding(self, stop_id: int) -> None:
        self.conn.execute(
            "UPDATE safety_stops SET status = 'HOLDING' WHERE id = %s AND status = 'OPEN'",
            (stop_id,),
        )
