"""Pure read-model assembly for work-order robot tasks."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from app.domains.execution.state import RobotTaskExecutionState
from app.models.work_orders import (
    RobotTaskPlanSummary,
    RobotTaskProgress,
    RobotTaskProgressStep,
    RobotTaskSummary,
)


def _progress_snapshot(execution: RobotTaskExecutionState) -> RobotTaskProgress | None:
    steps = execution.steps
    if not steps:
        return None
    if len(steps) == 1 and str(steps[0].get("kind")) == "route":
        route_steps = steps[0].get("route_timeline")
        if isinstance(route_steps, list) and route_steps:
            return RobotTaskProgress(
                phase=execution.phase,
                current_step_index=int(steps[0].get("route_timeline_current_index") or 0),
                steps=[
                    RobotTaskProgressStep(
                        step_index=index,
                        kind=str(step.get("kind") or "unknown"),
                        label=_optional_str(step.get("label")),
                        status=str(step.get("status") or "PENDING").upper(),
                        command_id=_optional_str(step.get("command_id")),
                        transfer_action=_optional_str(step.get("transfer_action")),
                        failure_reason=_optional_str(step.get("failure_reason")),
                    )
                    for index, step in enumerate(route_steps)
                ],
            )
    return RobotTaskProgress(
        phase=execution.phase,
        current_step_index=execution.step_index,
        steps=[
            RobotTaskProgressStep(
                step_index=index,
                kind=str(step.get("kind") or "unknown"),
                label=_optional_str(step.get("label")),
                status=str(step.get("status") or "PENDING").upper(),
                command_id=_optional_str(step.get("command_id")),
                transfer_action=_optional_str(
                    step.get("transfer_action") or (step.get("params") or {}).get("action")
                ),
                failure_reason=_optional_str(step.get("dispatch_error")),
            )
            for index, step in enumerate(steps)
        ],
    )


def assemble_robot_task_summary(
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
    """Combine task, execution, plan, and location data without side effects."""
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
        source_location_id=_optional_str(robot_task.get("from_location_id") or robot_task.get("from_location")),
        target_location_id=_optional_str(robot_task.get("to_location_id") or robot_task.get("to_location")),
        slot_id=_optional_str(slot_id),
        floor=floor,
        business_completed=execution.business_completed,
        return_status=execution.return_status,
        parking_error=parking_error,
        progress=_progress_snapshot(execution),
        plan=plan,
        created_at=robot_task.get("created_at"),
        started_at=robot_task.get("started_at"),
        finished_at=robot_task.get("finished_at"),
    )


def _optional_str(value: object) -> str | None:
    return str(value) if value not in (None, "") else None


def _optional_int(value: object) -> int | None:
    return int(value) if value not in (None, "") else None
