#!/usr/bin/env python3
"""Build and validate an axis-aligned corridor waypoint graph."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Set, Tuple

from agv_grid_planner import Cell, GridMap, rasterize_axis_aligned


@dataclass(frozen=True)
class GraphNode:
    name: str
    x: float
    y: float


@dataclass(frozen=True)
class CorridorGraph:
    frame_id: str
    nodes: Dict[str, GraphNode]
    edges: List[Tuple[str, str]]


def load_corridor_graph(path: Path) -> CorridorGraph:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to load AGV graph yaml files") from exc

    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}

    nodes = {
        name: GraphNode(name=name, x=float(value["x"]), y=float(value["y"]))
        for name, value in (raw.get("nodes") or {}).items()
    }
    edges = [tuple(edge) for edge in raw.get("edges") or []]
    return CorridorGraph(frame_id=raw.get("frame_id", "map"), nodes=nodes, edges=edges)


def graph_allowed_cells(graph: CorridorGraph, grid: GridMap) -> Set[Cell]:
    allowed: Set[Cell] = set()
    for start_name, end_name in graph.edges:
        start = _node_cell(graph, grid, start_name)
        end = _node_cell(graph, grid, end_name)
        allowed.update(rasterize_axis_aligned(start, end))
    return allowed


def validate_graph(graph: CorridorGraph, grid: GridMap, blocked: Set[Cell]) -> List[str]:
    errors: List[str] = []
    for name in graph.nodes:
        cell = _node_cell(graph, grid, name)
        if not grid.in_bounds(cell):
            errors.append(f"node {name} is outside map")
        elif cell in blocked:
            errors.append(f"node {name} is inside inflated obstacle")

    for start_name, end_name in graph.edges:
        if start_name not in graph.nodes:
            errors.append(f"edge references missing node {start_name}")
            continue
        if end_name not in graph.nodes:
            errors.append(f"edge references missing node {end_name}")
            continue
        try:
            cells = rasterize_axis_aligned(
                _node_cell(graph, grid, start_name),
                _node_cell(graph, grid, end_name),
            )
        except ValueError:
            errors.append(f"edge {start_name}->{end_name} is not axis-aligned")
            continue
        blocked_hits = [cell for cell in cells if cell in blocked]
        if blocked_hits:
            errors.append(f"edge {start_name}->{end_name} crosses inflated obstacle")
    return errors


def build_graph_from_zones(zones_path: Path, output_path: Path, waypoint_names: Sequence[str]) -> None:
    """Create a starter graph yaml from selected waypoint names.

    The generated edges are intentionally empty. Operators should connect only
    corridor-center pairs that are safe and axis-aligned.
    """
    with zones_path.open("r", encoding="utf-8") as handle:
        zones = json.load(handle)

    waypoints = zones.get("waypoints", {})
    nodes = {}
    for name in waypoint_names:
        if name not in waypoints:
            raise KeyError(f"missing waypoint in zones.json: {name}")
        nodes[name] = {"x": float(waypoints[name]["x"]), "y": float(waypoints[name]["y"])}

    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to write AGV graph yaml files") from exc

    output = {"frame_id": "map", "nodes": nodes, "edges": []}
    with output_path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(output, handle, sort_keys=False, allow_unicode=True)


def _node_cell(graph: CorridorGraph, grid: GridMap, name: str) -> Cell:
    node = graph.nodes[name]
    return grid.world_to_cell(node.x, node.y)


def edge_names(edges: Iterable[Tuple[str, str]]) -> List[str]:
    return [f"{start}->{end}" for start, end in edges]
