from datetime import UTC, datetime

from app.domains.execution.state import RobotTaskExecutionState
from app.domains.work_orders.adapters import robot_task_summary_to_v1, work_order_response_to_v1
from app.domains.work_orders.assembler import RobotTaskSummaryAssembler
from app.models.tasks import RobotTaskKind, RobotTaskStatus
from app.models.work_orders import WorkOrder, WorkOrderOperation


def _summary():
    execution = RobotTaskExecutionState.wrap(
        {
            "business_completed": True,
            "return_status": "PARK_FAILED",
        }
    )
    return RobotTaskSummaryAssembler.assemble(
        robot_task={
            "task_id": 41,
            "task_type": "INBOUND",
            "quantity": 6,
            "priority": 7,
            "status": "RUNNING",
            "assigned_robot_id": "tb3_1",
            "from_location_id": "inbound-1",
            "to_location_id": "slot-7",
            "slot_id": "slot-7",
            "created_at": datetime(2026, 7, 14, tzinfo=UTC),
        },
        order_id=10,
        execution=execution,
        active_command_id="cmd-41",
        floor=2,
        source_zone_label="입고 존",
        target_zone_label="보관 존",
        plan_data={
            "slot_label": "A-07",
            "selection_reason": "nearest_available",
            "available_qty_at_plan": 12,
        },
        parking_error={"reason": "home_blocked"},
    )


def test_assembler_uses_canonical_robot_task_names() -> None:
    summary = _summary()

    assert summary.robot_task_id == 41
    assert summary.order_id == 10
    assert summary.kind is RobotTaskKind.INBOUND
    assert summary.allocated_quantity == 6
    assert summary.status is RobotTaskStatus.RUNNING
    assert summary.active_command_id == "cmd-41"
    assert summary.source_location_id == "inbound-1"
    assert summary.target_location_id == "slot-7"
    assert summary.plan is not None
    assert summary.plan.slot_label == "A-07"
    assert summary.plan.available_quantity_at_plan == 12


def test_v1_adapter_keeps_legacy_work_order_fields() -> None:
    summary = _summary()
    task_payload = robot_task_summary_to_v1(summary)
    response = work_order_response_to_v1(
        order_id=10,
        operation=WorkOrderOperation.INBOUND,
        item_code="ITEM-A",
        requested_quantity=10,
        status="RUNNING",
        robot_tasks=[summary],
        created_by="operator",
        created_at="2026-07-14T00:00:00Z",
        business_completed=False,
        return_status=None,
        parking_error=None,
    )

    assert task_payload["task_id"] == 41
    assert task_payload["quantity"] == 6
    assert task_payload["command_id"] == "cmd-41"
    assert "robot_task_id" not in task_payload
    assert "allocated_quantity" not in task_payload
    assert response["quantity"] == 10
    assert response["tasks"] == [task_payload]
    assert "requested_quantity" not in response
    assert "robot_tasks" not in response

    serialized = WorkOrder(**response).model_dump(mode="json")
    assert serialized["operation"] == "inbound"
    assert serialized["tasks"][0]["task_id"] == 41
