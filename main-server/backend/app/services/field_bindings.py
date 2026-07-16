"""Authoritative task-location bindings shared by Main startup and execution."""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import HTTPException

from app.db.map_reference import load_manifest

_BINDINGS_PATH = Path(__file__).resolve().parents[2] / "config" / "field-bindings.json"
_REQUIRED_LOCATION_FIELDS = {"kind", "map_id", "nav_zone", "nav_waypoint", "pose", "scan_location_id"}
_FIELD_TASKS = {"INBOUND", "OUTBOUND"}


def _invalid(message: str) -> ValueError:
    return ValueError(f"invalid field bindings: {message}")


def _validate_pose(value: Any, label: str) -> None:
    if not isinstance(value, dict) or set(value) != {"x", "y", "yaw"}:
        raise _invalid(f"{label}.pose must contain x, y, yaw")
    if any(not isinstance(value[key], (int, float)) or isinstance(value[key], bool) or not math.isfinite(value[key]) for key in value):
        raise _invalid(f"{label}.pose must be finite")


@lru_cache(maxsize=1)
def load_release_scans() -> dict[str, dict[str, Any]]:
    manifest = load_manifest()
    scans: dict[str, dict[str, Any]] = {}
    for row in manifest["locations"]:
        if row["type"] != "scan":
            continue
        marker_id = row.get("marker_id")
        if not isinstance(marker_id, int) or isinstance(marker_id, bool):
            raise _invalid(f"release scan {row['id']} requires integer marker_id")
        scans[row["id"]] = {**row, "map_id": manifest["map_id"]}
    return scans


