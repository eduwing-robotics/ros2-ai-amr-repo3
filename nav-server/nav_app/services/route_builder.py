#!/usr/bin/env python3
"""Build Movement API steps from warehouse item/location configuration."""

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from nav_app.settings import ROOT

ZONES_PATH = ROOT / "map" / "zones.json"
INVENTORY_PATH = ROOT / "config" / "inventory_locations.json"
SUPPORTED_ROUTE_TYPES = {"inbound", "outbound", "standby", "return_to_standby"}
TRANSFER_ROUTE_TYPES = {"inbound", "outbound"}
STANDBY_ROUTE_TYPES = {"standby", "return_to_standby"}
RIGHT_HAND_LANE_WAYPOINTS = ["aisle_right_south", "aisle_right_mid", "aisle_right_north"]
ROUTE_TRAFFIC_SEGMENTS = {
    "inbound": ["inbound_lane", "warehouse_aisle"],
    "outbound": ["warehouse_aisle", "outbound_lane"],
}
DEFAULT_INBOUND_SOURCE_SECTION = "inbound_slot_1"
DEFAULT_OUTBOUND_TARGET_SECTION = "outbound_slot_1"
DEFAULT_RETURN_WAYPOINT = "vehicle_1_approach"


class RouteBuildError(ValueError):
    pass


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_item_name(value: str):
    return value.strip().lower().replace(" ", "_").replace("-", "_")


def load_inventory(path: Path = INVENTORY_PATH):
    data = load_json(path)
    items = data.get("items", [])
    by_key: Dict[str, Dict[str, Any]] = {}
    for item in items:
        keys = {
            item.get("item_code", ""),
            item.get("display_name", ""),
            normalize_item_name(item.get("item_code", "")),
            normalize_item_name(item.get("display_name", "")),
        }
        for key in keys:
            if key:
                by_key[key] = item
    return data, by_key


def find_item(item_name: str, inventory_index: Dict[str, Dict[str, Any]]):
    direct = inventory_index.get(item_name)
    if direct:
        return direct
    normalized = normalize_item_name(item_name)
    item = inventory_index.get(normalized)
    if item:
        return item
    raise RouteBuildError(f"unknown item_name: {item_name}")


def waypoint_pose(waypoints: Dict[str, Dict[str, Any]], waypoint_name: str):
    waypoint = waypoints.get(waypoint_name)
    if not waypoint:
        raise RouteBuildError(f"unknown waypoint: {waypoint_name}")
    return {
        "x": float(waypoint["x"]),
        "y": float(waypoint["y"]),
        "yaw": float(waypoint.get("theta", 0.0)),
        "waypoint": waypoint_name,
    }


def _dedupe_waypoints(waypoint_names: Iterable[str]):
    result = []
    for name in waypoint_names:
        if not result or result[-1] != name:
            result.append(name)
    return result


def _nearest_right_lane_waypoint(waypoints: Dict[str, Dict[str, Any]], target_waypoint: str):
    target = waypoints.get(target_waypoint)
    if not target:
        raise RouteBuildError(f"unknown waypoint: {target_waypoint}")
    target_y = float(target["y"])
    candidates = []
    for name in RIGHT_HAND_LANE_WAYPOINTS:
        waypoint = waypoints.get(name)
        if not waypoint:
            raise RouteBuildError(f"missing right-hand lane waypoint: {name}")
        candidates.append((abs(float(waypoint["y"]) - target_y), name))
    return min(candidates)[1]


def _right_lane_path(target_lane: str, route_type: str):
    if target_lane not in RIGHT_HAND_LANE_WAYPOINTS:
        raise RouteBuildError(f"unknown right-hand lane waypoint: {target_lane}")
    index = RIGHT_HAND_LANE_WAYPOINTS.index(target_lane)
    if route_type == "inbound":
        north_to_south = list(reversed(RIGHT_HAND_LANE_WAYPOINTS))
        return north_to_south[: north_to_south.index(target_lane) + 1]
    return list(reversed(RIGHT_HAND_LANE_WAYPOINTS[: index + 1]))


def _traffic_policy(zones: Dict[str, Any], route_type: str):
    segments = ROUTE_TRAFFIC_SEGMENTS[route_type]
    configured = zones.get("traffic_segments", {})
    yield_candidates = []
    for segment_id in segments:
        segment = configured.get(segment_id)
        if not segment:
            raise RouteBuildError(f"missing traffic segment: {segment_id}")
        yield_waypoint = segment.get("yield_waypoint")
        if yield_waypoint:
            yield_candidates.append(yield_waypoint)
    return {
        "enabled": True,
        "rule": "right_hand_traffic",
        "traffic_segments": segments,
        "yield_candidates": yield_candidates,
    }


