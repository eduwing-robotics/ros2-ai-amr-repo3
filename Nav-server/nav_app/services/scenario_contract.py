"""Scenario API v1 validation and expansion into validated physical steps."""

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
    ("LEAVE_HOME", "leave_home"),
    ("PICKUP_APPROACH", "pickup_approach"),
    ("PICKUP_ALIGN", "pickup_align"),
    ("LOAD", "load"),
    ("TRANSPORT", "transport"),
    ("DROPOFF_ALIGN", "dropoff_align"),
    ("UNLOAD", "unload"),
    ("RETURN_HOME", "return_home"),
    ("PARK", "park"),
)

_PROFILES = {
    "inbound": {
        "template": ROOT / "docs" / "main_inbound2_storage_a_level1_return_wait2_20260716.json",
        "pickup": ("INBOUND_02", "inbound_slot_2_approach", 1),
        "dropoff": ("STORAGE_02", "warehouse_a_approach", 1),
        "route_type": "inbound2_storage_a_return_wait2",
    },
    "outbound": {
        "template": ROOT / "docs" / "main_storage_a_outbound2_level1_return_wait2_20260716.json",
        "pickup": ("STORAGE_02", "warehouse_a_approach", 1),
        "dropoff": ("OUTBOUND_02", "outbound_slot_2_approach", 1),
        "route_type": "storage_a_outbound2_return_wait2",
    },
}


class ScenarioContractError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def error_detail(exc: ScenarioContractError) -> Dict[str, Any]:
    return {"code": exc.code, "message": exc.message, "retryable": False}


def _load_template(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_endpoint(label: str, endpoint, expected: Tuple[str, str, int], template: Dict[str, Any]) -> None:
    location_id, waypoint_id, floor = expected
    if endpoint.location_id != location_id or endpoint.approach.waypoint_id != waypoint_id:
        raise ScenarioContractError(
            "waypoint_location_mismatch",
            f"{label} must use {location_id} with {waypoint_id} for the validated v1 profile.",
        )
    if endpoint.floor != floor:
        raise ScenarioContractError("floor_profile_missing", f"{label} floor {endpoint.floor} is not configured.")
    expected_goal = next(
        goal
        for step in template["steps"]
        for goal in (step.get("payload", {}).get("goals") or [])
        if goal.get("waypoint") == waypoint_id
    )
    distance = math.hypot(endpoint.approach.x - float(expected_goal["x"]), endpoint.approach.y - float(expected_goal["y"]))
    yaw_error = abs(math.atan2(
        math.sin(endpoint.approach.yaw - float(expected_goal["yaw"])),
        math.cos(endpoint.approach.yaw - float(expected_goal["yaw"])),
    ))
    if distance > COORDINATE_TOLERANCE_M or yaw_error > YAW_TOLERANCE_RAD:
        raise ScenarioContractError(
            "coordinate_mismatch",
            f"{label} approach differs from the approved profile (xy={distance:.3f}m yaw={yaw_error:.3f}rad).",
        )


def _annotate(steps: List[Dict[str, Any]], indexes: Iterable[int], business_index: int) -> None:
    indexes = list(indexes)
    code, action = BUSINESS_STEPS[business_index]
    for offset, physical_index in enumerate(indexes):
        payload = steps[physical_index].setdefault("payload", {})
        payload["business_step_index"] = business_index
        payload["business_step_code"] = code
        payload["business_step_action"] = action
        payload["business_step_start"] = offset == 0
        payload["business_step_complete"] = offset == len(indexes) - 1


def _apply_business_steps(steps: List[Dict[str, Any]]) -> None:
    # The two validated templates intentionally share this 18-step physical shape.
    mapping = ((1,), (2,), (3, 4, 5, 6), (7,), (8,), (9, 10, 11, 12), (13,), (14,), (15, 16, 17))
    if len(steps) != 18:
        raise ScenarioContractError("waypoint_profile_missing", "Validated scenario template must contain 18 physical steps.")
    for business_index, physical_indexes in enumerate(mapping):
        _annotate(steps, physical_indexes, business_index)


def build_scenario_command(req: ScenarioCommandRequest) -> Tuple[List[MovementStep], Dict[str, Any]]:
    if req.contract_version != CONTRACT_VERSION:
        raise ScenarioContractError("invalid_request", "contract_version must be exactly 1.0.")
    if req.map.map_id != ACTIVE_MAP_ID or req.map.frame_id != "map":
        raise ScenarioContractError("map_mismatch", f"Active map is {ACTIVE_MAP_ID} with frame_id map.")
    profile = _PROFILES.get(req.scenario_type)
    if not profile:
        raise ScenarioContractError("invalid_request", f"Unsupported scenario_type: {req.scenario_type}")
    template = _load_template(profile["template"])
    _validate_endpoint("pickup", req.pickup, profile["pickup"], template)
    _validate_endpoint("dropoff", req.dropoff, profile["dropoff"], template)

    steps = copy.deepcopy(template["steps"])
    request_goals = {
        req.pickup.approach.waypoint_id: req.pickup.approach,
        req.dropoff.approach.waypoint_id: req.dropoff.approach,
    }
    for step in steps:
        payload = step.setdefault("payload", {})
        payload["route_type"] = profile["route_type"]
        for goal in payload.get("goals") or []:
            snapshot = request_goals.get(goal.get("waypoint"))
            if snapshot:
                goal.update(x=snapshot.x, y=snapshot.y, yaw=snapshot.yaw)
    _apply_business_steps(steps)
    metadata = {
        "contract_version": CONTRACT_VERSION,
        "scenario_contract": True,
        "scenario_type": req.scenario_type,
        "execution_id": f"exec-{req.command_id}",
        "authority_owner": "MOVEMENT",
        "authority_released": False,
        "cargo_state": "EMPTY",
        "business_completed": False,
        "current_step_code": None,
        "last_completed_step_index": None,
        "map_id": req.map.map_id,
        "frame_id": req.map.frame_id,
        "pickup": req.pickup.model_dump(),
        "dropoff": req.dropoff.model_dump(),
    }
    return [MovementStep(**step) for step in steps], metadata
