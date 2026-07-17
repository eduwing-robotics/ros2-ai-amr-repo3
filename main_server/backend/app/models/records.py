"""Audit, evidence, and status snapshot schemas."""

from typing import Any

from pydantic import BaseModel, Field

from app.models.movement import RobotCommandRecord
from app.models.robots import Robot
from app.models.tasks import RobotTask


class CameraSource(BaseModel):
    """카메라 skeleton source."""

    source_id: str
    label: str
    robot_id: str | None = None
    status: str = "not_connected"
    stream_url: str | None = None
    last_frame_age_s: float | None = None


class CameraSourceUpsert(BaseModel):
    """DB 관리 화면에서 카메라 source를 생성/수정할 때 쓰는 요청."""

    source_id: str
    label: str
    robot_id: str | None = None
    status: str = "not_connected"
    stream_url: str | None = None


class TimelineEvent(BaseModel):
    """통합 이벤트 타임라인 항목 (compat events 또는 evidence_events)."""

    event_id: int | None = None
    event_type: str
    task_id: int | None = None
    robot_id: str | None = None
    command_id: str | None = None
    message: str = ""
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    source: str | None = None
    layer: str | None = None


class TaskLogRecord(BaseModel):
    """완료/실패 task 감사 로그 (task_logs)."""

    id: int
    task_id: int
    task_type: str
    result: str
    result_evidence_type: str | None = None
    started_at: str | None = None
    finished_at: str | None = None
    error_reason: str | None = None
    summary: str | None = None
    logged_at: str | None = None


class ItemChangeLogRecord(BaseModel):
    """재고 변경 이력 (item_change_logs)."""

    id: int
    task_id: int | None = None
    item_code: str
    slot_id: str | None = None
    floor: int | None = None
    event_type: str
    quantity_change: int
    quantity_before: int | None = None
    quantity_after: int | None = None
    reason: str | None = None
    changed_at: str | None = None


class EvidenceEventRecord(BaseModel):
    """런타임 evidence (evidence_events)."""

    id: int
    task_id: int | None = None
    command_id: int | None = None
    event_type: str
    source: str
    confidence: float | None = None
    severity: str = "INFO"
    trusted: bool = False
    image_url: str | None = None
    data_json: dict[str, Any] = Field(default_factory=dict)
    observed_at: str | None = None


class ControlSystemStatusSnapshot(BaseModel):
    """LMS 관제 화면 snapshot."""

    system: dict[str, Any]
    movement_health: dict[str, dict[str, Any]] = Field(default_factory=dict)
    robots: list[Robot]
    camera_sources: list[CameraSource]
    movement_commands: list[RobotCommandRecord]
    events: list[dict[str, Any]]
    tasks: list[RobotTask] = Field(default_factory=list)
