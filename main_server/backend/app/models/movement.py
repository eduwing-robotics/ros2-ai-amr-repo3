"""Movement command and mission schemas."""

from typing import Any

from pydantic import BaseModel, Field


class MovementCommand(BaseModel):
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
