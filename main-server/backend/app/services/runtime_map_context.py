"""Movement runtime map context — Nav2 active map authority for manual ops."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.core.config import settings
from app.services.movement import MovementClientError, movement_client


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
    map_yaml_exists: bool = False
    image_exists: bool = False
    map_yaml_sha256: str | None = None
    image_sha256: str | None = None
    map_identity: str | None = None

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
        map_yaml_exists=bool(payload.get("map_yaml_exists")),
        image_exists=bool(payload.get("image_exists")),
        map_yaml_sha256=payload.get("map_yaml_sha256"),
        image_sha256=payload.get("image_sha256"),
        map_identity=payload.get("map_identity"),
    )


def _from_db_fallback(error: str | None = None) -> RuntimeMapContext:
    from app.api.movement_helpers import map_record_by_id

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


def assert_runtime_map_binding(map_id: str, ctx: RuntimeMapContext) -> None:
    """Fail closed unless Nav's live map is byte-identical to Main's asset."""
    from fastapi import HTTPException

    from app.services.map_assets import find_map_asset

    if not ctx.ok or ctx.active_map_id != map_id:
        raise HTTPException(status_code=409, detail={"error": "runtime_map_id_mismatch", "requested_map_id": map_id, "map_state": ctx.to_map_state()})
    if not ctx.map_yaml_exists or not ctx.image_exists:
        raise HTTPException(status_code=409, detail={"error": "runtime_map_asset_missing", "map_state": ctx.to_map_state()})
    if not all((ctx.map_yaml_sha256, ctx.image_sha256, ctx.map_identity)):
        raise HTTPException(status_code=409, detail={"error": "runtime_map_identity_missing", "map_state": ctx.to_map_state()})
    try:
        asset = find_map_asset(map_id)
    except HTTPException as exc:
        raise HTTPException(status_code=409, detail={"error": "main_map_asset_missing", "map_id": map_id}) from exc
    geometry_matches = (
        ctx.resolution is not None and ctx.width is not None and ctx.height is not None
        and abs(asset.resolution - ctx.resolution) <= 1e-4
        and all(abs(expected - actual) <= 1e-4 for expected, actual in zip((asset.origin_x, asset.origin_y, asset.origin_yaw), ctx.origin))
        and asset.width == ctx.width and asset.height == ctx.height
    )
    if not geometry_matches:
        raise HTTPException(status_code=409, detail={"error": "runtime_map_geometry_mismatch", "map_id": map_id, "map_state": ctx.to_map_state()})
    if (asset.yaml_sha256 != ctx.map_yaml_sha256 or asset.image_sha256 != ctx.image_sha256 or asset.identity != ctx.map_identity):
        raise HTTPException(status_code=409, detail={"error": "runtime_map_identity_mismatch", "map_id": map_id, "map_state": ctx.to_map_state()})


def assert_map_state_binding(map_id: str, payload: dict[str, Any]) -> RuntimeMapContext:
    ctx = _from_movement_payload(payload)
    assert_runtime_map_binding(map_id, ctx)
    return ctx


def resolve_command_map(ui_map_id: str | None, *, robot_id: str | None = None) -> tuple[str, RuntimeMapContext, dict[str, Any]]:
    """수동 명령용 map 해석. runtime active map을 우선하고 ui_map_id는 진단용으로 남긴다."""
    ctx = get_runtime_map_context(robot_id)
    if not ctx.ok or not ctx.active_map_id:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=502,
            detail={"error": "movement_map_state_unavailable", "map_state": ctx.to_map_state()},
        )

    if not ui_map_id:
        raise HTTPException(status_code=409, detail={"error": "map_id_required", "map_state": ctx.to_map_state()})
    assert_runtime_map_binding(ui_map_id, ctx)
    info = {
        "ui_map_id": ui_map_id,
        "runtime_map_id": ctx.active_map_id,
        "runtime_match": True,
        "asset_status": "ok",
        "runtime_confidence": ctx.confidence,
    }
    return ui_map_id, ctx, info
