"""Shared Movement diagnostics and pose helpers for API routers."""

from __future__ import annotations

from fastapi import HTTPException

from app.core.config import settings
from app.db.connection import transaction
from app.db.repo_bridge import event_repo, map_repo, robot_repo
from app.models.schemas import RobotPoseUpdate
from app.services.movement import MovementClientError, movement_client
from app.services.movement_health import base_url_for, get_movement_health
from app.services.runtime_map_context import get_runtime_map_context, resolve_command_map


def movement_reason(health: dict, pose_payload: dict | None = None) -> tuple[str, str | None]:
    """Movement health/pose를 운영자가 이해할 수 있는 reason/action으로 정규화한다."""
    pose_payload = pose_payload or {}
    pose = pose_payload.get("pose") if pose_payload else health.get("pose")
    localized = bool(pose_payload.get("localized", health.get("localized", False)))
    if not health.get("ok"):
        return "movement_api_unreachable", "check_movement_server"
    if health.get("robot_online") is False:
        return "robot_offline", "check_robot_bringup"
    if health.get("is_emergency"):
        return "emergency_stop", "clear_emergency"
    if not localized or not pose:
        if health.get("localization_required", True):
            return "initial_pose_required", "set_initial_pose"
        return "amcl_pose_not_received", "check_localization"
    if health.get("command_accepting") is False:
        return "command_not_accepting", "check_nav_state"
    return "ok", None


def pose_state(pose: dict | None) -> str:
    if not pose:
        return "missing"
    age = pose.get("age_sec")
    if age is None:
        return "unknown"
    try:
        age_value = float(age)
    except (TypeError, ValueError):
        return "unknown"
    if age_value > 5:
        return "lost"
    if age_value > 2:
        return "stale"
    return "live"


def map_record_by_id(map_id: str | None) -> dict | None:
    if not map_id:
        return None
    with transaction() as conn:
        for item in map_repo(conn).list():
            if item["map_id"] == map_id:
                return item
    return None


def fallback_map_state(error: str | None = None) -> dict:
    active_map_id = settings.movement_active_map_id
    record = map_record_by_id(active_map_id)
    payload = {
        "ok": error is None,
        "active_map_id": active_map_id,
        "frame_id": (record or {}).get("frame_id", "map"),
        "resolution": (record or {}).get("resolution"),
        "origin": [
            (record or {}).get("origin_x", 0.0),
            (record or {}).get("origin_y", 0.0),
            (record or {}).get("origin_yaw", 0.0),
        ],
        "width": (record or {}).get("width"),
        "height": (record or {}).get("height"),
        "source": "main_config_fallback",
    }
    if error:
        payload["error"] = error
        payload["reason"] = "movement_map_state_unavailable"
    return payload


def movement_map_state() -> dict:
    return get_runtime_map_context().to_map_state()


def runtime_map_context_route() -> dict:
    """PHASE_21 — Movement runtime map context 단일 조회."""
    return get_runtime_map_context().to_map_state()


def assert_movement_active_map(map_id: str) -> dict:
    """LMS map이 Movement active map과 일치하는지 확인하고 map-state를 반환한다."""
    _, state = resolve_movement_map_id(map_id)
    return state


def resolve_movement_map_id(lms_map_id: str, *, robot_id: str | None = None) -> tuple[str, dict]:
    """Resolve a command map against the receiving robot's live Nav map."""
    runtime_map_id, ctx, _info = resolve_command_map(lms_map_id, robot_id=robot_id)
    return runtime_map_id, ctx.to_map_state()


def localization_snapshot(robot_id: str) -> dict:
    health = get_movement_health([robot_id]).get(robot_id, {})
    try:
        localization = movement_client.localization(robot_id)
        localization_source = "movement_localization"
    except MovementClientError as exc:
        localization = {"error": str(exc)}
        localization_source = "health_pose_fallback"
        try:
            pose_payload = movement_client.robot_pose(robot_id)
        except MovementClientError as pose_exc:
            pose_payload = {"error": str(pose_exc), "localized": health.get("localized", False), "pose": health.get("pose")}
        localization.update(pose_payload)
    pose = localization.get("pose") or health.get("pose")
    reason, action = movement_reason(health, localization)
    return {
        "robot_id": robot_id,
        "robot_name": localization.get("robot_name") or health.get("robot_name") or robot_id,
        "ok": bool(health.get("ok")),
        "base_url": health.get("base_url") or base_url_for(robot_id),
        "robot_online": health.get("robot_online"),
        "command_accepting": health.get("command_accepting"),
        "localized": bool(localization.get("localized", health.get("localized", False))),
        "localization_required": health.get("localization_required", True),
        "pose": pose,
        "pose_state": pose_state(pose),
        "reason": localization.get("reason") if localization.get("reason") not in {None, "unknown"} else reason,
        "action_required": action,
        "health": health,
        "localization": localization,
        "source": localization_source,
    }


def report_pose_for_robot(conn, robot_id: str, payload: RobotPoseUpdate, source: str | None = None) -> None:
    """Pose report — DBML에 pose 컬럼 없음: robots.last_seen_at 갱신만 (PHASE_62-D)."""
    if not robot_repo(conn).exists(robot_id):
        raise HTTPException(status_code=404, detail="robot not found")
    robot_repo(conn).touch(robot_id)
    event_repo(conn).append(
        event_type="POSE_REPORT",
        robot_id=robot_id,
        message=f"pose report {robot_id}",
        payload={
            "robot_id": robot_id,
            "map_id": payload.map_id,
            "x": payload.x,
            "y": payload.y,
            "yaw": payload.yaw,
            "source": source or payload.source,
        },
    )
