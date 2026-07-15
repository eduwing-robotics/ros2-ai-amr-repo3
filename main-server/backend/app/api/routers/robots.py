"""Robot management routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db.connection import transaction
from app.db.repo_bridge import event_repo, robot_repo
from app.models.schemas import ApiMessage, Robot, RobotUpsert
from app.services.pose_runtime import pose_runtime

router = APIRouter(tags=["robots"])


@router.get("/robots", response_model=list[Robot])
def list_robots() -> list[Robot]:
    """로봇 목록."""
    with transaction() as conn:
        return [Robot(**r) for r in robot_repo(conn).list()]


@router.post("/robots", response_model=ApiMessage)
def upsert_robot(payload: RobotUpsert) -> ApiMessage:
    """DB 관리 화면에서 로봇을 생성하거나 수정한다."""
    with transaction() as conn:
        robots = robot_repo(conn)
        current = robots.get(payload.robot_id)
        if current and current.get("enabled", True) and payload.enabled is False:
            if reason := robots.disable_block_reason(payload.robot_id):
                raise HTTPException(status_code=409, detail=reason)
        robots.upsert(payload.model_dump())
        event_repo(conn).append(
            event_type="DB_ROBOT_UPSERT",
            robot_id=payload.robot_id,
            message=f"robot upserted: {payload.robot_id}",
            payload=payload.model_dump(),
        )
    effective_enabled = payload.enabled if payload.enabled is not None else current.get("enabled", True) if current else True
    if effective_enabled:
        pose_runtime.register_robot(payload.robot_id)
    else:
        pose_runtime.unregister_robot(payload.robot_id)
    return ApiMessage(message="robot saved")


@router.delete("/robots/{robot_id}", response_model=ApiMessage)
def delete_robot(robot_id: str) -> ApiMessage:
    """DB 관리 화면에서 로봇을 삭제한다."""
    with transaction() as conn:
        deleted = robot_repo(conn).delete(robot_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="robot not found")
        event_repo(conn).append(
            event_type="DB_ROBOT_DELETE",
            robot_id=robot_id,
            message=f"robot deleted: {robot_id}",
            payload={"robot_id": robot_id},
        )
    pose_runtime.unregister_robot(robot_id)
    return ApiMessage(message="robot deleted")
