"""Scenario API v1 validation and expansion into canonical physical steps."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from nav_app.models import MovementStep, ScenarioCommandRequest

ROOT = Path(__file__).resolve().parents[2]
CONTRACT_VERSION = "1.0"
ACTIVE_MAP_ID = "robot2_map"
COORDINATE_TOLERANCE_M = 0.05
YAW_TOLERANCE_RAD = 0.20

BUSINESS_STEPS: Tuple[Tuple[str, str], ...] = (
    ("LEAVE_HOME", "leave_home"), ("PICKUP_APPROACH", "pickup_approach"),
    ("PICKUP_ALIGN", "pickup_align"), ("LOAD", "load"), ("TRANSPORT", "transport"),
    ("DROPOFF_ALIGN", "dropoff_align"), ("UNLOAD", "unload"),
    ("RETURN_HOME", "return_home"), ("PARK", "park"),
)

_TEMPLATES = {
    "inbound": ROOT / "docs" / "main_inbound2_storage_a_level1_return_wait2_20260716.json",
    "outbound": ROOT / "docs" / "main_storage_a_outbound2_level1_return_wait2_20260716.json",
}
_BASE_ENDPOINTS = {
    "inbound": ("inbound_slot_2_approach", "warehouse_a_approach"),
    "outbound": ("warehouse_a_approach", "outbound_slot_2_approach"),
}
_LOCATION_WAYPOINTS = {
    "INBOUND_01": "inbound_slot_1_approach", "INBOUND_02": "inbound_slot_2_approach",
    "OUTBOUND_01": "outbound_slot_1_approach", "OUTBOUND_02": "outbound_slot_2_approach",
    "STORAGE_01": "warehouse_b_approach", "STORAGE_02": "warehouse_a_approach",
    "STORAGE_03": "warehouse_c_approach", "STORAGE_04": "warehouse_d_approach",
    "STORAGE_A": "warehouse_a_approach", "STORAGE_B": "warehouse_b_approach",
    "STORAGE_C": "warehouse_c_approach", "STORAGE_D": "warehouse_d_approach",
}
_ROLE_PREFIXES = {
    "inbound": ("INBOUND_", "STORAGE_"),
    "outbound": ("STORAGE_", "OUTBOUND_"),
}


class ScenarioContractError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code, self.message = code, message


def error_detail(exc: ScenarioContractError) -> Dict[str, Any]:
    return {"code": exc.code, "message": exc.message, "retryable": False}


def _load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _waypoint_profiles() -> Dict[str, Dict[str, Any]]:
    nav_profiles = _load_json(ROOT / "config" / "lms_nav_waypoint_map_tb3_2.json")["nav_waypoints"]
    zone_profiles = _load_json(ROOT / "map" / "zones.json")["waypoints"]
    return {
        waypoint_id: {**zone_profiles.get(waypoint_id, {}), **nav_profile}
        for waypoint_id, nav_profile in nav_profiles.items()
    }


def _resolve_endpoint(label: str, endpoint, expected_prefix: str) -> Tuple[str, Dict[str, Any]]:
    location_id = endpoint.location_id.upper()
    if not location_id.startswith(expected_prefix):
        raise ScenarioContractError("waypoint_location_mismatch", f"{label} must be a {expected_prefix.rstrip('_')} location.")
    waypoint_id = _LOCATION_WAYPOINTS.get(location_id)
    if waypoint_id is None or endpoint.approach.waypoint_id != waypoint_id:
        raise ScenarioContractError("waypoint_location_mismatch", f"{label} location {location_id} is not paired with {endpoint.approach.waypoint_id}.")
    profile = _waypoint_profiles().get(waypoint_id)
    if profile is None:
        raise ScenarioContractError("waypoint_profile_missing", f"No canonical profile for {waypoint_id}.")
    distance = math.hypot(endpoint.approach.x - profile["x"], endpoint.approach.y - profile["y"])
    yaw_error = abs(math.atan2(math.sin(endpoint.approach.yaw - profile["yaw"]), math.cos(endpoint.approach.yaw - profile["yaw"])))
    if distance > COORDINATE_TOLERANCE_M or yaw_error > YAW_TOLERANCE_RAD:
        raise ScenarioContractError("coordinate_mismatch", f"{label} approach differs from canonical profile (xy={distance:.3f}m yaw={yaw_error:.3f}rad).")
    return waypoint_id, profile


def _annotate(steps: List[Dict[str, Any]], indexes: Iterable[int], business_index: int) -> None:
    indexes = list(indexes)
    code, action = BUSINESS_STEPS[business_index]
    for offset, physical_index in enumerate(indexes):
        payload = steps[physical_index].setdefault("payload", {})
        payload.update(business_step_index=business_index, business_step_code=code,
                       business_step_action=action, business_step_start=offset == 0,
                       business_step_complete=offset == len(indexes) - 1)


def _apply_business_steps(steps: List[Dict[str, Any]]) -> None:
    mapping = ((1,), (2,), (3, 4, 5, 6), (7,), (8,), (9, 10, 11, 12), (13,), (14,), (15, 16, 17))
    if len(steps) != 18:
        raise ScenarioContractError("waypoint_profile_missing", "Validated scenario template must contain 18 physical steps.")
    for business_index, physical_indexes in enumerate(mapping):
        _annotate(steps, physical_indexes, business_index)


def _replace_endpoint(steps: List[Dict[str, Any]], old_wp: str, new_wp: str, profile: Dict[str, Any]) -> None:
    old_marker = _waypoint_profiles()[old_wp].get("aruco_marker_id")
    new_marker = profile.get("aruco_marker_id")
    old_token, new_token = old_wp.removesuffix("_approach"), new_wp.removesuffix("_approach")
    old_stage_token = old_token.replace("warehouse_", "storage_").replace("_slot_", "")
    new_stage_token = new_token.replace("warehouse_", "storage_").replace("_slot_", "")
    metric_profile = profile.get("metric_two_stage") or {}
    metric_targets = (
        metric_profile.get("stage1_target_distance_m"),
        metric_profile.get("stage2_target_distance_m"),
    )
    metric_step_index = 0
    for step in steps:
        payload = step.setdefault("payload", {})
        if payload.get("aruco_marker_id") == old_marker:
            payload["aruco_marker_id"] = new_marker
            if step.get("action") == "aruco_align" and payload.get("metric_distance_only"):
                preserve_width_only = payload.get("close_from_marker_width_only")
                payload.update(profile.get("aruco_align") or {})
                if preserve_width_only is not None:
                    payload["close_from_marker_width_only"] = preserve_width_only
                if metric_step_index < len(metric_targets) and metric_targets[metric_step_index] is not None:
                    target_distance = metric_targets[metric_step_index]
                    payload["target_distance_m"] = target_distance
                    distance_cm = round(target_distance * 100)
                    stage_prefix = "align" if metric_step_index == 0 else "insert"
                    payload["stage"] = f"{new_stage_token}_{stage_prefix}_{distance_cm}cm"
                    metric_step_index += 1
        for key in ("capture_return_pose_key", "use_return_pose_key"):
            if payload.get(key) == old_stage_token:
                payload[key] = new_stage_token
        if isinstance(payload.get("stage"), str):
            payload["stage"] = payload["stage"].replace(old_stage_token, new_stage_token)
            payload["stage"] = payload["stage"].replace(old_token, new_token)
        if isinstance(payload.get("waypoints"), list):
            payload["waypoints"] = [new_wp if waypoint == old_wp else waypoint for waypoint in payload["waypoints"]]
        for goal in payload.get("goals") or []:
            if goal.get("waypoint") == old_wp:
                goal.update(waypoint=new_wp, x=profile["x"], y=profile["y"], yaw=profile["yaw"])


def _prepend_inbound1_pre_approach(steps: List[Dict[str, Any]], pickup_wp: str) -> None:
    if pickup_wp != "inbound_slot_1_approach":
        return

    pre_wp = "inbound_slot_1_pre_approach"
    pre_profile = _waypoint_profiles().get(pre_wp)
    if pre_profile is None:
        raise ScenarioContractError("waypoint_profile_missing", f"No canonical profile for {pre_wp}.")

    for step in steps:
        payload = step.setdefault("payload", {})
        goals = payload.get("goals")
        if not isinstance(goals, list):
            continue
        for index, goal in enumerate(goals):
            if not isinstance(goal, dict) or goal.get("waypoint") != pickup_wp:
                continue
            pre_goal = {
                "x": pre_profile["x"],
                "y": pre_profile["y"],
                "yaw": pre_profile["yaw"],
                "waypoint": pre_wp,
                "nav_position_only": True,
                "yaw_tolerance_rad": None,
                "soft_xy_tolerance_m": 0.08,
            }
            goals.insert(index, pre_goal)
            waypoints = payload.get("waypoints")
            if isinstance(waypoints, list):
                waypoints.insert(index, pre_wp)
            return

    raise ScenarioContractError("waypoint_profile_missing", "Inbound 1 pickup navigation step is missing.")


def _apply_floor(steps: List[Dict[str, Any]], scenario_type: str, storage_floor: int) -> None:
    if storage_floor not in (1, 2):
        raise ScenarioContractError("floor_profile_missing", f"Storage floor {storage_floor} is not configured.")
    if scenario_type == "inbound":
        steps[11]["payload"]["target_height_mm"] = 6 if storage_floor == 1 else 50
        steps[13]["payload"]["level"] = storage_floor
    else:
        steps[5]["payload"]["target_height_mm"] = 0 if storage_floor == 1 else 50
        steps[7]["payload"]["level"] = storage_floor


def build_scenario_command(req: ScenarioCommandRequest) -> Tuple[List[MovementStep], Dict[str, Any]]:
    if req.contract_version != CONTRACT_VERSION:
        raise ScenarioContractError("invalid_request", "contract_version must be exactly 1.0.")
    if req.map.map_id != ACTIVE_MAP_ID or req.map.frame_id != "map":
        raise ScenarioContractError("map_mismatch", f"Active map is {ACTIVE_MAP_ID} with frame_id map.")

    pickup_wp, pickup_profile = _resolve_endpoint("pickup", req.pickup, _ROLE_PREFIXES[req.scenario_type][0])
    dropoff_wp, dropoff_profile = _resolve_endpoint("dropoff", req.dropoff, _ROLE_PREFIXES[req.scenario_type][1])
    steps = copy.deepcopy(_load_json(_TEMPLATES[req.scenario_type])["steps"])
    old_pickup, old_dropoff = _BASE_ENDPOINTS[req.scenario_type]
    _replace_endpoint(steps, old_pickup, pickup_wp, pickup_profile)
    _replace_endpoint(steps, old_dropoff, dropoff_wp, dropoff_profile)
    _prepend_inbound1_pre_approach(steps, pickup_wp)
    storage_floor = req.dropoff.floor if req.scenario_type == "inbound" else req.pickup.floor
    _apply_floor(steps, req.scenario_type, storage_floor)
    route_type = f"{pickup_wp.removesuffix('_approach')}_{dropoff_wp.removesuffix('_approach')}_return_wait2"
    for step in steps:
        step.setdefault("payload", {})["route_type"] = route_type
    _apply_business_steps(steps)

    canonical_pickup = req.pickup.model_dump()
    canonical_pickup["approach"].update(pickup_profile)
    canonical_dropoff = req.dropoff.model_dump()
    canonical_dropoff["approach"].update(dropoff_profile)
    metadata = {
        "contract_version": CONTRACT_VERSION, "scenario_contract": True,
        "scenario_type": req.scenario_type, "execution_id": f"exec-{req.command_id}",
        "authority_owner": "MOVEMENT", "authority_released": False,
        "cargo_state": "EMPTY", "business_completed": False, "current_step_code": None,
        "last_completed_step_index": None, "map_id": req.map.map_id, "frame_id": req.map.frame_id,
        "pickup": canonical_pickup, "dropoff": canonical_dropoff, "route_type": route_type,
    }
    return [MovementStep(**step) for step in steps], metadata
