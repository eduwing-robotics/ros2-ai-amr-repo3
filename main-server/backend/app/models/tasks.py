"""Task schemas."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class Task(BaseModel):
    """관제 작업(task)."""

    task_id: int
    task_type: str
    preset_name: str | None = None
    status: str
    priority: int = 0
    assigned_robot_id: str | None = None
    from_location: str | None = None
    to_location: str | None = None
    created_by: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class TaskCreate(BaseModel):
    """작업 생성 요청."""

    task_type: str = "MOVE"
    preset_name: str | None = None
    priority: int = 0
    from_location: str | None = None
    to_location: str | None = None
    created_by: str | None = "operator"


class TaskAssign(BaseModel):
    """작업 수동 배정 요청."""

    robot_id: str


class TaskStartRequest(BaseModel):
    """Explicit execution boundary for starting an assigned task."""

    model_config = ConfigDict(extra="forbid")

    execution_mode: Literal["physical", "synthetic_hil"] = "physical"
    admit_nonphysical: bool = False


class RecoverySafetyChecks(BaseModel):
    """Operator confirmations required before any recovery action."""

    model_config = ConfigDict(extra="forbid")

    site_clear: Literal[True]
    pose_ok: Literal[True]
    cargo_ok: Literal[True]


class RecoveryActionRequest(BaseModel):
    """Fail-closed recovery decision or execution request."""

    model_config = ConfigDict(extra="forbid")

    cargo_state: Literal["LOADED", "EMPTY", "UNKNOWN"] = "UNKNOWN"
    strategy: Literal["resume_task", "safe_move", "manual_abort"] = "safe_move"
    checks: RecoverySafetyChecks
