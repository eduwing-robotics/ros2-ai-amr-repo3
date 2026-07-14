"""External communication diagnostics routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.core.api_logs import list_logs as list_api_logs
from app.db.connection import transaction
from app.db.postgres import camera_repo, movement_repo, robot_repo
from app.domains.movement.health import get_movement_health
from app.domains.vision.client import fetch_camera_health
from app.models.schemas import Robot, RobotCommandRecord

router = APIRouter(prefix="/comm", tags=["comm"])


@router.get("/logs")
def comm_logs(
    service: str | None = Query(default=None, pattern="^(movement|camera|vision)$"),
    limit: int = Query(default=120, ge=1, le=300),
) -> dict:
    """Movement/Camera/Vision 외부 API 통신 로그를 조회한다."""
    cap = min(limit, 100)
    with transaction() as conn:
        movement_commands = [
            RobotCommandRecord(**{k: v for k, v in c.items() if k in RobotCommandRecord.model_fields})
            for c in movement_repo.list(conn, limit=cap)
        ]
        robots = [
            Robot(**r)
            for r in robot_repo.list(
                conn,
            )
        ]
    logs = list_api_logs(service=service, limit=limit)
    return {
        "logs": logs,
        "movement_commands": movement_commands,
        "counts": {
            "logs": len(logs),
            "movement_commands": len(movement_commands),
        },
        "robots": robots,
    }


@router.post("/probe/movement")
def probe_movement() -> dict:
    """로봇별 Movement health API를 즉시 호출한다. 이동 명령은 보내지 않는다."""
    with transaction() as conn:
        robots = [
            Robot(**r)
            for r in robot_repo.list(
                conn,
            )
        ]
    return {"movement_health": get_movement_health([robot.robot_id for robot in robots], force=True)}


@router.post("/probe/camera")
def probe_camera() -> dict:
    """Camera health를 cache 없이 즉시 확인한다(status와 같은 OR 판정)."""
    with transaction() as conn:
        camera_sources = [
            c["source_id"]
            for c in camera_repo.list(
                conn,
            )
        ]
    health = fetch_camera_health(camera_sources, force=True)
    return {
        **health,
        # Existing frontend uses content_type truthiness for the retry toast.
        "content_type": "application/json" if health.get("ok") else None,
    }
