"""Read model for movement command records derived from runtime evidence."""

from __future__ import annotations

from typing import Any

from app.db.postgres import runtime_records


def list_movement_command_records(conn, limit: int = 50) -> list[dict[str, Any]]:
    """Return command-shaped records without exposing unrelated runtime payloads."""

    rows = runtime_records.list_movement_command_evidence(conn, limit=max(limit, 1))
    out: list[dict[str, Any]] = []
    for row in rows:
        data = row.get("data_json") or {}
        if not isinstance(data, dict):
            continue
        command_id = data.get("command_id")
        if not command_id:
            continue
        source = str(row.get("source") or "")
        if source not in {"movement", "orchestrator", "runtime"}:
            continue
        out.append(
            {
                "command_id": str(command_id),
                "robot_id": data.get("robot_id"),
                "command_type": row["event_type"],
                "command": data.get("command") or row["event_type"],
                "status": data.get("status") or data.get("result") or row["event_type"],
                "request_payload": data.get("request") if isinstance(data.get("request"), dict) else {},
                "response_payload": _response_payload(data),
                "created_at": row.get("observed_at") or "",
                "layer": "dbml",
                "source_table": "evidence_events",
            }
        )
        if len(out) >= limit:
            break
    return out


def _response_payload(data: dict[str, Any]) -> dict[str, Any]:
    response = data.get("response")
    if isinstance(response, dict):
        return response
    result = data.get("result_payload")
    return result if isinstance(result, dict) else {}
