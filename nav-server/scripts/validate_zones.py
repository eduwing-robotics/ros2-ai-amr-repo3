#!/usr/bin/env python3
"""Validate Nav zones against the active map bounds and occupancy raster."""

import json
import math
import os
from pathlib import Path

# --- paths and clearance policy ---
ROOT = Path(__file__).resolve().parents[1]
MAP_DIR = ROOT / "map"
DEFAULT_MAP_YAML = MAP_DIR / "robot1_map.yaml"
YAML_PATH = Path(os.getenv("ACTIVE_MAP_YAML", DEFAULT_MAP_YAML))
if not YAML_PATH.exists():
    YAML_PATH = DEFAULT_MAP_YAML
ZONES_PATH = MAP_DIR / "zones.json"

# burger_smartfactory*.yaml: padded footprint circumscribed radius is 0.148 m;
# the global costmap's 0.18 m inflation radius is the stricter clearance.
WAREHOUSE_APPROACH_CLEARANCE_M = 0.18
WAREHOUSE_APPROACH_WAYPOINTS = ("warehouse_a_approach", "warehouse_c_approach")


def read_simple_yaml(path: Path):
    """Extract the scalar map metadata required by this dependency-free audit."""
    data = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        key, value = line.split(":", 1)
        data[key.strip()] = value.strip()
    return data


def next_token(raw: bytes, index: int) -> tuple[str, int]:
    while index < len(raw) and chr(raw[index]).isspace():
        index += 1
    if index < len(raw) and raw[index] == ord("#"):
        while index < len(raw) and raw[index] not in (10, 13):
            index += 1
        return next_token(raw, index)
    end = index
    while end < len(raw) and not chr(raw[end]).isspace():
        end += 1
    return raw[index:end].decode("ascii"), end


def read_pgm(path: Path) -> tuple[int, int, bytes]:
    raw = path.read_bytes()
    magic, index = next_token(raw, 0)
    if magic != "P5":
        raise ValueError(f"unsupported PGM format: {magic}")
    width, index = next_token(raw, index)
    height, index = next_token(raw, index)
    max_value, index = next_token(raw, index)
    if int(max_value) > 255:
        raise ValueError("16-bit PGM is not supported")
    while index < len(raw) and chr(raw[index]).isspace():
        index += 1
    pixels = raw[index : index + int(width) * int(height)]
    if len(pixels) != int(width) * int(height):
        raise ValueError("PGM pixel data is shorter than its header declares")
    return int(width), int(height), pixels


def parse_origin(value: str) -> tuple[float, float]:
    origin = [float(part.strip()) for part in value.strip("[]").split(",")]
    return origin[0], origin[1]


def world_to_cell(x: float, y: float, origin_x: float, origin_y: float, resolution: float) -> tuple[int, int]:
    return (
        math.floor((x - origin_x) / resolution),
        math.floor((y - origin_y) / resolution),
    )


def cell_to_world(cell: tuple[int, int], origin_x: float, origin_y: float, resolution: float) -> tuple[float, float]:
    return (
        origin_x + (cell[0] + 0.5) * resolution,
        origin_y + (cell[1] + 0.5) * resolution,
    )


def is_free_cell(cell: tuple[int, int], width: int, height: int, pixels: bytes, occupied_threshold: float, free_threshold: float) -> bool:
    """Treat occupied and unknown map pixels as unsafe, matching planner policy."""
    x, y = cell
    if not (0 <= x < width and 0 <= y < height):
        return False
    pixel = pixels[(height - 1 - y) * width + x]
    occupancy = (255 - pixel) / 255.0
    return occupancy < free_threshold and occupancy <= occupied_threshold


def has_clearance(cell: tuple[int, int], clearance_m: float, width: int, height: int, pixels: bytes, resolution: float, occupied_threshold: float, free_threshold: float) -> bool:
    radius_cells = math.ceil(clearance_m / resolution)
    for y in range(cell[1] - radius_cells, cell[1] + radius_cells + 1):
        for x in range(cell[0] - radius_cells, cell[0] + radius_cells + 1):
            if math.hypot(x - cell[0], y - cell[1]) * resolution <= clearance_m and not is_free_cell(
                (x, y), width, height, pixels, occupied_threshold, free_threshold
            ):
                return False
    return True


