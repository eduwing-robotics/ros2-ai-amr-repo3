"""Work order schemas."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.models.tasks import RobotTaskKind, RobotTaskReturnStatus, RobotTaskStatus


class WorkOrderOperation(StrEnum):
    """Business operation requested by a work order."""

    INBOUND = "inbound"
    OUTBOUND = "outbound"


class RobotTaskPlanSummary(BaseModel):
    """Read-only planning details exposed separately from robot task runtime state."""

    slot_label: str | None = None
    source_zone_label: str | None = None
    target_zone_label: str | None = None
    selection_reason: str | None = None
    available_quantity_at_plan: int | None = None


class RobotTaskProgressStep(BaseModel):
    """Operator-facing projection of one callback-tracked execution step."""

    step_index: int = Field(ge=0)
    kind: str
    label: str | None = None
    status: str
    command_id: str | None = None
    transfer_action: str | None = None
    failure_reason: str | None = None


class RobotTaskProgress(BaseModel):
    """Read-only progress snapshot updated by Movement callbacks or polling fallback."""

    phase: str
    current_step_index: int = Field(ge=0)
    steps: list[RobotTaskProgressStep] = Field(default_factory=list)


class RobotTaskSummary(BaseModel):
    """Canonical read model assembled from task, execution, plan, and location data."""

    robot_task_id: int
    order_id: int | None = None
    kind: RobotTaskKind
    allocated_quantity: int = Field(ge=1)
    priority: int = 0
    status: RobotTaskStatus
    assigned_robot_id: str | None = None
    active_command_id: str | None = None
    source_location_id: str | None = None
    target_location_id: str | None = None
    slot_id: str | None = None
    floor: int | None = Field(default=None, ge=1, le=2)
    business_completed: bool = False
    return_status: RobotTaskReturnStatus | None = None
    parking_error: dict[str, Any] | None = None
    progress: RobotTaskProgress | None = None
    plan: RobotTaskPlanSummary | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


class WorkOrderRobotTask(BaseModel):
    """Deprecated /api/v1 work-order task projection."""

    order_id: int
    task_id: int
    slot_id: str | None = None
    floor: int | None = Field(default=None, ge=1, le=2)
    quantity: int = Field(default=1, ge=1)
    priority: int = 0
    status: str | None = None
    assigned_robot_id: str | None = None
    command_id: str | None = None
    slot_label: str | None = None
    source_zone: str | None = None
    target_zone: str | None = None
    selection_reason: str | None = None
    available_qty_at_plan: int | None = None
    business_completed: bool = False
    return_status: str | None = None
    parking_error: dict[str, Any] | None = None
    progress: RobotTaskProgress | None = None


class WorkOrder(BaseModel):
    """입고/출고 업무 요청."""

    order_id: int
    operation: WorkOrderOperation
    item_code: str
    quantity: int = Field(ge=1)
    status: str
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    tasks: list[WorkOrderRobotTask] = Field(default_factory=list)
    execution_results: list[dict[str, Any]] = Field(default_factory=list)
    start_failed: list[dict[str, Any]] = Field(default_factory=list)
    business_completed: bool = False
    return_status: str | None = None
    parking_error: dict[str, Any] | None = None


class WorkOrderCreate(BaseModel):
    """품목/수량 기반 입고/출고 요청."""

    operation: WorkOrderOperation
    item_code: str
    quantity: int = Field(ge=1, le=50)
    floor: int | None = Field(default=None, ge=1, le=2)
    auto_start: bool = False
    priority: int = 0
    callback_base_url: str | None = None
    created_by: str | None = "operator"
    slot_id: str | None = None
    slot_ids: list[str] | None = None
    inbound_waypoint_id: str | None = None
    outbound_waypoint_id: str | None = None
    robot_id: str | None = None


class WorkOrderPriorityUpdate(BaseModel):
    """작업오더 우선순위 조정 (높을수록 먼저 배정)."""

    priority: int = Field(ge=0, le=1000)


class WorkOrderPreviewRequest(BaseModel):
    """입출고 계획 미리보기 (무쓰기)."""

    operation: WorkOrderOperation
    item_code: str
    quantity: int = Field(ge=1, le=50)
    floor: int | None = Field(default=None, ge=1, le=2)
    slot_id: str | None = None
    slot_ids: list[str] | None = None
    inbound_waypoint_id: str | None = None
    outbound_waypoint_id: str | None = None


class WorkOrderPlannedSlot(BaseModel):
    slot_id: str
    floor: int = Field(default=1, ge=1, le=2)
    slot_label: str | None = None
    map_id: str | None = None
    source_zone: str | None = None
    target_zone: str | None = None
    selection_reason: str | None = None
    available_qty_at_plan: int | None = None


class WorkOrderPlannedZone(BaseModel):
    waypoint_id: str
    name: str
    map_id: str


class WorkOrderPreview(BaseModel):
    operation: WorkOrderOperation
    item_code: str
    quantity: int
    slots: list[WorkOrderPlannedSlot] = Field(default_factory=list)
    zone: WorkOrderPlannedZone | None = None
