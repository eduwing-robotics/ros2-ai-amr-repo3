"""Movement active map 기준으로 LMS map 자산·DB runtime cache를 갱신한다."""

from __future__ import annotations

import shutil
from typing import Any

from fastapi import HTTPException

from app.api.movement_helpers import movement_map_state
from app.db.repo_bridge import event_repo
from app.services.map_assets import _pgm_size, import_map_assets


def _write_map_yaml(asset_dir, map_id: str, state: dict[str, Any]) -> None:
    target = asset_dir / f"{map_id}.yaml"
    # An existing ROS map YAML is part of the map identity contract. Rewriting
    # equivalent numeric values changes its SHA-256 and makes Main reject the
    # same Nav map. Only synthesize metadata when the asset is genuinely absent.
    if target.exists():
        return
    origin = state.get("origin") or [0.0, 0.0, 0.0]
    origin = (list(origin) + [0.0, 0.0, 0.0])[:3]
    yaml_text = (
        f"image: {map_id}.pgm\n"
        "mode: trinary\n"
        f"resolution: {float(state['resolution'])}\n"
        f"origin: [{origin[0]}, {origin[1]}, {origin[2]}]\n"
        "negate: 0\n"
        "occupied_thresh: 0.65\n"
        "free_thresh: 0.25\n"
    )
    target.write_text(yaml_text, encoding="utf-8")


def _ensure_map_pgm(asset_dir, map_id: str, width: int, height: int) -> str | None:
    target = asset_dir / f"{map_id}.pgm"
    if target.exists():
        w, h = _pgm_size(target)
        if w == width and h == height:
            return None
        return f"{target.name} is {w}x{h}, movement expects {width}x{height}"

    for candidate in sorted(asset_dir.glob("*.pgm")):
        if candidate.name == f"{map_id}.pgm":
            continue
        w, h = _pgm_size(candidate)
        if w == width and h == height:
            shutil.copy2(candidate, target)
            return f"copied {candidate.name} → {target.name}"
    return f"place {map_id}.pgm ({width}x{height}) in {asset_dir}"


def _migrate_map_references(conn, active_map_id: str, legacy_ids: list[str]) -> list[str]:
    from app.db.repo_bridge import map_repo

    migrated: list[str] = []
    for legacy in legacy_ids:
        if legacy == active_map_id:
            continue
        if map_repo(conn).delete(legacy):
            migrated.append(f"maps:pruned {legacy}")
    return migrated


def sync_from_movement(conn, *, legacy_map_ids: list[str] | None = None) -> dict[str, Any]:
    """Movement map-state로 runtime cache(maps/{active}.yaml·DB nav dims)를 갱신하고 legacy map_id 참조를 이전한다."""
    from app.core.config import settings

    state = movement_map_state()
    if not state.get("ok"):
        raise HTTPException(status_code=502, detail={"error": "movement_map_state_unavailable", "map_state": state})

    active_map_id = str(state.get("active_map_id") or "")
    if not active_map_id:
        raise HTTPException(status_code=502, detail={"error": "movement_active_map_missing", "map_state": state})

    width = int(state.get("width") or 0)
    height = int(state.get("height") or 0)
    if width <= 0 or height <= 0:
        raise HTTPException(status_code=502, detail={"error": "movement_map_dimensions_missing", "map_state": state})

    asset_dir = settings.map_assets_dir.resolve()
    asset_dir.mkdir(parents=True, exist_ok=True)
    _write_map_yaml(asset_dir, active_map_id, state)
    pgm_note = _ensure_map_pgm(asset_dir, active_map_id, width, height)

    from app.db.repo_bridge import map_repo

    origin = state.get("origin") or [0.0, 0.0, 0.0]
    origin = (list(origin) + [0.0, 0.0, 0.0])[:3]
    map_repo(conn).upsert(
        {
            "map_id": active_map_id,
            "name": active_map_id,
            "image_url": f"{settings.api_prefix}/map-assets/{active_map_id}/image.png",
            "resolution": float(state["resolution"]),
            "origin_x": float(origin[0]),
            "origin_y": float(origin[1]),
            "origin_yaw": float(origin[2]),
            "width": width,
            "height": height,
            "frame_id": str(state.get("frame_id") or "map"),
        }
    )

    legacy = legacy_map_ids or ["robot1_map", "Main_map", "map_a"]
    for legacy_id in legacy:
        if legacy_id == active_map_id:
            continue
        legacy_yaml = asset_dir / f"{legacy_id}.yaml"
        if legacy_yaml.exists():
            legacy_yaml.unlink()

    pgm_path = asset_dir / f"{active_map_id}.pgm"
    if pgm_path.exists():
        import_result = import_map_assets(conn)
    else:
        import_result = {
            "imported": [],
            "skipped": [{"yaml": f"{active_map_id}.yaml", "reason": f"awaiting {active_map_id}.pgm"}],
            "removed": [],
        }
    migrated = _migrate_map_references(conn, active_map_id, legacy)

    payload = {
        "active_map_id": active_map_id,
        "imported": import_result["imported"],
        "removed": import_result["removed"],
        "skipped": import_result["skipped"],
        "migrated": migrated,
        "pgm_note": pgm_note,
        "movement_map_state": state,
    }
    event_repo(conn).append(
        event_type="DB_MAP_SYNC_MOVEMENT",
        message=f"map synced from movement: {active_map_id}",
        payload=payload,
    )
    return {"ok": True, **payload}
