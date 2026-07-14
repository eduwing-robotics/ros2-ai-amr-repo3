"""LMS → Nav waypoint_id bridge (copy into lms_control_rebuild/backend/app/services/).

Nav `map/zones.json` approach id를 move_to_point params.waypoint_id로 넘기기 위한 매핑.
설정: config/nav_waypoint_map_tb3_2.json (또는 NAV_WAYPOINT_MAP_PATH env).
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _map_path() -> Path:
    raw = os.environ.get("NAV_WAYPOINT_MAP_PATH", "").strip()
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else _REPO_ROOT / p
    return _REPO_ROOT / "config" / "nav_waypoint_map_tb3_2.json"


@lru_cache(maxsize=1)
def _load_map() -> dict[str, Any]:
    path = _map_path()
    if not path.exists():
        return {"by_lms_location_id": {}, "by_aruco_marker_id": {}, "nav_waypoints": {}}
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def resolve_waypoint_id(
    *,
    lms_location_id: str | None = None,
    aruco_marker_id: int | None = None,
) -> str | None:
    data = _load_map()
    by_loc = data.get("by_lms_location_id") or {}
    by_marker = data.get("by_aruco_marker_id") or {}
    if lms_location_id:
        key = str(lms_location_id).strip()
        if key in by_loc:
            return str(by_loc[key])
        scan_key = key if key.startswith("scan_") else f"scan_{key}"
        if scan_key in by_loc:
            return str(by_loc[scan_key])
    if aruco_marker_id is not None:
        hit = by_marker.get(str(int(aruco_marker_id)))
        if hit:
            return str(hit)
    return None


def move_to_point_params_from_scan(scan: dict[str, Any]) -> dict[str, Any]:
    """LMS scan/location row → Nav move_to_point params (waypoint_id 우선)."""
    loc_id = str(scan.get("slot_id") or scan.get("location_id") or scan.get("waypoint_id") or "")
    marker = scan.get("marker_id")
    nav_wp = resolve_waypoint_id(
        lms_location_id=loc_id,
        aruco_marker_id=int(marker) if marker is not None else None,
    )
    if nav_wp:
        return {"waypoint_id": nav_wp}
    if scan.get("x") is not None and scan.get("y") is not None:
        return {
            "x": float(scan["x"]),
            "y": float(scan["y"]),
            "yaw": float(scan.get("yaw") or 0.0),
        }
    return {}


def aruco_align_hold_params(marker_id: int) -> dict[str, Any]:
    """대기장 hold 주차 — Nav 계약 final=hold."""
    return {
        "aruco_marker_id": int(marker_id),
        "final": "hold",
        "align_mode": "center_only",
        "docking_timeout_sec": 90,
        "marker_search_on_miss": True,
        "marker_search_timeout_sec": 90,
    }
