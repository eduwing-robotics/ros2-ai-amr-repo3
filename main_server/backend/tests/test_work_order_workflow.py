# 기능 책임: Work Order 생성·배정·접수 순서를 검증한다. 비책임: 슬롯 선정과 실장비 물리 동작.
from __future__ import annotations

from unittest.mock import MagicMock, patch

from fastapi import HTTPException

from app.domains.work_orders import workflow


def test_create_work_order_exposes_planned_task_to_assignment_and_start() -> None:
    payload = {
        "operation": "outbound",
        "item_code": "bolt_1",
        "quantity": 1,
        "auto_start": True,
        "robot_id": "tb3_2",
    }
    entry = {"slot": {"slot_id": "STORAGE_02"}, "plan_summary": {"floor": 1}}
    with (
        patch.object(workflow.items, "exists", return_value=True),
        patch.object(workflow.planner, "plan_work_order", return_value={"_planned_entries": [entry]}),
        patch.object(workflow, "_create_task", return_value=384) as create_task,
        patch.object(workflow, "_assign_tasks") as assign_tasks,
        patch.object(workflow, "_start_tasks", return_value=([{"command_id": "cmd-384"}], [])) as start_tasks,
        patch.object(workflow.operational_events, "append"),
        patch.object(
            workflow.service,
            "assemble_work_order_response",
            return_value={"order_id": 384},
        ) as assemble,
    ):
        result = workflow.create_work_order(MagicMock(), payload, callback_base_url="http://main/callback")

    assert result == {"order_id": 384}
    assert create_task.call_args.kwargs["operation"] == "outbound"
    assign_tasks.assert_called_once()
    start_tasks.assert_called_once()
    assemble.assert_called_once()


def test_start_tasks_reports_movement_rejection_without_hiding_created_task() -> None:
    with (
        patch.object(workflow.postgres_tasks, "get_task", return_value={"status": "ASSIGNED"}),
        patch.object(
            workflow.tasks,
            "start_task_execution",
            side_effect=HTTPException(status_code=409, detail={"code": "waypoint_location_mismatch"}),
        ),
    ):
        started, failed = workflow._start_tasks(
            MagicMock(),
            [383],
            auto_start=True,
            callback_base_url="http://main/callback",
        )

    assert started == []
    assert failed == [{"task_id": 383, "detail": {"code": "waypoint_location_mismatch"}}]


def test_inbound_task_resolves_only_its_source_zone_and_uses_validated_quantity() -> None:
    with (
        patch.object(workflow.locations, "get_inbound", return_value={"slot_id": "INBOUND_02"}) as inbound,
        patch.object(workflow.locations, "get_outbound") as outbound,
        patch.object(workflow.postgres_tasks, "create_task_record", return_value=392) as create_task,
        patch.object(workflow.operational_events, "append"),
    ):
        task_id = workflow._create_task(
            MagicMock(),
            operation="inbound",
            item_code="bolt_1",
            quantity=3,
            slot={"slot_id": "STORAGE_02"},
            floor=1,
            plan_summary={"selection_reason": "operator_specified"},
            payload={"inbound_waypoint_id": "INBOUND_02"},
        )

    assert task_id == 392
    inbound.assert_called_once()
    outbound.assert_not_called()
    record = create_task.call_args.args[1]
    assert record["quantity"] == 3
    assert record["from_location_id"] == "INBOUND_02"
    assert record["to_location_id"] == "STORAGE_02"
