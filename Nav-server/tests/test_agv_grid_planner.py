import pytest

from agv_grid_planner import (
    GridMap,
    assert_cardinal_path,
    astar_4,
    cells_to_motion_segments,
    effective_radius,
    inflated_blocked_cells,
    inflation_cells,
)


def grid(width, height, blocked=()):
    data = [0] * (width * height)
    for x, y in blocked:
        data[y * width + x] = 100
    return GridMap(width=width, height=height, resolution=0.1, origin_x=0.0, origin_y=0.0, data=data)


def test_effective_radius_uses_lift_half_width_plus_margin():
    assert effective_radius(robot_radius=0.11, lift_width=0.34, safety_margin=0.05) == pytest.approx(0.22)


def test_inflation_blocks_cells_around_obstacle():
    test_grid = grid(7, 7, blocked=[(3, 3)])
    blocked = inflated_blocked_cells(test_grid, radius_cells=2)

    assert (3, 3) in blocked
    assert (3, 5) in blocked
    assert (5, 3) in blocked
    assert (6, 3) not in blocked


def test_inflation_cell_count_is_ceiled():
    test_grid = grid(5, 5)
    assert inflation_cells(test_grid, robot_radius=0.11, lift_width=0.34, safety_margin=0.05) == 3


def test_astar_uses_only_4_neighbors():
    test_grid = grid(5, 5, blocked=[(1, 0), (1, 1), (1, 2)])
    path = astar_4(test_grid, (0, 0), (4, 4), blocked=inflated_blocked_cells(test_grid, 0))

    assert path[0] == (0, 0)
    assert path[-1] == (4, 4)
    assert_cardinal_path(path)


def test_astar_rejects_diagonal_only_escape():
    test_grid = grid(2, 2, blocked=[(1, 0), (0, 1)])
    with pytest.raises(ValueError, match="no 4-neighbor path"):
        astar_4(test_grid, (0, 0), (1, 1), blocked=inflated_blocked_cells(test_grid, 0))


def test_motion_segments_stop_and_rotate_at_corners():
    test_grid = grid(5, 5)
    path = [(0, 0), (1, 0), (2, 0), (2, 1), (2, 2)]
    segments = cells_to_motion_segments(path, test_grid)

    assert [segment.kind for segment in segments] == ["rotate", "drive", "stop", "rotate", "drive"]
    assert [segment.heading_deg for segment in segments] == [0, 0, 0, 90, 90]
