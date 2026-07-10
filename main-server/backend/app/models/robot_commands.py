"""Robot command dispatch schemas."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RobotCommandRequest(BaseModel):
    """POST /robot-commands envelope (PHASE_12-B)."""

    model_config = ConfigDict(extra="forbid")

    robot_id: str
    kind: Literal["move_to_point", "dock_transfer", "manual_drive", "estop", "aruco_align", "leave_dock"]
    command_id: str | None = None
    task_id: int | None = None
    dry_run: bool = False
    params: dict[str, Any] = Field(default_factory=dict)


class RobotCommandResponse(BaseModel):
    """Robot command dispatch 결과."""

    command_id: str
    robot_id: str
    kind: str
    dry_run: bool = False
    accepted: bool = True
    response: dict[str, Any] = Field(default_factory=dict)
