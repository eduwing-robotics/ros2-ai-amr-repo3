"""Robot command dispatch schemas."""

from typing import Any, Literal

from pydantic import BaseModel, Field


class RobotCommandRequest(BaseModel):
    """POST /robot-commands envelope."""

    robot_id: str
    kind: Literal["move_to_point", "dock_transfer", "manual_drive", "estop", "aruco_align", "leave_dock"]
    command_id: str | None = None
    task_id: int | None = None
    dry_run: bool = False
    params: dict[str, Any] = Field(default_factory=dict)
    callback_url: str | None = None


class RobotCommandResponse(BaseModel):
    """Robot command dispatch 결과."""

    command_id: str
    robot_id: str
    kind: str
    dry_run: bool = False
    accepted: bool = True
    response: dict[str, Any] = Field(default_factory=dict)
