"""Geometry contract for the field-validated robot2 approach points.

The approach poses are physical Nav2 goals.  Dock poses are only the short,
straight ArUco hand-off targets that follow those goals; they must never carry
coordinates from a different map frame.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ZONES = json.loads((ROOT / "map" / "zones.json").read_text(encoding="utf-8"))
EXPECTED_MARKERS = {
    "inbound_slot_1": 0,
    "inbound_slot_2": 1,
    "vehicle_1_zone": 3,
    "vehicle_2_zone": 4,
    "outbound_slot_1": 5,
    "outbound_slot_2": 6,
    "warehouse_section_a": 7,
    "warehouse_section_b": 8,
    "warehouse_section_c": 10,
    "warehouse_section_d": 9,
}


def _map_bounds() -> tuple[float, float, float, float]:
    meta: dict[str, str] = {}
    for line in (ROOT / "map" / "robot2_map.yaml").read_text(encoding="utf-8").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        meta[key.strip()] = value.strip()
    origin = [float(value.strip()) for value in meta["origin"].strip("[]").split(",")]
    raw = (ROOT / "map" / meta["image"]).read_bytes()
    tokens = []
    index = 0
    while len(tokens) < 4:
        while index < len(raw) and chr(raw[index]).isspace():
            index += 1
        if raw[index] == ord("#"):
            while index < len(raw) and raw[index] not in (10, 13):
                index += 1
            continue
        end = index
        while end < len(raw) and not chr(raw[end]).isspace():
            end += 1
        tokens.append(raw[index:end].decode("ascii"))
        index = end
    _, width, height, _ = tokens
    resolution = float(meta["resolution"])
    return origin[0], origin[0] + int(width) * resolution, origin[1], origin[1] + int(height) * resolution


def _expected_handoff_distance(approach: dict) -> float:
    metric = approach.get("metric_two_stage") or {}
    if metric.get("enabled"):
        return float(metric["stage1_target_distance_m"]) - float(metric["stage2_target_distance_m"])
    return float(approach["fork_insert_distance_m"])


def test_operational_marker_roles_are_unique_and_canonical() -> None:
    zones = ZONES["semantic_zones"]
    assert {zone_id: zones[zone_id]["aruco_marker_id"] for zone_id in EXPECTED_MARKERS} == EXPECTED_MARKERS
    assert len(set(EXPECTED_MARKERS.values())) == len(EXPECTED_MARKERS)


@pytest.mark.parametrize("zone_id", EXPECTED_MARKERS)
def test_dock_handoff_is_forward_on_the_approach_normal(zone_id: str) -> None:
    zone = ZONES["semantic_zones"][zone_id]
    approach = ZONES["waypoints"][zone["approach_waypoint"]]
    dock = ZONES["waypoints"][zone["dock_waypoint"]]
    dx = float(dock["x"]) - float(approach["x"])
    dy = float(dock["y"]) - float(approach["y"])
    yaw = float(approach["theta"])
    forward = dx * math.cos(yaw) + dy * math.sin(yaw)
    lateral = -dx * math.sin(yaw) + dy * math.cos(yaw)

    assert forward == pytest.approx(_expected_handoff_distance(approach), abs=0.002)
    assert lateral == pytest.approx(0.0, abs=0.005)
    assert float(dock["theta"]) == pytest.approx(yaw, abs=0.002)


@pytest.mark.parametrize("zone_id", EXPECTED_MARKERS)
def test_operational_approach_and_dock_poses_are_on_robot2_map(zone_id: str) -> None:
    min_x, max_x, min_y, max_y = _map_bounds()
    zone = ZONES["semantic_zones"][zone_id]
    for waypoint_id in (zone["approach_waypoint"], zone["dock_waypoint"]):
        pose = ZONES["waypoints"][waypoint_id]
        assert min_x <= float(pose["x"]) <= max_x, waypoint_id
        assert min_y <= float(pose["y"]) <= max_y, waypoint_id
