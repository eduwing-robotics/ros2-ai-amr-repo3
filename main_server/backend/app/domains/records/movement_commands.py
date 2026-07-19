"""Read model for movement command records derived from runtime evidence."""

from __future__ import annotations

from typing import Any

from app.db.postgres import runtime_records


def list_movement_command_records(conn, limit: int = 50) -> list[dict[str, Any]]:
    """명령별 최신 상태와 접수 payload를 합쳐 command당 한 행을 반환한다."""
    rows = runtime_records.list_movement_command_evidence(conn, limit=max(limit, 1))
    return _merge_command_rows(rows, limit=limit)


def list_movement_command_records_by_id(conn, command_id: str) -> list[dict[str, Any]]:
    """해당 Movement command의 evidence를 하나의 command record로 투영한다."""
    rows = runtime_records.list_movement_command_evidence_by_id(conn, command_id)
    return _merge_command_rows(rows, limit=1)


def _merge_command_rows(rows: list[dict[str, Any]], *, limit: int) -> list[dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    for row in rows:
        data = row.get("data_json") or {}
        if not isinstance(data, dict):
            continue
        command_id = data.get("command_id") or data.get("movement_command_id")
        if not command_id:
            continue
        key = str(command_id)
        record = records.get(key)
        request = data.get("request") if isinstance(data.get("request"), dict) else {}
        response = _response_payload(data)
        if record is None:
            record = {
                "command_id": key,
                "robot_id": data.get("robot_id"),
                "command_type": row["event_type"],
                "command": data.get("command") or row["event_type"],
                "status": data.get("status") or data.get("result") or row["event_type"],
                "request_payload": request,
                "response_payload": response,
                "created_at": row.get("observed_at") or "",
                "layer": "dbml",
                "source_table": "evidence_events",
            }
            records[key] = record
        else:
            record["robot_id"] = record["robot_id"] or data.get("robot_id")
            record["request_payload"] = record["request_payload"] or request
            record["response_payload"] = record["response_payload"] or response
            if data.get("command"):
                record["command"] = data["command"]
                record["command_type"] = row["event_type"]
            record["created_at"] = row.get("observed_at") or record["created_at"]
    return list(records.values())[:limit]


def _response_payload(data: dict[str, Any]) -> dict[str, Any]:
    response = data.get("response")
    if isinstance(response, dict):
        return response
    result = data.get("result_payload")
    return result if isinstance(result, dict) else {}