def _zone_for_section(zones: Dict[str, Any], section_id: str):
    zone = zones.get("semantic_zones", {}).get(section_id)
    if not zone:
        raise RouteBuildError(f"unknown section_id in zones.json: {section_id}")
    return zone


def _section_transfer_payload(zones: Dict[str, Any], section_id: str, action: str, item: Dict[str, Any]):
    zone = _zone_for_section(zones, section_id)
    marker_id = zone.get("aruco_marker_id")
    if marker_id is None:
        raise RouteBuildError(f"missing aruco_marker_id for section: {section_id}")
    approach_waypoint = zone.get("approach_waypoint")
    dock_waypoint = zone.get("dock_waypoint")
    if not approach_waypoint or not dock_waypoint:
        raise RouteBuildError(f"section requires approach_waypoint and dock_waypoint: {section_id}")
    return {
        "aruco_marker_id": int(marker_id),
        "action": action,
        "level": int(zone.get("level", 1)),
        "dock_waypoint": dock_waypoint,
        "approach_waypoint": approach_waypoint,
        "section_id": section_id,
        "item_code": item["item_code"],
        "section_display_name": zone.get("display_name"),
    }


def _dock_transfer_payload(zones: Dict[str, Any], route_type: str, item: Dict[str, Any]):
    return _section_transfer_payload(
        zones,
        item["section_id"],
        "unload" if route_type == "inbound" else "load",
        item,
    )


def build_route_goals(route_type: str, item_name: str, zones_path: Path = ZONES_PATH, inventory_path: Path = INVENTORY_PATH):
    route_type = route_type.strip().lower()
    if route_type not in TRANSFER_ROUTE_TYPES:
        raise RouteBuildError(f"unsupported item transfer route_type: {route_type}")

    zones = load_json(zones_path)
    waypoints = zones.get("waypoints", {})
    _, inventory_index = load_inventory(inventory_path)
    item = find_item(item_name, inventory_index)

    approach = item["approach_waypoint"]
    right_lane = _nearest_right_lane_waypoint(waypoints, approach)
    lane_path = _right_lane_path(right_lane, route_type)
    if route_type == "inbound":
        waypoint_names = _dedupe_waypoints(["inbound_entry", *lane_path, approach])
    else:
        waypoint_names = _dedupe_waypoints([approach, *lane_path, "outbound_entry"])

    traffic_policy = _traffic_policy(zones, route_type)
    goals = [waypoint_pose(waypoints, name) for name in waypoint_names]
    return {
        "route_type": route_type,
        "item": item,
        "waypoints": waypoint_names,
        "goals": goals,
        "dock_transfer": _dock_transfer_payload(zones, route_type, item),
        "traffic_policy": traffic_policy,
        "traffic_segments": traffic_policy["traffic_segments"],
        "yield_candidates": traffic_policy["yield_candidates"],
    }


def _nav_step(route: Dict[str, Any], waypoint_names: List[str], stage: str, terminal_state="ARRIVED"):
    item = route.get("item") or {}
    return {
        "action": "nav2_waypoints",
        "command": None,
        "duration": None,
        "payload": {
            "frame_id": "map",
            "route_type": route["route_type"],
            "stage": stage,
            "item_code": item.get("item_code"),
            "display_name": item.get("display_name"),
            "waypoints": waypoint_names,
            "goals": [waypoint_pose(route["waypoint_map"], name) for name in waypoint_names],
            "terminal_state": terminal_state,
            "traffic_policy": route["traffic_policy"],
            "traffic_segments": route["traffic_segments"],
            "yield_candidates": route["yield_candidates"],
        },
    }


def _dock_step(route: Dict[str, Any], payload: Dict[str, Any], stage: str):
    return {
        "action": "dock_transfer",
        "command": None,
        "duration": None,
        "payload": {
            **payload,
            "route_type": route["route_type"],
            "stage": stage,
            "terminal_state": "DONE",
        },
    }


def _wait_step(wait_sec: float):
    return {"action": "wait", "command": None, "duration": wait_sec, "payload": {}}


def _return_step(route: Dict[str, Any], return_waypoint: Optional[str]):
    if not return_waypoint:
        return None
    return _nav_step(route, [return_waypoint], "return_to_standby", terminal_state="DONE")


