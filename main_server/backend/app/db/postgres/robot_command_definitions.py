from __future__ import annotations

from typing import Any

from app.db.postgres import runtime_records


def list_for_task_type(conn, task_type: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "\n            SELECT * FROM commands\n            WHERE task_type = %s AND is_active = true\n            ORDER BY sequence_no\n            ",
        (task_type,),
    ).fetchall()
    return [dict(r) for r in rows]


def get_robot_command_definition(conn, command_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM commands WHERE id = %s", (command_id,)).fetchone()
    return dict(row) if row else None


def resolve_for_step(conn, task_type: str, sequence_no: int, command_type: str | None = None) -> int | None:
    for cmd in list_for_task_type(conn, task_type):
        if int(cmd["sequence_no"]) != sequence_no:
            continue
        if command_type is None or cmd["command_type"] == command_type:
            return int(cmd["id"])
    return None


def progress_for_task(conn, task_id: int, task_type: str) -> list[dict[str, Any]]:
    """Derive command progress from static definitions + evidence."""
    defs = list_for_task_type(conn, task_type)
    evidence_rows = conn.execute(
        "\n            SELECT command_id, event_type, trusted, severity, observed_at\n            FROM evidence_events\n            WHERE task_id = %s AND event_type <> %s\n            ORDER BY observed_at\n            ",
        (task_id, runtime_records.ORCHESTRATION_TYPE),
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
        satisfied = any((e["event_type"] == cmd["required_evidence_type"] and e.get("trusted", True) for e in evs))
        out.append(
            {
                "command_id": cid,
                "sequence_no": cmd["sequence_no"],
                "command_type": cmd["command_type"],
                "target_system": cmd["target_system"],
                "required_evidence_type": cmd["required_evidence_type"],
                "status": "DONE" if satisfied else latest,
                "evidence_count": len(evs),
            }
        )
    return out