def main():
    print("구역 및 웨이포인트 검증을 시작합니다...")
    if not YAML_PATH.exists() or not ZONES_PATH.exists():
        print(f"오류: 필요한 설정 파일이 없습니다. map={YAML_PATH}, zones={ZONES_PATH}")
        return 1

    map_yaml = read_simple_yaml(YAML_PATH)
    zones = json.loads(ZONES_PATH.read_text(encoding="utf-8"))
    width, height, pixels = read_pgm(MAP_DIR / map_yaml["image"])
    resolution = float(map_yaml["resolution"])
    origin_x, origin_y = parse_origin(map_yaml["origin"])
    occupied_threshold = float(map_yaml["occupied_thresh"])
    free_threshold = float(map_yaml["free_thresh"])
    min_x, max_x = origin_x, origin_x + width * resolution
    min_y, max_y = origin_y, origin_y + height * resolution
    errors = []

    for name, pose in zones.get("waypoints", {}).items():
        x, y = float(pose["x"]), float(pose["y"])
        if not (min_x <= x <= max_x and min_y <= y <= max_y):
            errors.append(f"웨이포인트 범위 초과: {name} ({x}, {y})")

    for name, zone in zones.get("semantic_zones", {}).items():
        rect = zone["rect"]
        for x, y in ((rect["min_x"], rect["min_y"]), (rect["max_x"], rect["max_y"])):
            if not (min_x <= x <= max_x and min_y <= y <= max_y):
                errors.append(f"구역 범위 초과: {name} ({x}, {y})")

    waypoints = zones.get("waypoints", {})
    for segment_id, segment in zones.get("traffic_segments", {}).items():
        for field in ("entry_waypoints", "right_hand_waypoints"):
            for waypoint_name in segment.get(field, []):
                if waypoint_name not in waypoints:
                    errors.append(f"traffic segment 참조 오류: {segment_id}.{field} -> {waypoint_name}")
        yield_waypoint = segment.get("yield_waypoint")
        if yield_waypoint and yield_waypoint not in waypoints:
            errors.append(f"traffic segment 양보 지점 오류: {segment_id}.yield_waypoint -> {yield_waypoint}")

    for name in WAREHOUSE_APPROACH_WAYPOINTS:
        pose = waypoints.get(name)
        if not isinstance(pose, dict):
            errors.append(f"warehouse approach waypoint 누락: {name}")
            continue
        cell = world_to_cell(float(pose["x"]), float(pose["y"]), origin_x, origin_y, resolution)
        if not is_free_cell(cell, width, height, pixels, occupied_threshold, free_threshold):
            errors.append(f"warehouse approach 비-자유 셀: {name} cell={cell}")
        elif not has_clearance(cell, WAREHOUSE_APPROACH_CLEARANCE_M, width, height, pixels, resolution, occupied_threshold, free_threshold):
            errors.append(f"warehouse approach clearance 부족: {name} cell={cell} clearance={WAREHOUSE_APPROACH_CLEARANCE_M:.2f}m")
        else:
            center = cell_to_world(cell, origin_x, origin_y, resolution)
            print(f"warehouse approach: {name} cell={cell} center=({center[0]:.3f}, {center[1]:.3f}) free clearance={WAREHOUSE_APPROACH_CLEARANCE_M:.2f}m")

    print(f"맵 범위: X({min_x:.2f} ~ {max_x:.2f}), Y({min_y:.2f} ~ {max_y:.2f})")
    if errors:
        print("\n[검증 실패] 아래 항목을 수정하세요:")
        for error in errors:
            print(f" - {error}")
        return 1
    print("\n[검증 성공] 모든 데이터가 맵 범위 내에 정상적으로 위치합니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
