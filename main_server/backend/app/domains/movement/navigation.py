"""Movement runtime map context — Nav2 active map authority for manual ops."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.core.config import settings
from app.db.postgres import robot_poses, robots
from app.domains.maps.assets import list_map_asset_records
from app.domains.movement.client import MovementClientError, movement_client
from app.domains.movement.health import base_url_for, get_movement_health
from app.models.robots import RobotPoseUpdate


class RuntimeMapContext(BaseModel):
    """Movement/Nav2가 현재 사용 중인 맵 좌표계."""

    ok: bool = False
    active_map_id: str | None = None
    frame_id: str = "map"
    resolution: float | None = None
    origin: list[float] = Field(default_factory=lambda: [0.0, 0.0, 0.0])
    width: int | None = None
    height: int | None = None
    source: str = "unknown"
    confidence: str = "live"
    reported_at: str | None = None
    error: str | None = None

    def to_map_state(self) -> dict[str, Any]:
        return self.model_dump()


def _from_movement_payload(payload: dict[str, Any]) -> RuntimeMapContext:
    origin = payload.get("origin") or [0.0, 0.0, 0.0]
    origin = (list(origin) + [0.0, 0.0, 0.0])[:3]
    return RuntimeMapContext(
        ok=True,
        active_map_id=str(payload.get("active_map_id") or ""),
        frame_id=str(payload.get("frame_id") or "map"),
        resolution=float(payload["resolution"]) if payload.get("resolution") is not None else None,
        origin=[float(origin[0]), float(origin[1]), float(origin[2])],
        width=int(payload["width"]) if payload.get("width") is not None else None,
        height=int(payload["height"]) if payload.get("height") is not None else None,
        source=str(payload.get("source") or "movement"),
        confidence="live",
        reported_at=payload.get("reported_at"),
    )


def _from_db_fallback(error: str | None = None) -> RuntimeMapContext:
    active_map_id = settings.movement_active_map_id
    record = map_record_by_id(active_map_id) or {}
    return RuntimeMapContext(
        ok=error is None,
        active_map_id=active_map_id or None,
        frame_id=str(record.get("frame_id") or "map"),
        resolution=float(record["resolution"]) if record.get("resolution") is not None else None,
        origin=[
            float(record.get("origin_x", 0.0)),
            float(record.get("origin_y", 0.0)),
            float(record.get("origin_yaw", 0.0)),
        ],
        width=int(record["width"]) if record.get("width") else None,
        height=int(record["height"]) if record.get("height") else None,
        source="db_fallback",
        confidence="stale",
        error=error,
    )


def get_runtime_map_context(robot_id: str | None = None) -> RuntimeMapContext:
    """Movement map-state를 정규화한다. 실패 시 DB/config fallback."""
    try:
        payload = movement_client.map_state(robot_id)
        ctx = _from_movement_payload(payload)
        if not ctx.active_map_id:
            return _from_db_fallback("movement_active_map_missing")
        return ctx
    except MovementClientError as exc:
        return _from_db_fallback(str(exc))


def metadata_matches(record: dict[str, Any], ctx: RuntimeMapContext, *, tol: float = 1e-4) -> bool:
    if not ctx.ok or ctx.width is None or ctx.height is None or ctx.resolution is None:
        return False
    try:
        return (
            abs(float(record.get("resolution", 0)) - float(ctx.resolution)) <= tol
            and abs(float(record.get("origin_x", 0)) - float(ctx.origin[0])) <= tol
            and abs(float(record.get("origin_y", 0)) - float(ctx.origin[1])) <= tol
            and abs(float(record.get("origin_yaw", 0)) - float(ctx.origin[2])) <= tol
            and int(record.get("width", 0)) == int(ctx.width)
            and int(record.get("height", 0)) == int(ctx.height)
        )
    except (TypeError, ValueError):
        return False


def asset_status_for(record: dict[str, Any], ctx: RuntimeMapContext) -> str:
    """persistent map asset vs runtime context 진단."""
    if not ctx.ok:
        return "no_runtime"
    map_id = str(record.get("map_id") or "")
    if map_id == ctx.active_map_id and metadata_matches(record, ctx):
        return "ok"
    if map_id == ctx.active_map_id:
        return "mismatch"
    if metadata_matches(record, ctx):
        return "alias"
    return "mismatch"


def overlay_nav_dims(record: dict[str, Any], ctx: RuntimeMapContext) -> dict[str, Any]:
    """MapRecord에 display asset metadata와 runtime nav metadata를 분리해 싣는다."""
    out = dict(record)
    status = asset_status_for(record, ctx)
    out["asset_status"] = status
    out["runtime_match"] = metadata_matches(record, ctx)
    out["runtime_map_id"] = ctx.active_map_id
    out["runtime_confidence"] = ctx.confidence
    out["display_resolution"] = record.get("resolution")
    out["display_origin_x"] = record.get("origin_x")
    out["display_origin_y"] = record.get("origin_y")
    out["display_origin_yaw"] = record.get("origin_yaw")
    out["display_width"] = record.get("width")
    out["display_height"] = record.get("height")
    if ctx.ok and ctx.active_map_id:
        out["runtime_resolution"] = ctx.resolution
        out["runtime_origin_x"] = ctx.origin[0]
        out["runtime_origin_y"] = ctx.origin[1]
        out["runtime_origin_yaw"] = ctx.origin[2]
        out["runtime_width"] = ctx.width
        out["runtime_height"] = ctx.height
        out["runtime_frame_id"] = ctx.frame_id
    return out


def pose_in_bounds(x: float, y: float, ctx: RuntimeMapContext) -> bool | None:
    if not ctx.ok or ctx.width is None or ctx.height is None or ctx.resolution is None:
        return None
    try:
        px = (x - ctx.origin[0]) / ctx.resolution
        py = ctx.height - (y - ctx.origin[1]) / ctx.resolution
        return 0 <= px <= ctx.width and 0 <= py <= ctx.height
    except (TypeError, ValueError, ZeroDivisionError):
        return None


def resolve_command_map(
    ui_map_id: str | None, robot_id: str | None = None
) -> tuple[str, RuntimeMapContext, dict[str, Any]]:
    """수동 명령용 map 해석. runtime active map을 우선하고 ui_map_id는 진단용으로 남긴다."""
    ctx = get_runtime_map_context(robot_id)
    if not ctx.ok or not ctx.active_map_id:
        raise HTTPException(
            status_code=502,
            detail={"error": "movement_map_state_unavailable", "map_state": ctx.to_map_state()},
        )
    record = map_record_by_id(ui_map_id) if ui_map_id else None
    runtime_map_id = ctx.active_map_id
    info = {
        "ui_map_id": ui_map_id,
        "runtime_map_id": runtime_map_id,
        "runtime_match": metadata_matches(record, ctx) if record else ui_map_id == runtime_map_id,
        "asset_status": asset_status_for(record, ctx) if record else "no_persistent_map",
        "runtime_confidence": ctx.confidence,
    }
    return runtime_map_id, ctx, info


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
    for item in list_map_asset_records():
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
    """— Movement runtime map context 단일 조회."""
    return get_runtime_map_context().to_map_state()


def assert_movement_active_map(map_id: str) -> dict:
    """LMS map이 Movement active map과 일치하는지 확인하고 map-state를 반환한다."""
    _, state = resolve_movement_map_id(map_id)
    return state


def resolve_movement_map_id(lms_map_id: str, robot_id: str | None = None) -> tuple[str, dict]:
    """수동 명령용 map 해석. runtime active map을 우선한다."""
    runtime_map_id, ctx, _info = resolve_command_map(lms_map_id, robot_id)
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
            pose_payload = {
                "error": str(pose_exc),
                "localized": health.get("localized", False),
                "pose": health.get("pose"),
            }
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
    """Store the canonical latest pose and refresh robot liveness."""
    if not robots.exists(conn, robot_id):
        raise HTTPException(status_code=404, detail="robot not found")
    data = payload.model_dump()
    data["source"] = source or payload.source
    robot_poses.upsert_latest(conn, robot_id, data)
    robots.touch(conn, robot_id)
