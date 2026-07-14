"""Movement command, mission, and callback schemas."""

from datetime import datetime
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RobotCommandRecord(BaseModel):
    """Main이 기록한 이동 명령."""

    command_id: str
    robot_id: str | None = None
    command_type: str
    command: str
    status: str
    request_payload: dict[str, Any] = Field(default_factory=dict)
    response_payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str


class MissionStatusResponse(BaseModel):
    """Movement mission API 응답 wrapper."""

    robot_id: str
    command_id: str | None = None
    response: dict[str, Any] = Field(default_factory=dict)


class RobotCommandEvent(BaseModel):
    """Canonical Movement command lifecycle callback."""

    model_config = ConfigDict(extra="allow")
    command_id: str = Field(min_length=1)
    robot_name: str | None = Field(default=None, min_length=1)
    robot_id: str | None = Field(default=None, min_length=1)
    task_id: int | None = Field(default=None, ge=1)
    event: str | None = Field(default=None, min_length=1)
    state: str | None = Field(default=None, min_length=1)
    message: str | None = None
    pose: dict[str, Any] | None = None
    reported_at: datetime | None = None
    event_id: str | None = Field(default=None, min_length=1)
    sequence: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_identity_and_state(self) -> Self:
        if not (self.robot_name or self.robot_id):
            raise ValueError("robot_name or robot_id is required")
        if not (self.event or self.state):
            raise ValueError("event or state is required")
        return self

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class RobotCommandResult(BaseModel):
    """Legacy result callback normalized into the command event state machine."""

    model_config = ConfigDict(extra="allow")
    command_id: str = Field(min_length=1)
    robot_name: str | None = Field(default=None, min_length=1)
    robot_id: str | None = Field(default=None, min_length=1)
    task_id: int | None = Field(default=None, ge=1)
    result: str = Field(min_length=1)
    message: str | None = None
    reported_at: datetime | None = None
    event_id: str | None = Field(default=None, min_length=1)
    sequence: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def validate_robot(self) -> Self:
        if not (self.robot_name or self.robot_id):
            raise ValueError("robot_name or robot_id is required")
        return self

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class MovementRobotStatusCallback(BaseModel):
    """Movement robot status callback; identity comes from the URL path."""

    model_config = ConfigDict(extra="allow")
    state: str | None = None
    current_command_id: str | None = None
    localized: bool | None = None
    pose: dict[str, Any] | None = None
    reported_at: datetime | None = None

    @model_validator(mode="after")
    def validate_status_content(self) -> Self:
        if self.state is None and self.current_command_id is None and self.localized is None and self.pose is None:
            raise ValueError("status callback has no state fields")
        return self

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class MovementCallbackAck(BaseModel):
    """Callback receipt acknowledgement."""

    ok: bool = True
    message: str = "movement callback accepted"
    duplicate: bool = False
    task_advanced: bool = False

# Deprecated compatibility aliases. Do not use in new code.
MovementCommand = RobotCommandRecord
MovementCommandEvent = RobotCommandEvent
MovementCommandResult = RobotCommandResult
