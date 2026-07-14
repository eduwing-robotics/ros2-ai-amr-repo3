"""Robot management routes."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.db.connection import transaction
from app.db.postgres import event_repo, robot_repo
from app.models.schemas import ApiMessage, Robot, RobotUpsert

router = APIRouter(tags=["robots"])


@router.get("/robots", response_model=list[Robot])
def list_robots() -> list[Robot]:
    """로봇 목록."""
    with transaction() as conn:
        return [
            Robot(**r)
            for r in robot_repo.list(
                conn,
            )
        ]


@router.post("/robots", response_model=ApiMessage)
def upsert_robot(payload: RobotUpsert) -> ApiMessage:
    """DB 관리 화면에서 로봇을 생성하거나 수정한다."""
    with transaction() as conn:
        robot_repo.upsert(conn, payload.model_dump())
        event_repo.append(
            conn,
            event_type="DB_ROBOT_UPSERT",
            robot_id=payload.robot_id,
            message=f"robot upserted: {payload.robot_id}",
            payload=payload.model_dump(),
        )
    return ApiMessage(message="robot saved")


@router.delete("/robots/{robot_id}", response_model=ApiMessage)
def delete_robot(robot_id: str) -> ApiMessage:
    """DB 관리 화면에서 로봇을 삭제한다."""
    with transaction() as conn:
        deleted = robot_repo.delete(conn, robot_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="robot not found")
        event_repo.append(
            conn,
            event_type="DB_ROBOT_DELETE",
            robot_id=robot_id,
            message=f"robot deleted: {robot_id}",
            payload={"robot_id": robot_id},
        )
    return ApiMessage(message="robot deleted")
