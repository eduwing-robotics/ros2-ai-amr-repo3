"""Movement command and callback schemas."""

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
    contract_version: str | None = None
    current_step_index: int | None = Field(default=None, ge=0, le=8)
    current_step_code: str | None = None
    current_step_action: str | None = None
    last_completed_step_index: int | None = Field(default=None, ge=0, le=8)
    cargo_state: str | None = None
    business_completed: bool | None = None
    reason_code: str | None = None
    navigator_status: str | None = None
    is_emergency: bool | None = None
    authority_owner: str | None = None
    authority_released: bool | None = None

    @model_validator(mode="after")
    def validate_identity_and_state(self) -> Self:
        if not (self.robot_name or self.robot_id):
            raise ValueError("robot_name or robot_id is required")
        if not (self.event or self.state):
            raise ValueError("event or state is required")
        if self.contract_version is not None:
            self._validate_scenario_v1()
        return self

    def _validate_scenario_v1(self) -> None:
        if self.contract_version != "1.0":
            raise ValueError("unsupported scenario contract_version")
        required = {
            "event_id",
            "sequence",
            "task_id",
            "robot_name",
            "event",
            "last_completed_step_index",
            "cargo_state",
            "business_completed",
            "message",
            "reported_at",
        }
        missing = sorted(field for field in required if field not in self.model_fields_set)
        if missing:
            raise ValueError(f"scenario callback missing fields: {', '.join(missing)}")
        if (
            not self.event_id
            or self.sequence is None
            or self.task_id is None
            or not self.robot_name
            or not self.event
            or self.business_completed is None
            or self.message is None
            or self.reported_at is None
        ):
            raise ValueError("scenario callback required fields cannot be null")
        events = {
            "COMMAND_ACCEPTED",
            "COMMAND_RUNNING",
            "STEP_STARTED",
            "STEP_COMPLETED",
            "BUSINESS_COMPLETED",
            "COMMAND_DONE",
            "COMMAND_FAILED",
            "COMMAND_ABORTED",
            "COMMAND_STOPPED",
            "COMMAND_CANCELLED",
        }
        event = str(self.event or "").upper()
        if event not in events:
            raise ValueError("invalid scenario callback event")
        if self.cargo_state not in {"EMPTY", "LOADED", "UNKNOWN"}:
            raise ValueError("invalid scenario cargo_state")
        step_codes = (
            "LEAVE_HOME",
            "PICKUP_APPROACH",
            "PICKUP_ALIGN",
            "LOAD",
            "TRANSPORT",
            "DROPOFF_ALIGN",
            "UNLOAD",
            "RETURN_HOME",
            "PARK",
        )
        if event in {"STEP_STARTED", "STEP_COMPLETED"}:
            if self.current_step_index is None or self.current_step_code is None:
                raise ValueError("scenario step callback requires current step")
            if step_codes[self.current_step_index] != self.current_step_code:
                raise ValueError("scenario current_step_index/code mismatch")
        if event == "STEP_COMPLETED" and self.current_step_code == "LOAD" and self.cargo_state != "LOADED":
            raise ValueError("scenario LOAD completion requires LOADED cargo")
        if (
            event == "STEP_COMPLETED"
            and self.current_step_code == "UNLOAD"
            and not (
                self.cargo_state == "EMPTY" and self.business_completed is True and self.last_completed_step_index == 6
            )
        ):
            raise ValueError("scenario UNLOAD completion requires EMPTY completed cargo")
        if event == "BUSINESS_COMPLETED" and not (
            self.current_step_index == 6
            and self.current_step_code == "UNLOAD"
            and self.last_completed_step_index == 6
            and self.cargo_state == "EMPTY"
            and self.business_completed is True
        ):
            raise ValueError("scenario BUSINESS_COMPLETED requires completed UNLOAD and EMPTY cargo")
        if self.business_completed:
            if self.cargo_state != "EMPTY" or (self.last_completed_step_index or -1) < 6:
                raise ValueError("business_completed requires UNLOAD and EMPTY cargo")
        terminal = {
            "COMMAND_DONE",
            "COMMAND_FAILED",
            "COMMAND_ABORTED",
            "COMMAND_STOPPED",
            "COMMAND_CANCELLED",
        }
        if event in terminal:
            terminal_required = {"navigator_status", "is_emergency", "authority_owner", "authority_released"}
            missing_terminal = sorted(field for field in terminal_required if field not in self.model_fields_set)
            if missing_terminal:
                raise ValueError(f"scenario terminal callback missing fields: {', '.join(missing_terminal)}")
        if event in {"COMMAND_FAILED", "COMMAND_ABORTED"} and not self.reason_code:
            raise ValueError("scenario failure callback requires reason_code")
        if event == "COMMAND_DONE" and not (
            self.current_step_index == 8
            and self.current_step_code == "PARK"
            and self.last_completed_step_index == 8
            and self.cargo_state == "EMPTY"
            and self.business_completed is True
            and self.navigator_status == "IDLE"
            and self.is_emergency is False
            and self.authority_owner == "MAIN"
            and self.authority_released is True
        ):
            raise ValueError("scenario COMMAND_DONE completion gate failed")

    def to_payload(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class MovementRobotStatusCallback(BaseModel):
    """Movement robot status callback; identity comes from the URL path."""

    model_config = ConfigDict(extra="allow")
    state: str | None = None
    current_command_id: str | None = None
    localized: bool | None = None
    is_emergency: bool | None = None
    pose: dict[str, Any] | None = None
    reported_at: datetime | None = None

    @model_validator(mode="after")
    def validate_status_content(self) -> Self:
        if (
            self.state is None
            and self.current_command_id is None
            and self.localized is None
            and self.pose is None
            and self.is_emergency is None
        ):
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
