"""Records and audit read routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.db.connection import transaction
from app.db.mvp import (
    event_repo,
    evidence_repo,
    item_change_log_repo,
    movement_repo,
    task_log_repo,
)
from app.models.schemas import (
    EvidenceEventRecord,
    ItemChangeLogRecord,
    MovementCommand,
    TaskLogRecord,
    TimelineEvent,
)

router = APIRouter(tags=["records"])


@router.get("/events", response_model=list[TimelineEvent])
def list_events(limit: int = Query(default=50, ge=1, le=200)) -> list[TimelineEvent]:
    """감사 타임라인 — evidence_events (source=runtime)."""
    with transaction() as conn:
        return [
            TimelineEvent(
                event_id=e.get("event_id"),
                event_type=e["event_type"],
                task_id=e.get("task_id"),
                robot_id=e.get("robot_id"),
                command_id=e.get("command_id"),
                message=e.get("message", ""),
                payload=e.get("payload_json") or {},
                created_at=e.get("created_at"),
                layer="dbml",
                source="runtime",
            )
            for e in event_repo(conn).list(limit=limit)
        ]


@router.get("/task-logs", response_model=list[TaskLogRecord])
def list_task_logs(limit: int = Query(default=50, ge=1, le=200)) -> list[TaskLogRecord]:
    """완료/실패 task 감사 로그."""
    with transaction() as conn:
        return [TaskLogRecord(**r) for r in task_log_repo(conn).list(limit=limit)]


@router.get("/item-change-logs", response_model=list[ItemChangeLogRecord])
def list_item_change_logs(limit: int = Query(default=50, ge=1, le=200)) -> list[ItemChangeLogRecord]:
    """재고 변경 이력."""
    with transaction() as conn:
        return [ItemChangeLogRecord(**r) for r in item_change_log_repo(conn).list(limit=limit)]


@router.get("/evidence-events", response_model=list[EvidenceEventRecord])
def list_evidence_events(limit: int = Query(default=50, ge=1, le=200)) -> list[EvidenceEventRecord]:
    """evidence_events 원본 목록."""
    with transaction() as conn:
        return [EvidenceEventRecord(**r) for r in evidence_repo(conn).list(limit=limit)]


@router.get("/movement-commands", response_model=list[MovementCommand])
def list_movement_commands(limit: int = Query(default=50, ge=1, le=200)) -> list[MovementCommand]:
    """이동 명령 — evidence_events derived."""
    with transaction() as conn:
        rows = movement_repo(conn).list(limit=limit)
        return [MovementCommand(**{k: v for k, v in c.items() if k in MovementCommand.model_fields}) for c in rows]
