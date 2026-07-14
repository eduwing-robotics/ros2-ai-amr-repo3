#!/usr/bin/env bash
# zones.json approach → LMS 동기화용 JSON (좌표·marker·waypoint_id)
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="${1:-$ROOT/config/lms_nav_waypoint_map_tb3_2.json}"
ZONES="$ROOT/map/zones.json"

python3 <<PY
import json
from pathlib import Path

zones = json.loads(Path("$ZONES").read_text(encoding="utf-8"))
wps = zones.get("waypoints", {})
semantic = zones.get("semantic_zones", {})

marker_by_wp = {}
for z in semantic.values():
    aw = z.get("approach_waypoint")
    mid = z.get("aruco_marker_id")
    if aw and mid is not None:
        marker_by_wp[str(aw)] = int(mid)

nav_waypoints = {}
by_marker = {}
for wp_id, data in wps.items():
    if not str(wp_id).endswith("_approach"):
        continue
    entry = {
        "x": float(data["x"]),
        "y": float(data["y"]),
        "yaw": float(data.get("theta", data.get("yaw", 0))),
    }
    if wp_id in marker_by_wp:
        entry["aruco_marker_id"] = marker_by_wp[wp_id]
        by_marker[str(marker_by_wp[wp_id])] = wp_id
    nav_waypoints[wp_id] = entry

# 기존 LMS id 매핑은 유지
existing = {}
out_path = Path("$OUT")
if out_path.exists():
    existing = json.loads(out_path.read_text(encoding="utf-8"))

payload = {
    "schema_version": "2026-07-09",
    "robot_id": existing.get("robot_id", "tb3_2"),
    "nav_map": existing.get("nav_map", "map/robot2_map.yaml"),
    "zones_source": "slam_nav_ws/map/zones.json",
    "description": existing.get("description", "Auto-export from zones.json — merge by_lms_location_id manually"),
    "by_lms_location_id": existing.get("by_lms_location_id", {}),
    "by_aruco_marker_id": by_marker,
    "nav_waypoints": nav_waypoints,
}
out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print(f"Wrote {out_path} ({len(nav_waypoints)} approach waypoints)")
PY
