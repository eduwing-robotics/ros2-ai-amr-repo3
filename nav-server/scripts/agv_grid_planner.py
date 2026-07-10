#!/usr/bin/env python3
"""AGV-style 4-neighbor grid planner for warehouse corridor following."""

from __future__ import annotations

from dataclasses import dataclass
import heapq
import math
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple


Cell = Tuple[int, int]


@dataclass(frozen=True)
class GridMap:
    width: int
    height: int
    resolution: float
    origin_x: float
    origin_y: float
    data: Sequence[int]
    occupied_threshold: int = 50
    unknown_is_blocked: bool = True

    def in_bounds(self, cell: Cell) -> bool:
        x, y = cell
        return 0 <= x < self.width and 0 <= y < self.height

    def index(self, cell: Cell) -> int:
        x, y = cell
        return y * self.width + x

    def occupancy(self, cell: Cell) -> int:
        return int(self.data[self.index(cell)])

    def is_blocked_raw(self, cell: Cell) -> bool:
        if not self.in_bounds(cell):
            return True
        value = self.occupancy(cell)
        if value < 0:
            return self.unknown_is_blocked
        return value >= self.occupied_threshold

    def world_to_cell(self, x: float, y: float) -> Cell:
        return (
            int(math.floor((x - self.origin_x) / self.resolution)),
            int(math.floor((y - self.origin_y) / self.resolution)),
        )

    def cell_to_world(self, cell: Cell) -> Tuple[float, float]:
        x, y = cell
        return (
            self.origin_x + (x + 0.5) * self.resolution,
            self.origin_y + (y + 0.5) * self.resolution,
        )


@dataclass(frozen=True)
class MotionSegment:
    kind: str
    x: float
    y: float
    heading_deg: int


def effective_radius(robot_radius: float, lift_width: float, safety_margin: float) -> float:
    return max(robot_radius, lift_width / 2.0) + safety_margin


def inflation_cells(grid: GridMap, robot_radius: float, lift_width: float, safety_margin: float) -> int:
    return int(math.ceil(effective_radius(robot_radius, lift_width, safety_margin) / grid.resolution))


def inflated_blocked_cells(grid: GridMap, radius_cells: int) -> Set[Cell]:
    blocked: Set[Cell] = set()
    raw_blocked = [
        (x, y)
        for y in range(grid.height)
        for x in range(grid.width)
        if grid.is_blocked_raw((x, y))
    ]
    radius_sq = radius_cells * radius_cells
    for ox, oy in raw_blocked:
        for dy in range(-radius_cells, radius_cells + 1):
            for dx in range(-radius_cells, radius_cells + 1):
                if dx * dx + dy * dy > radius_sq:
                    continue
                cell = (ox + dx, oy + dy)
                if grid.in_bounds(cell):
                    blocked.add(cell)
    return blocked


def four_neighbors(cell: Cell) -> Tuple[Cell, Cell, Cell, Cell]:
    x, y = cell
    return ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))


def manhattan(a: Cell, b: Cell) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def astar_4(
    grid: GridMap,
    start: Cell,
    goal: Cell,
    blocked: Optional[Set[Cell]] = None,
    allowed_cells: Optional[Set[Cell]] = None,
) -> List[Cell]:
    """Run A* using only up/down/left/right neighbors."""
    blocked = blocked or set()
    if not grid.in_bounds(start) or not grid.in_bounds(goal):
        raise ValueError("start and goal must be inside the grid")
    if start in blocked or goal in blocked:
        raise ValueError("start or goal is blocked")
    if allowed_cells is not None and (start not in allowed_cells or goal not in allowed_cells):
        raise ValueError("start or goal is outside the allowed corridor graph")

    frontier: List[Tuple[int, int, Cell]] = []
    heapq.heappush(frontier, (manhattan(start, goal), 0, start))
    came_from: Dict[Cell, Optional[Cell]] = {start: None}
    cost_so_far: Dict[Cell, int] = {start: 0}

    while frontier:
        _, _, current = heapq.heappop(frontier)
        if current == goal:
            return reconstruct_path(came_from, goal)

        for nxt in four_neighbors(current):
            if not grid.in_bounds(nxt) or nxt in blocked:
                continue
            if allowed_cells is not None and nxt not in allowed_cells:
                continue
            new_cost = cost_so_far[current] + 1
            if nxt not in cost_so_far or new_cost < cost_so_far[nxt]:
                cost_so_far[nxt] = new_cost
                priority = new_cost + manhattan(nxt, goal)
                heapq.heappush(frontier, (priority, new_cost, nxt))
                came_from[nxt] = current

    raise ValueError("no 4-neighbor path found")


def reconstruct_path(came_from: Dict[Cell, Optional[Cell]], goal: Cell) -> List[Cell]:
    path = [goal]
    current = goal
    while came_from[current] is not None:
        current = came_from[current]  # type: ignore[assignment]
        path.append(current)
    path.reverse()
    return path


def rasterize_axis_aligned(start: Cell, end: Cell) -> List[Cell]:
    sx, sy = start
    ex, ey = end
    if sx != ex and sy != ey:
        raise ValueError("edge must be axis-aligned")
    if sx == ex:
        step = 1 if ey >= sy else -1
        return [(sx, y) for y in range(sy, ey + step, step)]
    step = 1 if ex >= sx else -1
    return [(x, sy) for x in range(sx, ex + step, step)]


def cells_to_motion_segments(path: Sequence[Cell], grid: GridMap) -> List[MotionSegment]:
    """Compress a cell path into stop/rotate/straight-drive primitives."""
    if len(path) < 2:
        return []

    segments: List[MotionSegment] = []
    current_heading: Optional[int] = None
    run_start = path[0]
    run_heading = heading_from_step(path[0], path[1])

    if current_heading != run_heading:
        x, y = grid.cell_to_world(run_start)
        segments.append(MotionSegment("rotate", x, y, run_heading))
        current_heading = run_heading

    for index in range(1, len(path)):
        prev = path[index - 1]
        cell = path[index]
        heading = heading_from_step(prev, cell)
        if heading != run_heading:
            corner = prev
            x, y = grid.cell_to_world(corner)
            segments.append(MotionSegment("drive", x, y, run_heading))
            segments.append(MotionSegment("stop", x, y, run_heading))
            segments.append(MotionSegment("rotate", x, y, heading))
            run_start = prev
            run_heading = heading
            current_heading = heading

    end_x, end_y = grid.cell_to_world(path[-1])
    segments.append(MotionSegment("drive", end_x, end_y, run_heading))
    return segments


def heading_from_step(a: Cell, b: Cell) -> int:
    dx = b[0] - a[0]
    dy = b[1] - a[1]
    if dx == 1 and dy == 0:
        return 0
    if dx == -1 and dy == 0:
        return 180
    if dx == 0 and dy == 1:
        return 90
    if dx == 0 and dy == -1:
        return 270
    raise ValueError(f"non-cardinal step: {a} -> {b}")


def assert_cardinal_path(path: Iterable[Cell]) -> None:
    cells = list(path)
    for prev, cell in zip(cells, cells[1:]):
        heading_from_step(prev, cell)
