#!/usr/bin/env python3
"""Build Movement API steps from warehouse item/location configuration."""

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

ROOT = Path(__file__).resolve().parents[1]
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
INBOUND2_STORAGE_B_SCENARIO = "inbound2_storage_b_return_wait2"
INBOUND2_STORAGE_B_SCENARIO_ID = "inbound2-storage-b"
INBOUND2_STORAGE_B_SCENARIO_VERSION = 1
INBOUND2_STORAGE_B_BUSINESS_STEPS = [
    ("LEAVE_HOME_COMPLETE", "leave_home"),
    ("INBOUND_APPROACH_COMPLETE", "inbound_approach"),
    ("INBOUND_PRECISION_COMPLETE", "inbound_precision"),
    ("INBOUND_LOAD_COMPLETE", "inbound_load"),
    ("STORAGE_APPROACH_COMPLETE", "storage_approach"),
    ("STORAGE_PRECISION_COMPLETE", "storage_precision"),
    ("STORAGE_UNLOAD_COMPLETE", "storage_unload"),
    ("RETURN_HOME_COMPLETE", "return_home"),
    ("PARK_COMPLETE", "park_home"),
]


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


def build_inbound2_storage_b_scenario(dry_run: bool = False, skip_lift: bool = False):
    """Build the fixed tb3_2 inbound2 -> storage B -> wait2 operating scenario."""
    zones = load_json(ZONES_PATH)
    waypoints = zones.get("waypoints", {})
    traffic_policy = _traffic_policy(zones, "inbound")

    def payload(values: Dict[str, Any]):
        return {**values, "dry_run": True} if dry_run else values

    def business(values: Dict[str, Any], index: int, *, start: bool = True, complete: bool = True):
        step_code, action = INBOUND2_STORAGE_B_BUSINESS_STEPS[index]
        return {
            **values,
            "business_step_index": index,
            "business_step_code": step_code,
            "business_step_action": action,
            "business_step_start": start,
            "business_step_complete": complete,
        }

    def nav_step(waypoint: str, stage: str, terminal_state: str = "ARRIVED"):
        goal = waypoint_pose(waypoints, waypoint)
        waypoint_cfg = waypoints.get(waypoint) or {}
        if waypoint.endswith("_approach"):
            goal.update({
                "nav_position_only": True,
                "yaw_tolerance_rad": None,
                "soft_xy_tolerance_m": float(waypoint_cfg.get("soft_xy_tolerance_m", 0.07)),
                "require_exact_approach": False,
                "relax_forward_clearance": True,
            })
        return {
            "action": "nav2_waypoints",
            "command": None,
            "duration": None,
            "payload": payload(business({
                "frame_id": "map",
                "route_type": INBOUND2_STORAGE_B_SCENARIO,
                "stage": stage,
                "waypoints": [waypoint],
                "goals": [goal],
                "terminal_state": terminal_state,
                "traffic_policy": traffic_policy,
                "traffic_segments": traffic_policy["traffic_segments"],
                "yield_candidates": traffic_policy["yield_candidates"],
            }, 1 if stage == "go_to_inbound2" else 4 if stage == "go_to_storage_b" else 7)),
        }

    def metric_approach_steps(marker_id: int, waypoint_id: str, stage_prefix: str):
        waypoint = waypoints.get(waypoint_id) or {}
        profile = waypoint.get("metric_two_stage") or {}
        aruco = waypoint.get("aruco_align") or {}
        stage1_target = float(profile.get("stage1_target_distance_m", 0.40))
        stage2_target = float(profile.get("stage2_target_distance_m", 0.20))
        wait_sec = float(profile.get("interstage_stop_sec", 3.0))
        common = {
            "route_type": INBOUND2_STORAGE_B_SCENARIO,
            "aruco_marker_id": marker_id,
            "align_mode": "full",
            "final": "hold",
            "fork_insert_on_hold": False,
            "fork_insert_enabled": False,
            "metric_distance_only": True,
            "marker_search_on_miss": True,
            "marker_seek_mode": "sweep",
            "marker_search_timeout_sec": 45,
            "docking_timeout_sec": 65.0,
            "dock_linear_speed": 0.018,
            "dock_min_linear_speed": 0.006,
            "dock_angular_gain": 0.45,
            "dock_max_angular_speed": 0.16,
            **{key: value for key, value in aruco.items() if value is not None},
            # metric_two_stage의 중앙 정렬 허용값이 슬롯 일반값(예: 5%)보다
            # 우선한다. 20cm 삽입 중에도 이 값으로 직진 중심을 유지한다.
            "center_tolerance_norm": float(profile.get("center_tolerance_norm", 0.03)),
            "coarse_center_tolerance_norm": float(profile.get("coarse_center_tolerance_norm", 0.14)),
            # 40cm/20cm(슬롯별 보정값) 단계는 캘리브레이션된 ArUco metric
            # distance가 유일한 정지 기준이다. 슬롯의 legacy pixel-width close가
            # target_distance_m을 덮어쓰지 못하게 한다.
            "close_from_marker_width_only": False,
        }
        return [
            {
                "action": "aruco_align",
                "command": None,
                "duration": None,
                "payload": payload({
                    **business(common, 2 if stage_prefix == "inbound2" else 5, complete=False),
                    "stage": f"{stage_prefix}_align_40cm",
                    "target_distance_m": stage1_target,
                    "terminal_state": "ARRIVED",
                    "capture_return_pose_key": stage_prefix,
                }),
            },
            {
                "action": "wait",
                "command": None,
                "duration": wait_sec,
                "payload": payload(business({
                    "route_type": INBOUND2_STORAGE_B_SCENARIO,
                    "stage": f"{stage_prefix}_wait_3sec",
                    "reason": "two_stage_metric_approach",
                }, 2 if stage_prefix == "inbound2" else 5, start=False)),
            },
            {
                "action": "aruco_align",
                "command": None,
                "duration": None,
                "payload": payload({
                    **business(common, 3 if stage_prefix == "inbound2" else 6, complete=False),
                    "stage": f"{stage_prefix}_insert_calibrated",
                    "target_distance_m": stage2_target,
                    "skip_approach_yaw_rotate": True,
                    "terminal_state": "ARRIVED",
                }),
            },
        ]

    def metric_hold_park_steps(marker_id: int, waypoint_id: str, stage_prefix: str):
        """Build calibrated standby parking: 40 cm stop -> wait -> 20 cm hold."""
        waypoint = waypoints.get(waypoint_id) or {}
        profile = waypoint.get("metric_two_stage") or {}
        aruco = waypoint.get("aruco_align") or {}
        stage1_target = float(profile.get("stage1_target_distance_m", 0.40))
        stage2_target = float(profile.get("stage2_target_distance_m", 0.20))
        wait_sec = float(profile.get("interstage_stop_sec", 3.0))
        common = {
            "route_type": INBOUND2_STORAGE_B_SCENARIO,
            "aruco_marker_id": marker_id,
            "align_mode": "full",
            "fork_insert_on_hold": False,
            "fork_insert_enabled": False,
            "metric_distance_only": True,
            "marker_search_on_miss": True,
            "marker_seek_mode": "sweep",
            "marker_search_timeout_sec": 45,
            "docking_timeout_sec": 65.0,
            "dock_linear_speed": 0.018,
            "dock_min_linear_speed": 0.006,
            "dock_angular_gain": 0.45,
            "dock_max_angular_speed": 0.16,
            **{key: value for key, value in aruco.items() if value is not None},
            "center_tolerance_norm": float(profile.get("center_tolerance_norm", 0.03)),
            "coarse_center_tolerance_norm": float(profile.get("coarse_center_tolerance_norm", 0.14)),
            "close_from_marker_width_only": False,
        }
        return [
            {
                "action": "aruco_align",
                "command": None,
                "duration": None,
                "payload": payload(business({
                    **common,
                    "stage": f"{stage_prefix}_align_40cm",
                    "final": "return_approach",
                    "target_distance_m": stage1_target,
                    "terminal_state": "ARRIVED",
                }, 8, complete=False)),
            },
            {
                "action": "wait",
                "command": None,
                "duration": wait_sec,
                "payload": payload(business({
                    "route_type": INBOUND2_STORAGE_B_SCENARIO,
                    "stage": f"{stage_prefix}_wait_3sec",
                    "reason": "two_stage_metric_hold_park",
                }, 8, start=False, complete=False)),
            },
            {
                "action": "aruco_align",
                "command": None,
                "duration": None,
                "payload": payload(business({
                    **common,
                    "stage": f"{stage_prefix}_hold_20cm",
                    "final": "hold",
                    "target_distance_m": stage2_target,
                    "skip_approach_yaw_rotate": True,
                    "terminal_state": "DONE",
                }, 8, start=False)),
            },
        ]

    steps = [
        {
            "action": "leave_dock",
            "command": None,
            "duration": None,
            "payload": payload(business({
                "route_type": INBOUND2_STORAGE_B_SCENARIO,
                "stage": "leave_wait2",
                "aruco_marker_id": 4,
                "reverse_clearance_marker_distance_m": 0.40,
                "reverse_clearance_fallback_m": 0.20,
                "reverse_marker_max_age_sec": 5.0,
                "terminal_state": "DONE",
            }, 0)),
        },
        nav_step("inbound_slot_2_approach", "go_to_inbound2"),
        *metric_approach_steps(1, "inbound_slot_2_approach", "inbound2"),
        {
            "action": "dock_transfer",
            "command": None,
            "duration": None,
            "payload": payload(business({
                "route_type": INBOUND2_STORAGE_B_SCENARIO,
                "stage": "inbound2_load",
                "aruco_marker_id": 1,
                "action": "load",
                "level": 1,
                "align_mode": "skip",
                "skip_approach_yaw_rotate": True,
                "fork_insert_enabled": False,
                "skip_lift": skip_lift,
                "use_return_pose_key": "inbound2",
                "terminal_state": "DONE",
            }, 3, start=False)),
        },
        nav_step("warehouse_b_approach", "go_to_storage_b"),
        *metric_approach_steps(8, "warehouse_b_approach", "storage_b"),
        {
            "action": "dock_transfer",
            "command": None,
            "duration": None,
            "payload": payload(business({
                "route_type": INBOUND2_STORAGE_B_SCENARIO,
                "stage": "storage_b_unload",
                "aruco_marker_id": 8,
                "action": "unload",
                "level": 2,
                "align_mode": "skip",
                "skip_approach_yaw_rotate": True,
                "fork_insert_enabled": False,
                "skip_lift": skip_lift,
                "use_return_pose_key": "storage_b",
                "terminal_state": "DONE",
            }, 6, start=False)),
        },
        nav_step("vehicle_2_approach", "return_to_wait2"),
        *metric_hold_park_steps(4, "vehicle_2_approach", "park_wait2"),
    ]
    business_details = [
        {"waypoint": "vehicle_2_approach", "marker_id": 4, "estimated_timeout_sec": 60},
        {"waypoint": "inbound_slot_2_approach", "estimated_timeout_sec": 120},
        {"waypoint": "inbound_slot_2_approach", "marker_id": 1, "target_distance_m": 0.40, "wait_sec": 3, "estimated_timeout_sec": 90},
        {"waypoint": "inbound_slot_2_approach", "marker_id": 1, "level": 1, "insert_distance_m": 0.20, "return_to_approach": True, "estimated_timeout_sec": 120},
        {"waypoint": "warehouse_b_approach", "estimated_timeout_sec": 120},
        {"waypoint": "warehouse_b_approach", "marker_id": 8, "target_distance_m": 0.40, "wait_sec": 3, "estimated_timeout_sec": 90},
        {"waypoint": "warehouse_b_approach", "marker_id": 8, "level": 2, "insert_distance_m": 0.20, "return_to_approach": True, "estimated_timeout_sec": 120},
        {"waypoint": "vehicle_2_approach", "estimated_timeout_sec": 120},
        {"waypoint": "vehicle_2_approach", "marker_id": 4, "estimated_timeout_sec": 90},
    ]
    business_steps = [
        {
            "step_index": index,
            "step_code": code,
            "step_action": action,
            **business_details[index],
        }
        for index, (code, action) in enumerate(INBOUND2_STORAGE_B_BUSINESS_STEPS)
    ]
    plan_material = json.dumps(steps, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "scenario": INBOUND2_STORAGE_B_SCENARIO,
        "scenario_id": INBOUND2_STORAGE_B_SCENARIO_ID,
        "scenario_version": INBOUND2_STORAGE_B_SCENARIO_VERSION,
        "robot_name": "tb3_2",
        "waypoints": ["inbound_slot_2_approach", "warehouse_b_approach", "vehicle_2_approach"],
        "steps": steps,
        "operation_sequence": [step["payload"]["stage"] for step in steps],
        "business_steps": business_steps,
        "estimated_total_timeout_sec": sum(item["estimated_timeout_sec"] for item in business_steps),
        "plan_hash": hashlib.sha256(plan_material.encode("utf-8")).hexdigest(),
        "traffic_policy": traffic_policy,
        "traffic_segments": traffic_policy["traffic_segments"],
        "yield_candidates": traffic_policy["yield_candidates"],
    }


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
