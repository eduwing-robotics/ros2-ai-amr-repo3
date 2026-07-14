"""Robot task and robot task step schemas."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

from app.models.robot_commands import RobotCommandKind


class RobotTaskStatus(StrEnum):
    """Lifecycle of a robot-executable task exposed by the Main API."""

    CREATED = "CREATED"
    QUEUED = "QUEUED"
    ASSIGNED = "ASSIGNED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RobotTaskKind(StrEnum):
    """Kind of work assigned to one robot."""

    INBOUND = "INBOUND"
    OUTBOUND = "OUTBOUND"
    MOVE = "MOVE"
    CHARGE = "CHARGE"


class RobotTaskReturnStatus(StrEnum):
    """Post-business return and parking status for one robot task."""

    RETURNING_HOME = "RETURNING_HOME"
    PARKING = "PARKING"
    PARKED = "PARKED"
    PARK_FAILED = "PARK_FAILED"


class RobotTaskStepStatus(StrEnum):
    """Lifecycle of one planned step within a robot task."""

    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class RobotTaskStep(BaseModel):
    """A planned robot action; one step may produce one or more robot commands."""

    kind: RobotCommandKind
    params: dict[str, Any] = Field(default_factory=dict)
    status: RobotTaskStepStatus = RobotTaskStepStatus.PENDING
    command_id: str | None = None


class RobotTask(BaseModel):
    """A robot-executable unit planned from a work order or direct request."""

    task_id: int
    task_type: str
    preset_name: str | None = None
    status: RobotTaskStatus
    priority: int = 0
    assigned_robot_id: str | None = None
    from_location: str | None = None
    to_location: str | None = None
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class RobotTaskCreate(BaseModel):
    """Robot task creation request."""

    task_type: str = "MOVE"
    preset_name: str | None = None
    priority: int = 0
    from_location: str | None = None
    to_location: str | None = None
    created_by: str | None = "operator"


class RobotTaskAssign(BaseModel):
    """Robot task assignment request."""

    robot_id: str
