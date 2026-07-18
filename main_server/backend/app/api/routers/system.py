"""System status and external config routes."""

from __future__ import annotations

from fastapi import APIRouter, Request

from app.core.config import settings
from app.db.connection import transaction
from app.db.postgres import cameras as postgres_cameras
from app.db.postgres import operational_events, runtime_records
from app.db.postgres import robots as postgres_robots
from app.db.postgres import tasks as postgres_tasks
from app.domains.movement.client import movement_client
from app.domains.movement.health import battery_from_health, get_movement_health
from app.domains.vision.cameras import apply_camera_stream_defaults, camera_system_config
from app.domains.vision.client import fetch_camera_health
from app.models.records import CameraSource, ControlSystemStatusSnapshot
from app.models.robots import Robot
from app.models.tasks import RobotTask

router = APIRouter(tags=["system"])


def _estop_summary(robots: list[Robot], health: dict, persisted: dict[str, str] | None = None) -> dict:
    enabled_ids = [robot.robot_id for robot in robots if robot.enabled]
    active: list[str] = []
    unknown: list[str] = []
    robot_states: dict[str, str] = {}
    persisted = persisted or {}
    for robot_id in enabled_ids:
        snapshot = health.get(robot_id) or {}
        online = bool(snapshot.get("ok")) and snapshot.get("robot_online") is not False
        lifecycle = persisted.get(robot_id)
        if snapshot.get("is_emergency"):
            if online:
                state = "stop_confirmed"
                active.append(robot_id)
            else:
                state = lifecycle or "stop_unconfirmed"
                unknown.append(robot_id)
        elif lifecycle in {"stop_requested", "stop_unconfirmed", "clear_requested", "clear_unconfirmed"}:
            state = lifecycle
            unknown.append(robot_id)
        else:
            state = "clear_confirmed" if lifecycle == "clear_confirmed" else "clear"
        robot_states[robot_id] = state
    state = "active" if active else "unknown" if unknown else "clear"
    return {"state": state, "active_robots": active, "unknown_robots": unknown, "robot_states": robot_states}


def _sync_battery_from_health(robots: list[Robot], health: dict) -> None:
    """movement /health가 실어준 배터리를 DB에 반영하고 응답 객체도 즉시 갱신한다.

    이동서버가 battery를 안 주면 DB의 과거 정적값을 완충으로 오인하지 않도록
    운영 상태 응답에서는 None으로 표시한다. DB 원본은 실제 값 수신 전까지 보존한다.
    """
    updates: dict[str, int] = {}
    for robot in robots:
        pct = battery_from_health(health.get(robot.robot_id) or {})
        if pct is None:
            robot.battery = None
        elif pct != robot.battery:
            updates[robot.robot_id] = pct
    if not updates:
        return
    with transaction() as conn:
        for robot_id, pct in updates.items():
            postgres_robots.set_battery(conn, robot_id, pct)
    for robot in robots:
        if robot.robot_id in updates:
            robot.battery = updates[robot.robot_id]


def _apply_camera_runtime_states(cameras: list[CameraSource], camera_health: dict) -> None:
    bridge = camera_health.get("bridge") or {}
    response = bridge.get("response") or {}
    runtime_sources = {
        str(source.get("source_id")): source for source in response.get("sources") or [] if source.get("source_id")
    }
    for camera in cameras:
        runtime = runtime_sources.get(camera.source_id)
        if not runtime:
            camera.status = "offline"
            camera.last_frame_age_s = None
            continue
        camera.status = str(runtime.get("status") or "unknown").lower()
        age = runtime.get("last_frame_age_s")
        camera.last_frame_age_s = float(age) if age is not None else None


ACTIVE_TASK_STATES = {"RUNNING", "ASSIGNED", "AWAITING_OPERATOR", "RECOVERY_REQUIRED"}
RECOVERY_TASK_STATES = {"AWAITING_OPERATOR", "RECOVERY_REQUIRED"}


def _derive_robot_operational_state(robot: Robot, snapshot: dict, estop_state: str | None) -> tuple[str, str, bool]:
    """Derive the operator-facing state without overwriting the DB task state."""
    task_state = str(robot.status or "UNKNOWN").upper()
    if robot.enabled is False:
        return "NOT_IN_USE", "robot_disabled", False
    if snapshot.get("is_emergency") or str(estop_state or "").startswith("stop_"):
        return "ESTOP", "emergency_stop_active", False
    if not snapshot or not snapshot.get("ok") or snapshot.get("robot_online") is False:
        return "OFFLINE", "movement_or_robot_offline", False
    if snapshot.get("localized") is False:
        return "FAULT", "localization_lost", False
    if snapshot.get("fault") or snapshot.get("error_code"):
        return "FAULT", str(snapshot.get("error_code") or "movement_fault"), False
    if snapshot.get("command_accepting") is False:
        return "NOT_READY", "command_not_accepting", False
    if snapshot.get("nav2_ready") is False:
        return "NOT_READY", "nav2_not_ready", False
    if task_state in RECOVERY_TASK_STATES:
        return "RECOVERY", "task_recovery_required", False
    if task_state == "RUNNING":
        return "RUNNING", "task_running", True
    if task_state == "ASSIGNED":
        return "ASSIGNED", "task_assigned", True
    if task_state == "IDLE":
        return "IDLE", "ready_no_active_task", True
    if task_state in ACTIVE_TASK_STATES:
        return "RECOVERY", "task_state_requires_attention", False
    return "UNKNOWN", "state_not_classified", False


def _apply_robot_operational_states(
    robots: list[Robot], health: dict, estop_states: dict[str, str], recovery_robot_ids: set[str]
) -> None:
    for robot in robots:
        robot.task_status = str(robot.status or "UNKNOWN").upper()
        state, reason, command_enabled = _derive_robot_operational_state(
            robot, health.get(robot.robot_id) or {}, estop_states.get(robot.robot_id)
        )
        if robot.robot_id in recovery_robot_ids and state in {"RUNNING", "ASSIGNED", "IDLE"}:
            state, reason, command_enabled = "RECOVERY", "task_recovery_required", False
        robot.operational_status = state
        robot.operational_reason = reason
        robot.command_enabled = command_enabled


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
        tasks = [RobotTask(**t) for t in postgres_tasks.list_tasks(conn, limit=30)]
        estop_states = operational_events.latest_estop_states(conn, [robot.robot_id for robot in robots])
        recovery_robot_ids = {
            str(task.assigned_robot_id)
            for task in tasks
            if task.assigned_robot_id
            and task.status.value == "RUNNING"
            and str((runtime_records.get_orchestration(conn, task.task_id) or {}).get("phase") or "").upper()
            in {"AWAITING_OPERATOR", "RECOVERY_RUNNING"}
        }

    movement_health = get_movement_health([robot.robot_id for robot in robots])
    _sync_battery_from_health(robots, movement_health)
    _apply_robot_operational_states(robots, movement_health, estop_states, recovery_robot_ids)
    camera_health = fetch_camera_health([c.source_id for c in cameras])
    _apply_camera_runtime_states(cameras, camera_health)

    return ControlSystemStatusSnapshot(
        system={
            "mode": "MANUAL",
            "estop_summary": _estop_summary(robots, movement_health, estop_states),
            "movement_mode": movement_client.mode,
            "camera_mode": "configured",
            "camera": camera_system_config(),
            "camera_health": camera_health,
            "vision": {
                "api_base_url": settings.vision_api_base_url,
                "stream_base_url": settings.vision_stream_base_url,
            },
        },
        movement_health=movement_health,
        robots=robots,
        camera_sources=cameras,
    )
