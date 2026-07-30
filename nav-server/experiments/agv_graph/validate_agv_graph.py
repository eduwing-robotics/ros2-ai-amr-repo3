#!/usr/bin/env python3
"""Validate AGV graph against a map yaml with the same inflation as the follower."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

import yaml

try:
    from .agv_graph_builder import (
        graph_allowed_cells,
        load_corridor_graph,
        validate_graph,
    )
    from .agv_grid_planner import (
        GridMap,
        astar_4,
        inflated_blocked_cells,
        inflation_cells,
    )
except ImportError:  # pragma: no cover - direct script execution fallback
    from agv_graph_builder import (
        graph_allowed_cells,
        load_corridor_graph,
        validate_graph,
    )
    from agv_grid_planner import (
        GridMap,
        astar_4,
        inflated_blocked_cells,
        inflation_cells,
    )


EXPERIMENT_ROOT = Path(__file__).resolve().parent
NAV_SERVER_ROOT = Path(os.environ.get("NAV_SERVER_ROOT", EXPERIMENT_ROOT.parents[1])).resolve()
DEFAULT_MAP_YAML = NAV_SERVER_ROOT / "map" / "robot2_map.yaml"
DEFAULT_GRAPH_PATH = EXPERIMENT_ROOT / "map" / "agv_waypoint_graph.yaml"


def resolve_repo_path(path_value: str) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(str(path_value))))
    if path.is_absolute():
        return path
    return (NAV_SERVER_ROOT / path).resolve()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--map-yaml", default=os.environ.get("ACTIVE_MAP_YAML", str(DEFAULT_MAP_YAML)))
    parser.add_argument("--graph", default=os.environ.get("AGV_GRAPH_PATH", str(DEFAULT_GRAPH_PATH)))
    parser.add_argument("--robot-radius", type=float, default=0.11)
    parser.add_argument("--lift-width", type=float, default=0.34)
    parser.add_argument("--safety-margin", type=float, default=0.08)
    parser.add_argument("--unknown-is-blocked", action="store_true")
    parser.add_argument("--check-path", nargs=2, action="append", metavar=("START", "GOAL"), default=[])
    args = parser.parse_args()

    map_yaml = resolve_repo_path(args.map_yaml)
    graph_path = resolve_repo_path(args.graph)
    grid = load_map_yaml(map_yaml, unknown_is_blocked=args.unknown_is_blocked)
    graph = load_corridor_graph(graph_path)
    radius = inflation_cells(grid, args.robot_radius, args.lift_width, args.safety_margin)
    blocked = inflated_blocked_cells(grid, radius)
    allowed = graph_allowed_cells(graph, grid)
    errors = validate_graph(graph, grid, blocked)

    print(
        f"map={map_yaml} graph={graph_path} "
        f"resolution={grid.resolution:.3f} inflation_cells={radius} "
        f"allowed_cells={len(allowed)} blocked_cells={len(blocked)} graph_errors={len(errors)}"
    )
    for error in errors:
        print(f"- {error}")

    for start, goal in args.check_path:
        try:
            start_cell = nearest_allowed(grid.world_to_cell(graph.nodes[start].x, graph.nodes[start].y), allowed)
            goal_cell = nearest_allowed(grid.world_to_cell(graph.nodes[goal].x, graph.nodes[goal].y), allowed)
            path = astar_4(grid, start_cell, goal_cell, blocked=blocked, allowed_cells=allowed)
            print(f"path {start}->{goal}: OK {len(path)} cells")
        except (KeyError, ValueError) as exc:
            print(f"path {start}->{goal}: FAILED {exc}")

    return 1 if errors else 0


def load_map_yaml(path: Path, unknown_is_blocked: bool) -> GridMap:
    meta = yaml.safe_load(path.read_text(encoding="utf-8"))
    pgm_path = path.parent / meta["image"]
    width, height, pixels = read_pgm(pgm_path)
    occupied_thresh = float(meta.get("occupied_thresh", 0.65))
    free_thresh = float(meta.get("free_thresh", 0.196))
    data = []
    for y in range(height):
        image_y = height - 1 - y
        for x in range(width):
            pixel = pixels[image_y * width + x]
            occupancy = (255 - pixel) / 255.0
            if occupancy > occupied_thresh:
                data.append(100)
            elif occupancy < free_thresh:
                data.append(0)
            else:
                data.append(-1)
    return GridMap(
        width=width,
        height=height,
        resolution=float(meta["resolution"]),
        origin_x=float(meta["origin"][0]),
        origin_y=float(meta["origin"][1]),
        data=data,
        unknown_is_blocked=unknown_is_blocked,
    )


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
    width_int = int(width)
    height_int = int(height)
    pixels = raw[index : index + width_int * height_int]
    if len(pixels) != width_int * height_int:
        raise ValueError("PGM pixel data is shorter than expected")
    return width_int, height_int, pixels


def next_token(buffer: bytes, index: int) -> tuple[str, int]:
    while index < len(buffer) and chr(buffer[index]).isspace():
        index += 1
    if index < len(buffer) and buffer[index] == ord("#"):
        while index < len(buffer) and buffer[index] not in (10, 13):
            index += 1
        return next_token(buffer, index)
    end = index
    while end < len(buffer) and not chr(buffer[end]).isspace():
        end += 1
    return buffer[index:end].decode("ascii"), end


def nearest_allowed(cell, allowed):
    if cell in allowed:
        return cell
    return min(allowed, key=lambda candidate: abs(candidate[0] - cell[0]) + abs(candidate[1] - cell[1]))


if __name__ == "__main__":
    raise SystemExit(main())
