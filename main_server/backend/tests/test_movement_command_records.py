# 기능 책임: Movement command trace 조립과 정렬을 검증한다. 비책임: 실장비의 물리 동작.
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domains.records import movement_commands


def test_projection_keeps_command_contract_and_drops_unrelated_payload() -> None:
    rows = [
        {
            "id": 9,
            "event_type": "MOVE_TO_POINT",
            "source": "movement",
            "observed_at": "2026-07-14T01:02:03+00:00",
            "data_json": {
                "command_id": "cmd-9",
                "robot_id": "tb3_1",
                "command": "move_to_point",
                "status": "ACCEPTED",
                "request": {"x": 1.0},
                "response": {"accepted": True},
            },
        },
        {
            "id": 10,
            "event_type": "INTERNAL_EVENT",
            "source": "runtime",
            "observed_at": "2026-07-14T01:02:04+00:00",
            "data_json": {"secret": "must-not-leak"},
        },
    ]
    conn = MagicMock()
    with patch.object(movement_commands.runtime_records, "list_movement_command_evidence", return_value=rows) as read:
        result = movement_commands.list_movement_command_records(conn, limit=10)

    read.assert_called_once_with(conn, limit=10)
    assert result == [
        {
            "command_id": "cmd-9",
            "robot_id": "tb3_1",
            "command_type": "MOVE_TO_POINT",
            "command": "move_to_point",
            "status": "ACCEPTED",
            "request_payload": {"x": 1.0},
            "response_payload": {"accepted": True},
            "created_at": "2026-07-14T01:02:03+00:00",
            "layer": "dbml",
            "source_table": "evidence_events",
        }
    ]


def test_projection_uses_result_payload_without_exposing_message() -> None:
    row = {
        "id": 11,
        "event_type": "MOVEMENT_RESULT",
        "source": "movement",
        "observed_at": "now",
        "data_json": {
            "command_id": "cmd-11",
            "result": "DONE",
            "message": "internal upstream detail",
            "result_payload": {"distance": 1.2},
        },
    }
    with patch.object(movement_commands.runtime_records, "list_movement_command_evidence", return_value=[row]):
        result = movement_commands.list_movement_command_records(MagicMock(), limit=1)

    assert result[0]["status"] == "DONE"
    assert result[0]["request_payload"] == {}
    assert result[0]["response_payload"] == {"distance": 1.2}
    assert "internal upstream detail" not in str(result)
