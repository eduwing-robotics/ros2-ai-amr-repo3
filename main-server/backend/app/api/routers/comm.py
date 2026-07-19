"""External communication diagnostics routes."""

from __future__ import annotations

from fastapi import APIRouter, Query

from app.db.connection import transaction
from app.db.repo_bridge import camera_repo, movement_repo, robot_repo
from app.models.schemas import MovementCommand, Robot
from app.services.api_logs import list_logs as list_api_logs
from app.services.api_logs import list_poll_metrics
from app.services.movement_health import get_movement_health
from app.services.vision_proxy import fetch_camera_health

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
            MovementCommand(**{k: v for k, v in c.items() if k in MovementCommand.model_fields})
            for c in movement_repo(conn).list(limit=cap)
        ]
        robots = [Robot(**r) for r in robot_repo(conn).list()]
    logs = list_api_logs(service=service, limit=limit)
    poll_metrics = list_poll_metrics(service=service)
    return {
        "logs": logs,
        "poll_metrics": poll_metrics,
        "movement_commands": movement_commands,
        "counts": {
            "logs": len(logs),
            "movement_commands": len(movement_commands),
            "poll_metrics": len(poll_metrics),
        },
        "robots": robots,
    }


@router.post("/probe/movement")
def probe_movement() -> dict:
    """로봇별 Movement health API를 즉시 호출한다. 이동 명령은 보내지 않는다."""
    with transaction() as conn:
        robots = [Robot(**r) for r in robot_repo(conn).list()]
    return {"movement_health": get_movement_health([robot.robot_id for robot in robots], force=True)}


@router.post("/probe/camera")
def probe_camera() -> dict:
    """Camera health를 cache 없이 즉시 확인한다(status와 같은 OR 판정)."""
    with transaction() as conn:
        camera_sources = [c["source_id"] for c in camera_repo(conn).list()]
    health = fetch_camera_health(camera_sources, force=True)
    return {
        **health,
        # Existing frontend uses content_type truthiness for the retry toast.
        "content_type": "application/json" if health.get("ok") else None,
    }
