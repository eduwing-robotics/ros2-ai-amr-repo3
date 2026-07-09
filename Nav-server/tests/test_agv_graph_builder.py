from pathlib import Path

from agv_graph_builder import CorridorGraph, GraphNode, graph_allowed_cells, load_corridor_graph, validate_graph
from agv_grid_planner import GridMap, inflated_blocked_cells


def test_graph_allowed_cells_rasterizes_axis_aligned_edges():
    test_grid = GridMap(width=5, height=5, resolution=1.0, origin_x=0.0, origin_y=0.0, data=[0] * 25)
    graph = CorridorGraph(
        frame_id="map",
        nodes={
            "a": GraphNode("a", 0.5, 0.5),
            "b": GraphNode("b", 3.5, 0.5),
            "c": GraphNode("c", 3.5, 2.5),
        },
        edges=[("a", "b"), ("b", "c")],
    )

    assert graph_allowed_cells(graph, test_grid) == {
        (0, 0),
        (1, 0),
        (2, 0),
        (3, 0),
        (3, 1),
        (3, 2),
    }


def test_validate_graph_rejects_diagonal_edges():
    test_grid = GridMap(width=5, height=5, resolution=1.0, origin_x=0.0, origin_y=0.0, data=[0] * 25)
    graph = CorridorGraph(
        frame_id="map",
        nodes={
            "a": GraphNode("a", 0.5, 0.5),
            "b": GraphNode("b", 2.5, 2.5),
        },
        edges=[("a", "b")],
    )

    errors = validate_graph(graph, test_grid, blocked=set())
    assert errors == ["edge a->b is not axis-aligned"]


def test_validate_graph_rejects_inflated_obstacle_crossing():
    data = [0] * 25
    data[2] = 100
    test_grid = GridMap(width=5, height=5, resolution=1.0, origin_x=0.0, origin_y=0.0, data=data)
    graph = CorridorGraph(
        frame_id="map",
        nodes={
            "a": GraphNode("a", 0.5, 0.5),
            "b": GraphNode("b", 4.5, 0.5),
        },
        edges=[("a", "b")],
    )

    errors = validate_graph(graph, test_grid, blocked=inflated_blocked_cells(test_grid, 0))
    assert errors == ["edge a->b crosses inflated obstacle"]


def test_project_agv_graph_edges_are_axis_aligned():
    graph = load_corridor_graph(Path("/home/lucas/slam_nav_ws/map/agv_waypoint_graph.yaml"))

    diagonal_edges = []
    for start_name, end_name in graph.edges:
        start = graph.nodes[start_name]
        end = graph.nodes[end_name]
        if start.x != end.x and start.y != end.y:
            diagonal_edges.append((start_name, end_name))

    assert diagonal_edges == []
