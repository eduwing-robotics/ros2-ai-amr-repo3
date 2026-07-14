"""Pure read-model assembly for work-order robot tasks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.domains.execution.state import RobotTaskExecutionState
from app.models.work_orders import RobotTaskPlanSummary, RobotTaskSummary


class RobotTaskSummaryAssembler:
    """Combine task, execution, plan, and location data without side effects."""

    @staticmethod
    def assemble(
        *,
        robot_task: Mapping[str, Any],
        order_id: int | None,
        execution: RobotTaskExecutionState,
        active_command_id: str | None,
        floor: int | None,
        source_zone_label: str | None = None,
        target_zone_label: str | None = None,
        plan_data: Mapping[str, Any] | None = None,
        parking_error: dict[str, Any] | None = None,
    ) -> RobotTaskSummary:
        plan_data = plan_data or {}
        slot_id = robot_task.get("slot_id")
        plan = RobotTaskPlanSummary(
            slot_label=str(plan_data.get("slot_label") or slot_id or "") or None,
            source_zone_label=source_zone_label or None,
            target_zone_label=target_zone_label or None,
            selection_reason=_optional_str(plan_data.get("selection_reason")),
            available_quantity_at_plan=_optional_int(plan_data.get("available_qty_at_plan")),
        )
        return RobotTaskSummary(
            robot_task_id=int(robot_task["task_id"]),
            order_id=order_id,
            kind=str(robot_task["task_type"]).upper(),
            allocated_quantity=int(robot_task.get("quantity") or 1),
            priority=int(robot_task.get("priority") or 0),
            status=str(robot_task["status"]).upper(),
            assigned_robot_id=_optional_str(robot_task.get("assigned_robot_id")),
            active_command_id=active_command_id,
            source_location_id=_optional_str(
                robot_task.get("from_location_id") or robot_task.get("from_location")
            ),
            target_location_id=_optional_str(
                robot_task.get("to_location_id") or robot_task.get("to_location")
            ),
            slot_id=_optional_str(slot_id),
            floor=floor,
            business_completed=execution.business_completed,
            return_status=execution.return_status,
            parking_error=parking_error,
            plan=plan,
            created_at=robot_task.get("created_at"),
            started_at=robot_task.get("started_at"),
            finished_at=robot_task.get("finished_at"),
        )


def _optional_str(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


def _optional_int(value: object) -> int | None:
    return int(value) if value not in (None, "") else None
