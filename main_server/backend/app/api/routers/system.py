"""System status and external config routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.config import settings
from app.db.connection import transaction
from app.db.postgres import cameras as postgres_cameras
from app.db.postgres import operational_events
from app.db.postgres import robots as postgres_robots
from app.db.postgres import tasks as postgres_tasks
from app.domains.movement.client import movement_client
from app.domains.movement.health import battery_from_health, get_movement_health
from app.domains.records import movement_commands
from app.domains.vision.cameras import apply_camera_stream_defaults, camera_system_config
from app.domains.vision.client import fetch_camera_health
from app.models.movement import RobotCommandRecord
from app.models.records import CameraSource, ControlSystemStatusSnapshot
from app.models.robots import Robot
from app.models.tasks import RobotTask

router = APIRouter(tags=["system"])


def _sync_battery_from_health(robots: list[Robot], health: dict) -> None:
    """movement /health가 실어준 배터리를 DB에 반영하고 응답 객체도 즉시 갱신한다.

    이동서버가 battery를 안 주면(대부분의 현 상태) no-op — 기존 정적 값을 유지한다.
    """
    updates = {
        robot.robot_id: pct
        for robot in robots
        if (pct := battery_from_health(health.get(robot.robot_id) or {})) is not None and pct != robot.battery
    }
    if not updates:
        return
    with transaction() as conn:
        for robot_id, pct in updates.items():
            postgres_robots.set_battery(conn, robot_id, pct)
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
            "mode": "http",
            "fallback_base_url": settings.movement_base_url,
            "base_urls": settings.movement_base_urls,
            "active_map_id": settings.movement_active_map_id,
            "callback_auth_required": bool(settings.movement_callback_token),
            "callback_auth_header": "X-Movement-Callback-Token",
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
            "api_fallback_base_url": settings.vision_api_fallback_base_url,
            "stream_fallback_base_url": settings.vision_stream_fallback_base_url,
        },
    }


@router.get("/status", response_model=ControlSystemStatusSnapshot)
def status() -> ControlSystemStatusSnapshot:
    """LMS 첫 화면용 snapshot."""
    with transaction() as conn:
        robots = [
            Robot(**r)
            for r in postgres_robots.list_robots(
                conn,
            )
        ]
        cameras = apply_camera_stream_defaults(
            [
                CameraSource(**c)
                for c in postgres_cameras.list_cameras(
                    conn,
                )
            ]
        )
        commands = [RobotCommandRecord(**c) for c in movement_commands.list_movement_command_records(conn, limit=20)]
        events = operational_events.list_operational_events(conn, limit=30)
        tasks = [RobotTask(**t) for t in postgres_tasks.list_tasks(conn, limit=30)]

    movement_health = get_movement_health([robot.robot_id for robot in robots])
    _sync_battery_from_health(robots, movement_health)

    return ControlSystemStatusSnapshot(
        system={
            "mode": "MANUAL",
            "movement_mode": movement_client.mode,
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
