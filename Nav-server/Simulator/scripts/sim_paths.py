#!/usr/bin/env python3
"""Repo-relative path resolution for Simulator Python tools."""

from __future__ import annotations

import os
from pathlib import Path

SIMULATOR_ROOT = Path(__file__).resolve().parents[1]
NAV2_REFECTOR_REL = Path("../WS/nav2_REFECTOR")
TURTLEBOT3_WS_REL = Path("../turtlebot3_ws")
DEFAULT_SAMPLE_MAP = SIMULATOR_ROOT / "maps" / "sample" / "map.yaml"
DEFAULT_WORLD_PATH = SIMULATOR_ROOT / "worlds" / "warehouse.world"
DEFAULT_MODEL_DIR = SIMULATOR_ROOT / "models" / "warehouse_zone_markers"


def resolve_nav2_refector_root() -> Path | None:
    env = os.environ.get("NAV2_REFECTOR_ROOT", "").strip()
    candidates = [
        Path(env) if env else None,
        (SIMULATOR_ROOT / NAV2_REFECTOR_REL).resolve(),
        (SIMULATOR_ROOT / "../nav2_REFECTOR").resolve(),
        Path("/workspace/nav2_REFECTOR"),
        Path.home() / "WS" / "nav2_REFECTOR",
    ]
    for candidate in candidates:
        if candidate and (candidate / "slam_nav_ws").is_dir():
            return candidate.resolve()
    return None


def default_robot1_map_yaml() -> Path:
    nav2_root = resolve_nav2_refector_root()
    if nav2_root is not None:
        path = nav2_root / "slam_nav_ws" / "map" / "robot1_map.yaml"
        if path.is_file():
            return path
    return DEFAULT_SAMPLE_MAP


def nav2_config_root() -> Path | None:
    nav2_root = resolve_nav2_refector_root()
    if nav2_root is None:
        return None
    return nav2_root / "slam_nav_ws" / "config"
