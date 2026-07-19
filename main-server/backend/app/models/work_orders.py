"""Work order schemas."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class WorkOrderTask(BaseModel):
    """work order와 실제 task 연결."""

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
    progress: "WorkOrderTaskProgress | None" = None


class WorkOrderTaskProgressStep(BaseModel):
    step_index: int = Field(ge=0)
    kind: str
    label: str | None = None
    status: str
    command_id: str | None = None
    transfer_action: str | None = None
    failure_reason: str | None = None
    command_def_id: int | None = None
    sequence_no: int | None = None
    command_type: str | None = None
    target_system: str | None = None
    required_evidence_type: str | None = None
    evidence_count: int = 0
    runtime_command_id: str | None = None
    target: str | None = None
    human_hazard_monitor: bool = False
    last_observed_at: str | None = None


class WorkOrderTaskProgress(BaseModel):
    phase: str
    current_step_index: int = Field(ge=0)
    steps: list[WorkOrderTaskProgressStep] = Field(default_factory=list)
    current_recipe_index: int = Field(default=0, ge=0)
    recipe_steps: list[WorkOrderTaskProgressStep] = Field(default_factory=list)
    recovery_reason: str | None = None
    cargo_state: str | None = None


class WorkOrder(BaseModel):
    """입고/출고 업무 요청."""

    order_id: int
    operation: Literal["inbound", "outbound"] | str
    item_code: str
    item_name: str | None = None
    aruco_marker_id: int | None = Field(default=None, ge=20, le=49)
    quantity: int = Field(ge=1)
    status: str
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    tasks: list[WorkOrderTask] = Field(default_factory=list)
    mission_results: list[dict[str, Any]] = Field(default_factory=list)
    business_completed: bool = False
    return_status: str | None = None
    parking_error: dict[str, Any] | None = None
    execution_mode: Literal["physical", "synthetic_hil"] = "physical"


class WorkOrderStopResult(BaseModel):
    order_id: int
    task_id: int
    status: Literal["CANCEL_REQUESTED", "AWAITING_OPERATOR"]
    accepted: bool
    command_id: str | None = None
    cargo_state: Literal["EMPTY", "LOADED", "UNKNOWN"]
    business_completed: bool = False


class WorkOrderCreate(BaseModel):
    """품목/수량 기반 입고/출고 요청."""

    # Reject callback destination injection rather than silently accepting it.
    model_config = ConfigDict(extra="forbid")

    operation: Literal["inbound", "outbound"]
    item_code: str
    quantity: int = Field(ge=1, le=50)
    floor: int | None = Field(default=None, ge=1, le=2)
    auto_start: bool = False
    priority: int = 0
    created_by: str | None = "operator"
    slot_id: str | None = None
    slot_ids: list[str] | None = None
    inbound_waypoint_id: str | None = None
    outbound_waypoint_id: str | None = None
    robot_id: str | None = None
    execution_mode: Literal["physical", "synthetic_hil"] = "physical"
    admit_nonphysical: bool = False

    @model_validator(mode="after")
    def validate_execution_mode(self) -> "WorkOrderCreate":
        if self.execution_mode == "synthetic_hil":
            if not self.admit_nonphysical:
                raise ValueError("explicit nonphysical admission is required")
            if not self.auto_start or not self.robot_id:
                raise ValueError("synthetic_hil work orders require auto_start and an explicit robot_id")
        elif self.admit_nonphysical:
            raise ValueError("admit_nonphysical is only valid for synthetic_hil")
        return self


class WorkOrderPriorityUpdate(BaseModel):
    """작업오더 우선순위 조정 (높을수록 먼저 배정)."""

    priority: int = Field(ge=0, le=1000)


class WorkOrderPreviewRequest(BaseModel):
    """입출고 계획 미리보기 (무쓰기)."""

    operation: Literal["inbound", "outbound"]
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
    operation: Literal["inbound", "outbound"] | str
    item_code: str
    quantity: int
    slots: list[WorkOrderPlannedSlot] = Field(default_factory=list)
    zone: WorkOrderPlannedZone | None = None
