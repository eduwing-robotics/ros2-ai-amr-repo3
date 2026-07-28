#!/usr/bin/env python3
"""Load a Simulator profile JSON and print shell export statements."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _simulator_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _as_bool(value: object) -> str:
    return "1" if value else "0"


def _exports(profile: dict) -> list[str]:
    lines: list[str] = []
    map_name = profile.get("map_name", "")
    if map_name:
        lines.append(f'export MAP_NAME="{map_name}"')

    lines.append(f'export WAREHOUSE_WORLD="{_as_bool(profile.get("warehouse_world", False))}"')
    lines.append(f'export WALL_HEIGHT_M="{profile.get("wall_height_m", 0.5)}"')
    lines.append(f'export GAZEBO_GUI="{_as_bool(profile.get("gazebo_gui", False))}"')
    lines.append(f'export RVIZ="{_as_bool(profile.get("rviz", False))}"')
    lines.append(f'export TURTLEBOT3_MODEL="{profile.get("turtlebot3_model", "burger")}"')
    lines.append(f'export ROS_DOMAIN_ID="{profile.get("ros_domain_id", 2)}"')
    nav2_params_file = profile.get("nav2_params_file", "")
    if nav2_params_file:
        lines.append(f'export NAV2_PARAMS_FILE="{nav2_params_file}"')
    robots_config_path = profile.get("robots_config_path", "")
    if robots_config_path:
        lines.append(f'export ROBOTS_CONFIG_PATH="{robots_config_path}"')
    nav_goal_xy_tolerance_m = profile.get("nav_goal_xy_tolerance_m", "")
    if nav_goal_xy_tolerance_m != "":
        lines.append(f'export NAV_GOAL_XY_TOLERANCE_M="{nav_goal_xy_tolerance_m}"')

    spawn = profile.get("spawn", {})
    initial = profile.get("initial_pose", spawn)
    lines.append(f'export INITIAL_X="{initial.get("x", 0.0)}"')
    lines.append(f'export INITIAL_Y="{initial.get("y", 0.0)}"')
    lines.append(f'export INITIAL_YAW="{initial.get("yaw", 0.0)}"')
    lines.append(f'export SPAWN_X="{spawn.get("x", initial.get("x", 0.0))}"')
    lines.append(f'export SPAWN_Y="{spawn.get("y", initial.get("y", 0.0))}"')
    lines.append(f'export SPAWN_YAW="{spawn.get("yaw", initial.get("yaw", 0.0))}"')
    lines.append(f'export SIM_PROFILE="{profile.get("profile", "")}"')
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "profile",
        nargs="?",
        default="sample",
        help="Profile name (config/profiles/<name>.json)",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=_simulator_root(),
        help="Simulator root (default: auto)",
    )
    args = parser.parse_args()

    path = args.root / "config" / "profiles" / f"{args.profile}.json"
    if not path.is_file():
        print(f"[load_profile] missing profile: {path}", file=sys.stderr)
        return 1

    profile = json.loads(path.read_text(encoding="utf-8"))
    for line in _exports(profile):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
