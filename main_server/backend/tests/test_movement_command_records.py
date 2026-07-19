# 기능 책임: Movement command trace 조립과 정렬을 검증한다. 비책임: 실장비의 물리 동작.
from __future__ import annotations

from unittest.mock import MagicMock, patch

from app.domains.movement import router as movement_router
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


def test_projection_merges_latest_status_with_original_request_once() -> None:
    rows = [
        {
            "event_type": "DONE",
            "source": "runtime",
            "observed_at": "2026-07-19T02:00:00+00:00",
            "data_json": {"movement_command_id": "cmd-1", "status": "DONE"},
        },
        {
            "event_type": "INOUT_SCENARIO",
            "source": "movement",
            "observed_at": "2026-07-19T01:00:00+00:00",
            "data_json": {
                "command_id": "cmd-1",
                "robot_id": "tb3_2",
                "command": "inout_scenario",
                "status": "ACCEPTED",
                "request": {"task_id": 391},
            },
        },
    ]
    with patch.object(movement_commands.runtime_records, "list_movement_command_evidence", return_value=rows):
        result = movement_commands.list_movement_command_records(MagicMock(), limit=10)

    assert len(result) == 1
    assert result[0]["status"] == "DONE"
    assert result[0]["robot_id"] == "tb3_2"
    assert result[0]["command"] == "inout_scenario"
    assert result[0]["request_payload"] == {"task_id": 391}
    assert result[0]["created_at"] == "2026-07-19T01:00:00+00:00"


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


def test_trace_queries_command_id_directly_without_recent_event_window() -> None:
    command = {"command_id": "old-command", "robot_id": "tb3_2", "status": "DONE"}
    callback = {"command_id": "old-command", "event_type": "DONE", "created_at": "now"}
    transaction = MagicMock()
    transaction.return_value.__enter__.return_value = MagicMock()
    with (
        patch.object(movement_router, "transaction", transaction),
        patch.object(
            movement_router.movement_commands,
            "list_movement_command_records_by_id",
            return_value=[command],
        ) as command_read,
        patch.object(
            movement_router.operational_events,
            "list_operational_events_by_command",
            return_value=[callback],
        ) as callback_read,
        patch.object(movement_router.command_status, "fetch", return_value={"state": "DONE"}),
    ):
        result = movement_router.movement_command_trace("old-command", robot_id=None)

    command_read.assert_called_once_with(transaction.return_value.__enter__.return_value, "old-command")
    callback_read.assert_called_once_with(transaction.return_value.__enter__.return_value, "old-command")
    assert result["callback_count"] == 1
    assert result["source"] == "polling"


def test_command_id_projection_accepts_runtime_movement_command_id() -> None:
    row = {
        "event_type": "MOVEMENT_CALLBACK",
        "source": "runtime",
        "observed_at": "now",
        "data_json": {"movement_command_id": "cmd-runtime", "robot_id": "tb3_2"},
    }
    with patch.object(movement_commands.runtime_records, "list_movement_command_evidence_by_id", return_value=[row]):
        result = movement_commands.list_movement_command_records_by_id(MagicMock(), "cmd-runtime")

    assert result[0]["command_id"] == "cmd-runtime"
