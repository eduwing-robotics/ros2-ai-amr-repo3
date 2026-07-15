"""Robot command dispatch schemas and lifecycle vocabulary."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class RobotCommandKind(StrEnum):
    MOVE_TO_POINT = "move_to_point"
    DOCK_TRANSFER = "dock_transfer"
    MANUAL_DRIVE = "manual_drive"
    ESTOP = "estop"
    ARUCO_ALIGN = "aruco_align"
    LEAVE_DOCK = "leave_dock"
    SCENARIO = "scenario"


class RobotCommandState(StrEnum):
    ACCEPTED = "ACCEPTED"
    RUNNING = "RUNNING"
    ARRIVED = "ARRIVED"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    STOPPED = "STOPPED"


class RobotCommandRequest(BaseModel):
    """POST /robot-commands envelope."""

    robot_id: str
    kind: RobotCommandKind
    command_id: str | None = None
    task_id: int | None = None
    dry_run: bool = False
    params: dict[str, Any] = Field(default_factory=dict)
    callback_url: str | None = None


class RobotCommandResponse(BaseModel):
    """Robot command dispatch 결과."""

    command_id: str
    robot_id: str
    kind: RobotCommandKind
    dry_run: bool = False
    accepted: bool = True
    response: dict[str, Any] = Field(default_factory=dict)
