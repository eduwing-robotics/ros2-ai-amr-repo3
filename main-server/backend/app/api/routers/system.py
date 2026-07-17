"""System status and external config routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.config import settings
from app.db.connection import transaction
from app.db.repo_bridge import (
    camera_repo,
    event_repo,
    movement_repo,
    robot_repo,
    task_repo,
)
from app.models.schemas import CameraSource, MovementCommand, Robot, StatusSnapshot, Task
from app.services.camera_config import apply_camera_stream_defaults, camera_system_config
from app.services.movement import movement_client
from app.services.movement_health import battery_from_health, get_movement_health
from app.services.vision_proxy import fetch_camera_health

router = APIRouter(tags=["system"])


def _estop_summary(robots: list[Robot], health: dict) -> dict:
    """Summarize fleet E-stop state without treating offline robots as clear."""
    rows = []
    for robot in robots:
        snapshot = health.get(robot.robot_id) or {}
        if snapshot.get("is_emergency") is True:
            state = "active"
        elif snapshot.get("estop_state") == "disabled":
            state = "disabled"
        elif snapshot.get("estop_state") != "clear":
            state = "unknown"
        elif not snapshot.get("ok") or snapshot.get("robot_online") is False:
            state = "unknown"
        else:
            state = "clear"
        rows.append({"robot_id": robot.robot_id, "state": state})
    states = {row["state"] for row in rows}
    state = "active" if "active" in states else "unknown" if "unknown" in states else "clear" if "clear" in states else "disabled"
    return {"state": state, "partial": len(states - {"disabled"}) > 1 or "unknown" in states, "robots": rows}


def _sync_battery_from_health(robots: list[Robot], health: dict) -> None:
    """movement /health가 실어준 배터리를 DB에 반영하고 응답 객체도 즉시 갱신한다.

    이동서버가 battery를 안 주면(대부분의 현 상태) no-op — 기존 정적 값을 유지한다.
    """
    updates = {
        robot.robot_id: pct
        for robot in robots
        if (pct := battery_from_health(health.get(robot.robot_id) or {})) is not None
        and pct != robot.battery
    }
    if not updates:
        return
    with transaction() as conn:
        repo = robot_repo(conn)
        for robot_id, pct in updates.items():
            repo.set_battery(robot_id, pct)
    for robot in robots:
        if robot.robot_id in updates:
            robot.battery = updates[robot.robot_id]


@router.get("/system/external-config")
def external_config(request: Request) -> dict:
    """현재 Main 서버가 사용하는 외부 API endpoint 설정을 반환한다."""
    return {
        "public_base_url": settings.public_base_url or str(request.base_url).rstrip("/"),
        "api_callback_base_url": settings.api_callback_base_url(str(request.base_url).rstrip("/")),
        "movement": {
            "mode": settings.movement_client_mode,
            "base_urls": settings.movement_base_urls,
            "active_map_id": settings.movement_active_map_id,
        },
        "camera": {
            "host": settings.camera_host,
            "api_base_url": settings.camera_api_base_url,
            "rosbridge_url": settings.camera_rosbridge_url,
            "stream_url_template": settings.camera_stream_url_template,
        },
        "vision": {
            "api_base_url": settings.vision_api_base_url,
            "stream_base_url": settings.vision_stream_base_url,
        },
    }


@router.get("/status", response_model=StatusSnapshot)
def status() -> StatusSnapshot:
    """LMS 첫 화면용 snapshot."""
    with transaction() as conn:
        robots = [Robot(**r) for r in robot_repo(conn).list()]
        cameras = apply_camera_stream_defaults([CameraSource(**c) for c in camera_repo(conn).list()])
        commands = [MovementCommand(**c) for c in movement_repo(conn).list(limit=20)]
        events = event_repo(conn).list(limit=30)
        tasks = [Task(**t) for t in task_repo(conn).list(limit=30)]

    movement_health = get_movement_health([robot.robot_id for robot in robots])
    _sync_battery_from_health(robots, movement_health)

    return StatusSnapshot(
        system={
            "mode": "MANUAL",
            "movement_mode": movement_client.mode,
            "estop": _estop_summary(robots, movement_health),
            "camera_mode": "configured",
            "camera": camera_system_config(),
            "camera_health": fetch_camera_health([c.source_id for c in cameras]),
            "vision": {
                "api_base_url": settings.vision_api_base_url,
                "stream_base_url": settings.vision_stream_base_url,
            },
        },
        movement_health=movement_health,
        robots=robots,
        camera_sources=cameras,
        movement_commands=commands,
        events=events,
        tasks=tasks,
    )