def _build_standby_steps(route_type: str, wait_sec: float, return_waypoint: Optional[str]):
    if not return_waypoint:
        raise RouteBuildError("standby route requires return_waypoint")
    zones = load_json(ZONES_PATH)
    route = {
        "route_type": "standby",
        "item": None,
        "waypoint_map": zones.get("waypoints", {}),
        "traffic_policy": {"enabled": False, "rule": "none", "traffic_segments": [], "yield_candidates": []},
        "traffic_segments": [],
        "yield_candidates": [],
    }
    steps: List[Dict[str, Any]] = [_nav_step(route, [return_waypoint], "return_to_standby", terminal_state="DONE")]
    if wait_sec > 0:
        steps.append(_wait_step(wait_sec))
    return {
        "route_type": route_type,
        "item": None,
        "waypoints": [return_waypoint],
        "goals": [waypoint_pose(route["waypoint_map"], return_waypoint)],
        "steps": steps,
        "operation_sequence": [step["payload"].get("stage", step["action"]) for step in steps],
        "dock_transfer": None,
        "pickup_transfer": None,
        "dropoff_transfer": None,
        "source_section_id": None,
        "target_section_id": None,
        "return_waypoint": return_waypoint,
        "traffic_policy": route["traffic_policy"],
        "traffic_segments": [],
        "yield_candidates": [],
    }


def build_movement_steps(
    route_type: str,
    item_name: Optional[str] = None,
    wait_sec: float = 0.2,
    source_section_id: Optional[str] = None,
    target_section_id: Optional[str] = None,
    return_waypoint: Optional[str] = DEFAULT_RETURN_WAYPOINT,
):
    route_type = route_type.strip().lower()
    if route_type in STANDBY_ROUTE_TYPES:
        return _build_standby_steps(route_type, wait_sec, return_waypoint)
    if not item_name:
        raise RouteBuildError("item transfer route requires item_name")
    route = build_route_goals(route_type, item_name)
    zones = load_json(ZONES_PATH)
    item = route["item"]
    route["waypoint_map"] = zones.get("waypoints", {})

    if route["route_type"] == "inbound":
        pickup_section = source_section_id or DEFAULT_INBOUND_SOURCE_SECTION
        dropoff_section = item["section_id"]
        pickup = _section_transfer_payload(zones, pickup_section, "load", item)
        dropoff = _section_transfer_payload(zones, dropoff_section, "unload", item)
        source_approach = pickup["approach_waypoint"]
        transport_waypoints = route["waypoints"]
    else:
        pickup_section = item["section_id"]
        dropoff_section = target_section_id or DEFAULT_OUTBOUND_TARGET_SECTION
        pickup = _section_transfer_payload(zones, pickup_section, "load", item)
        dropoff = _section_transfer_payload(zones, dropoff_section, "unload", item)
        source_approach = pickup["approach_waypoint"]
        transport_waypoints = route["waypoints"]
        if transport_waypoints and transport_waypoints[0] == source_approach:
            transport_waypoints = transport_waypoints[1:]

    steps: List[Dict[str, Any]] = [
        _nav_step(route, [source_approach], "go_to_pickup_approach"),
        _dock_step(route, pickup, "pickup_dock_lift_up_reverse"),
        _nav_step(route, transport_waypoints, "go_to_dropoff_approach"),
        _dock_step(route, dropoff, "dropoff_dock_lift_down_reverse"),
    ]
    return_step = _return_step(route, return_waypoint)
    if return_step:
        steps.append(return_step)
    if wait_sec > 0:
        steps.append(_wait_step(wait_sec))

    operation_sequence = [step["payload"].get("stage", step["action"]) for step in steps]
    public_route = {key: value for key, value in route.items() if key != "waypoint_map"}
    return {
        **public_route,
        "steps": steps,
        "operation_sequence": operation_sequence,
        "pickup_transfer": pickup,
        "dropoff_transfer": dropoff,
        "source_section_id": pickup_section,
        "target_section_id": dropoff_section,
        "return_waypoint": return_waypoint,
        "waypoints": _dedupe_waypoints([source_approach, *transport_waypoints, *([return_waypoint] if return_waypoint else [])]),
    }


def list_inventory():
    data, _ = load_inventory()
    return data.get("items", [])


def main(argv: Optional[Iterable[str]] = None):
    parser = argparse.ArgumentParser(description="Build Movement API route steps for configured inventory items.")
    parser.add_argument("route_type", choices=sorted(SUPPORTED_ROUTE_TYPES))
    parser.add_argument("item_name", nargs="?")
    parser.add_argument("--wait-sec", type=float, default=0.2)
    parser.add_argument("--source-section-id")
    parser.add_argument("--target-section-id")
    parser.add_argument("--return-waypoint", default=DEFAULT_RETURN_WAYPOINT)
    args = parser.parse_args(argv)
    print(json.dumps(
        build_movement_steps(
            args.route_type,
            args.item_name,
            args.wait_sec,
            args.source_section_id,
            args.target_section_id,
            args.return_waypoint,
        ),
        ensure_ascii=False,
        indent=2,
    ))


if __name__ == "__main__":
    main()
