# 기능 책임: canonical API·저장 계약을 검증한다. 비책임: 실장비의 물리 동작.
"""Contract tests for canonical public and persisted representations."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi.encoders import jsonable_encoder

from app.db.postgres import runtime_records
from app.domains.execution import router as execution_router
from app.domains.execution import state as orchestration_state
from app.main import app
from app.models.tasks import RobotTask
from app.models.work_orders import WorkOrder, WorkOrderOperation


def _operation(path: str, method: str) -> dict:
    return app.openapi()["paths"][path][method]


def test_openapi_operation_ids_and_response_models_remain_compatible() -> None:
    expected = {
        ("/api/v1/tasks/{task_id}/start", "post"): (
            "start_task_execution_api_v1_tasks__task_id__start_post",
            "#/components/schemas/RobotTaskStartResponse",
        ),
        ("/api/v1/tasks/{task_id}/cancel", "post"): (
            "cancel_task_api_v1_tasks__task_id__cancel_post",
            "#/components/schemas/RobotTask",
        ),
        ("/api/v1/work-orders", "post"): (
            "create_work_order_api_v1_work_orders_post",
            "#/components/schemas/WorkOrder",
        ),
    }

    for (path, method), (operation_id, response_ref) in expected.items():
        operation = _operation(path, method)
        response_schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
        assert operation["operationId"] == operation_id
        if response_ref is None:
            assert response_schema["type"] == "object"
            assert response_schema["additionalProperties"] is True
        else:
            assert response_schema == {"$ref": response_ref}


def test_start_task_response_uses_canonical_execution_fields() -> None:
    result = {
        "task": {
            "task_id": 17,
            "task_type": "MOVE",
            "status": "RUNNING",
            "assigned_robot_id": "tb3_1",
        },
        "robot_id": "tb3_1",
        "command_id": "cmd-17",
        "step_count": 3,
    }
    transaction = MagicMock()
    transaction.return_value.__enter__.return_value = MagicMock(name="conn")

    with (
        patch.object(execution_router, "transaction", transaction),
        patch.object(execution_router, "callback_base_url", return_value="http://main.example/api/v1"),
        patch.object(execution_router.tasks, "start_task_execution", return_value=result),
    ):
        response = execution_router.start_task_execution(17, MagicMock())

    encoded = jsonable_encoder(response)
    assert encoded["task"]["task_id"] == 17
    assert encoded == {
        "task": encoded["task"],
        "robot_id": "tb3_1",
        "command_id": "cmd-17",
        "step_count": 3,
    }


def test_work_order_keeps_execution_results_field() -> None:
    work_order = WorkOrder(
        order_id=21,
        operation=WorkOrderOperation.INBOUND,
        item_code="ITEM-A",
        quantity=2,
        status="RUNNING",
        execution_results=[{"task_id": 21, "command_id": "cmd-21"}],
    )

    payload = work_order.model_dump(mode="json")
    assert payload["execution_results"] == [{"task_id": 21, "command_id": "cmd-21"}]


def test_new_orchestration_uses_only_canonical_keys() -> None:
    steps = [{"kind": "move_to_point", "status": "PENDING"}]

    orchestration = orchestration_state.new_orchestration(
        steps,
        callback_base_url="http://main.example/api/v1",
    )

    assert orchestration["steps"] == steps
    assert orchestration["step_index"] == 0
    assert "legs" not in orchestration
    assert "cursor" not in orchestration
    assert orchestration["callback_base_url"] == "http://main.example/api/v1"


def test_orchestration_lookup_breaks_same_timestamp_ties_by_id() -> None:
    conn = MagicMock()
    conn.execute.return_value.fetchone.return_value = {
        "data_json": {"phase": "RUNNING", "step_index": 1},
    }

    result = runtime_records.get_orchestration(conn, 31)

    sql = conn.execute.call_args.args[0]
    assert "ORDER BY observed_at DESC, id DESC" in sql
    assert result == {"phase": "RUNNING", "step_index": 1}


def test_command_lookup_reads_canonical_steps() -> None:
    conn = MagicMock()
    conn.execute.return_value.fetchall.return_value = [
        {
            "task_id": 31,
            "data_json": {
                "steps": [
                    {"kind": "move_to_point", "command_id": "command-31"},
                ],
            },
        }
    ]

    assert runtime_records.find_task_id_by_robot_command(conn, "command-31") == 31
