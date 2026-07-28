#!/usr/bin/env python3
# Compute and validate dual-robot standby poses from the active waypoint map.

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from typing import Any

SIMULATOR_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = SIMULATOR_ROOT / "config" / "dual_robot_standby.json"


def _resolve(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _map_metadata(path: Path) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        key, value = line.split(":", 1)
        value = value.strip()
        if key == "resolution" or key.endswith("_thresh"):
            result[key] = float(value)
        elif key == "origin":
            result[key] = [float(item.strip()) for item in value.strip("[]").split(",")]
        else:
            result[key] = value
    return result


def _read_pgm(path: Path) -> tuple[int, int, bytes, int]:
    raw = path.read_bytes()
    index = 0

    def token() -> bytes:
        nonlocal index
        while index < len(raw) and raw[index] in b" \t\r\n":
            index += 1
        if index < len(raw) and raw[index] == ord("#"):
            while index < len(raw) and raw[index] not in b"\r\n":
                index += 1
            return token()
        start = index
        while index < len(raw) and raw[index] not in b" \t\r\n":
            index += 1
        return raw[start:index]

    magic = token()
    width = int(token())
    height = int(token())
    max_value = int(token())
    while index < len(raw) and raw[index] in b" \t\r\n":
        index += 1
    if magic != b"P5" or max_value > 255:
        raise ValueError(f"unsupported PGM format: {path}")
    pixels = raw[index:index + width * height]
    if len(pixels) != width * height:
        raise ValueError(f"PGM pixel length mismatch: {path}")
    return width, height, pixels, max_value


def _is_free(map_yaml: Path, x: float, y: float) -> bool:
    meta = _map_metadata(map_yaml)
    image = _resolve(map_yaml.parent, str(meta["image"]))
    width, height, pixels, max_value = _read_pgm(image)
    resolution = float(meta["resolution"])
    origin = meta["origin"]
    col = math.floor((x - float(origin[0])) / resolution)
    row_from_bottom = math.floor((y - float(origin[1])) / resolution)
    row = height - 1 - row_from_bottom
    if not (0 <= col < width and 0 <= row < height):
        return False
    pixel = pixels[row * width + col]
    free_threshold = max_value * (1.0 - float(meta.get("free_thresh", 0.196)))
    return pixel > free_threshold


def load_layout(config_path: Path = DEFAULT_CONFIG) -> dict[str, Any]:
    config_path = config_path.resolve()
    root = config_path.parents[1]
    config = json.loads(config_path.read_text(encoding="utf-8"))
    zones_path = _resolve(root, str(config["zones_json"]))
    map_yaml = _resolve(root, str(config["map_yaml"]))
    zones = json.loads(zones_path.read_text(encoding="utf-8"))
    waypoints = zones["waypoints"]
    hold_distance = float(config["hold_marker_distance_m"])
    approach_distance = float(config["approach_marker_distance_m"])
    reverse_distance = approach_distance - hold_distance
    if reverse_distance <= 0.0:
        raise ValueError("approach marker distance must exceed hold marker distance")

    robots = []
    for raw in config["robots"]:
        waypoint_id = str(raw["approach_waypoint"])
        waypoint = waypoints[waypoint_id]
        yaw = float(waypoint["theta"])
        approach = {"x": float(waypoint["x"]), "y": float(waypoint["y"]), "yaw": yaw}
        hold = {
            "x": approach["x"] + reverse_distance * math.cos(yaw),
            "y": approach["y"] + reverse_distance * math.sin(yaw),
            "yaw": yaw,
        }
        if not _is_free(map_yaml, approach["x"], approach["y"]):
            raise ValueError("{} approach pose is not in free map space: {}".format(raw["name"], approach))
        if not _is_free(map_yaml, hold["x"], hold["y"]):
            raise ValueError("{} hold pose is not in free map space: {}".format(raw["name"], hold))
        robots.append({
            **raw,
            "approach_pose": approach,
            "hold_pose": hold,
            "reverse_distance_m": reverse_distance,
        })

    names = [item["name"] for item in robots]
    domains = [int(item["ros_domain_id"]) for item in robots]
    ports = [int(item["api_port"]) for item in robots]
    if len(names) != len(set(names)) or len(domains) != len(set(domains)) or len(ports) != len(set(ports)):
        raise ValueError("robot names, ROS domains, and API ports must be unique")
    return {
        **config,
        "config_path": str(config_path),
        "map_yaml": str(map_yaml),
        "zones_json": str(zones_path),
        "reverse_distance_m": reverse_distance,
        "robots": robots,
    }


def marker_distance_from_progress(hold_distance_m: float, reverse_progress_m: float) -> float:
    return max(0.0, float(hold_distance_m) + float(reverse_progress_m))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--robot", choices=("tb3_1", "tb3_2"))
    args = parser.parse_args()
    layout = load_layout(args.config)
    if args.robot:
        layout = next(robot for robot in layout["robots"] if robot["name"] == args.robot)
    print(json.dumps(layout, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