@lru_cache(maxsize=1)
def load_field_bindings() -> dict[str, Any]:
    try:
        document = json.loads(_BINDINGS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _invalid(str(exc)) from exc
    if not isinstance(document, dict) or document.get("version") != 1:
        raise _invalid("version must be 1")
    locations, map_dispatch = document.get("locations"), document.get("map_dispatch")
    robot_homes = document.get("robot_home_locations")
    if not isinstance(locations, dict) or not isinstance(map_dispatch, dict) or not isinstance(robot_homes, dict):
        raise _invalid("locations, map_dispatch, and robot_home_locations must be objects")
    scans = load_release_scans()
    for map_id, dispatch in map_dispatch.items():
        if not isinstance(map_id, str) or not map_id or not isinstance(dispatch, dict):
            raise _invalid("map_dispatch entries must be map-id objects")
        if set(dispatch) != {"inbound", "outbound", "status"}:
            raise _invalid(f"map_dispatch.{map_id} must contain inbound, outbound, status")
        if not all(isinstance(dispatch[task], bool) for task in ("inbound", "outbound")) or not isinstance(dispatch["status"], str) or not dispatch["status"]:
            raise _invalid(f"map_dispatch.{map_id} has invalid dispatch state")
    for location_id, binding in locations.items():
        if not isinstance(location_id, str) or not isinstance(binding, dict) or set(binding) != _REQUIRED_LOCATION_FIELDS:
            raise _invalid(f"location {location_id!r} must have the required binding fields")
        _validate_pose(binding["pose"], f"locations.{location_id}")
        if not all(isinstance(binding[key], str) and binding[key] for key in ("kind", "map_id", "nav_zone", "nav_waypoint", "scan_location_id")):
            raise _invalid(f"location {location_id} has invalid scalar fields")
        if binding["scan_location_id"] not in scans:
            raise _invalid(f"location {location_id} scan_location_id is not in the release manifest")
    if not robot_homes or any(not isinstance(robot_id, str) or not robot_id for robot_id in robot_homes):
        raise _invalid("robot_home_locations requires non-empty string keys")
    for robot_id, location_id in robot_homes.items():
        if not isinstance(location_id, str) or not location_id:
            raise _invalid(f"robot_home_locations.{robot_id} must be a location id")
        binding = locations.get(location_id)
        if not binding or binding["kind"] != "home":
            raise _invalid(f"robot_home_locations.{robot_id} must reference a home binding")
    if "default" not in robot_homes:
        raise _invalid("robot_home_locations.default is required")
    return document


def binding_for(location_id: str) -> dict[str, Any]:
    binding = load_field_bindings()["locations"].get(location_id)
    if not binding:
        raise HTTPException(status_code=409, detail=f"location has no authoritative field binding: {location_id}")
    return binding


def scan_binding_for(location_id: str) -> tuple[str, dict[str, Any]]:
    binding = binding_for(location_id)
    scan_id = binding["scan_location_id"]
    return scan_id, load_release_scans()[scan_id]


def home_location_for_robot(robot_id: str | None) -> str:
    """Return the configured precision-return location for a robot."""
    from app.services.robot_mapping import movement_robot_key

    robot_homes = load_field_bindings()["robot_home_locations"]
    supplied = str(robot_id or "").strip()
    if not supplied:
        return str(robot_homes["default"])
    normalized = movement_robot_key(supplied)
    location_id = robot_homes.get(normalized)
    if not location_id:
        raise HTTPException(status_code=409, detail=f"robot has no precision-return binding: {supplied}")
    return str(location_id)


def assert_robot_live_map(robot_id: str, binding_map_id: str) -> dict[str, Any]:
    """Fail closed when a robot's live map cannot execute a bound pose.

    A map id is a coordinate-frame identity, not a UI preference.  In
    particular, do not use the manual-command compatibility resolver here: it
    intentionally rewrites a requested map to the runtime map, which would
    turn a map mismatch into a coordinate dispatch.
    """
    from app.services.movement import MovementClientError, movement_client

    try:
        state = movement_client.map_state(robot_id)
    except MovementClientError as exc:
        raise HTTPException(status_code=409, detail=f"robot map-state unavailable: {robot_id}: {exc}") from exc
    active_map_id = state.get("active_map_id") if isinstance(state, dict) else None
    if not isinstance(active_map_id, str) or not active_map_id:
        raise HTTPException(status_code=409, detail=f"robot map-state missing active_map_id: {robot_id}")
    if active_map_id != binding_map_id:
        raise HTTPException(
            status_code=409,
            detail=(f"robot live map mismatch: robot={robot_id} live_map={active_map_id} "
                    f"binding_map={binding_map_id}"),
        )
    from app.services.runtime_map_context import assert_map_state_binding
    assert_map_state_binding(binding_map_id, state)
    return state


def assert_field_dispatch_commissioned(task_type: str, map_id: str) -> None:
    """Only commissioned per-map field bindings may move inbound/outbound cargo."""
    normalized_task = task_type.upper()
    if normalized_task not in _FIELD_TASKS:
        return
    dispatch = load_field_bindings()["map_dispatch"].get(map_id)
    if not dispatch or not dispatch.get(normalized_task.lower(), False) or dispatch.get("status") != "COMMISSIONED":
        raise HTTPException(status_code=409, detail={
            "code": "BLOCKED_PENDING_PER_MAP_FIELD_BINDINGS",
            "task_type": normalized_task,
            "map_id": map_id,
            "field_dispatch": dispatch or {"inbound": False, "outbound": False, "status": "UNDECLARED"},
        })


def map_for_locations(location_ids: list[str]) -> str:
    """Return the one authoritative map shared by a field task's locations."""
    maps = {str(binding_for(location_id)["map_id"]) for location_id in location_ids}
    if len(maps) != 1:
        raise HTTPException(status_code=409, detail=f"task locations span authoritative maps: {sorted(maps)}")
    return maps.pop()


def assert_locations_match_map(location_ids: list[str], map_id: str) -> str:
    """Reject a saved scenario whose map label disagrees with its bindings."""
    binding_map_id = map_for_locations(location_ids)
    if map_id != binding_map_id:
        raise HTTPException(
            status_code=409,
            detail=f"scenario map conflicts with authoritative field binding: scenario_map={map_id} binding_map={binding_map_id}",
        )
    return binding_map_id


def validate_runtime_location(row: dict[str, Any], location_id: str, *, scan: bool = False) -> dict[str, Any]:
    binding = load_release_scans().get(location_id) if scan else load_field_bindings()["locations"].get(location_id)
    if not binding:
        label = "scan" if scan else "location"
        raise HTTPException(status_code=409, detail=f"{label} has no authoritative field binding: {location_id}")
    expected = binding if scan else binding["pose"]
    mismatches: list[str] = []
    if row.get("map_id") != binding["map_id"]:
        mismatches.append("map_id")
    expected_values = [("x", expected["x"]), ("y", expected["y"]), ("yaw", expected["yaw"])]
    if scan:
        expected_values.insert(0, ("marker_id", binding["marker_id"]))
    for key, expected_value in expected_values:
        actual = row.get(key)
        if key in {"x", "y", "yaw"}:
            if not isinstance(actual, (int, float)) or isinstance(actual, bool) or not math.isclose(float(actual), float(expected_value), abs_tol=1e-6):
                mismatches.append(key)
        elif actual != expected_value:
            mismatches.append(key)
    if mismatches:
        raise HTTPException(status_code=409, detail=f"{location_id} conflicts with authoritative field binding: {', '.join(mismatches)}")
    return binding
