"""책임: canonical Work Order 조회 모델을 기존 `/api/v1` 필드 alias로 변환한다.
비책임: 내부 식별자 명명, 상태 전이와 조회 데이터 생성."""

from __future__ import annotations

from typing import Any

from app.models.work_orders import RobotTaskSummary, WorkOrderOperation


def robot_task_summary_to_v1(summary: RobotTaskSummary) -> dict[str, Any]:
    """canonical Task summary를 문서화된 legacy `tasks[]` 계약으로만 변환한다."""

    plan = summary.plan
    return {
        "order_id": summary.order_id,
        "task_id": summary.robot_task_id,
        "slot_id": summary.slot_id,
        "floor": summary.floor,
        "quantity": summary.allocated_quantity,
        "priority": summary.priority,
        "status": summary.status,
        "assigned_robot_id": summary.assigned_robot_id,
        "command_id": summary.active_command_id,
        "slot_label": plan.slot_label if plan else None,
        "source_zone": plan.source_zone_label if plan else None,
        "target_zone": plan.target_zone_label if plan else None,
        "selection_reason": plan.selection_reason if plan else None,
        "available_qty_at_plan": plan.available_quantity_at_plan if plan else None,
        "business_completed": summary.business_completed,
        "return_status": summary.return_status,
        "parking_error": summary.parking_error,
        "progress": summary.progress.model_dump(mode="json") if summary.progress else None,
    }


def work_order_response_to_v1(
    *,
    order_id: int,
    operation: WorkOrderOperation,
    item_code: str,
    requested_quantity: int,
    status: str,
    robot_tasks: list[RobotTaskSummary],
    created_by: str | None,
    created_at: object,
    business_completed: bool,
    return_status: str | None,
    parking_error: dict[str, Any] | None,
) -> dict[str, Any]:
    """Keep public /api/v1 names outside domain and assembly logic."""

    return {
        "order_id": order_id,
        "operation": operation,
        "item_code": item_code,
        "quantity": requested_quantity,
        "status": status,
        "created_by": created_by,
        "created_at": created_at,
        "tasks": [robot_task_summary_to_v1(task) for task in robot_tasks],
        "business_completed": business_completed,
        "return_status": return_status,
        "parking_error": parking_error,
    }
