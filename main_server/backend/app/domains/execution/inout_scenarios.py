"""Main-owned Scenario API v1 contract assembly for inbound/outbound tasks."""

from __future__ import annotations

import math
from typing import Any

from fastapi import HTTPException

from app.core.config import settings
from app.db.postgres import locations
from app.domains.movement.client import movement_robot_key

CONTRACT_VERSION = "1.0"
FRAME_ID = "map"

BUSINESS_STEPS: tuple[tuple[str, str], ...] = (
    ("LEAVE_HOME", "대기 위치 출차"),
    ("PICKUP_APPROACH", "적재 위치 이동"),
    ("PICKUP_ALIGN", "적재 위치 정밀 접근"),
    ("LOAD", "화물 적재"),
    ("TRANSPORT", "목적 위치 이동"),
    ("DROPOFF_ALIGN", "하역 위치 정밀 접근"),
    ("UNLOAD", "화물 하역"),
    ("RETURN_HOME", "대기 위치 복귀"),
    ("PARK", "대기 위치 주차"),
)
STEP_CODE_TO_INDEX = {code: index for index, (code, _label) in enumerate(BUSINESS_STEPS)}

# DB schema를 바꾸지 않고 기존 업무 위치와 release-managed 접근 waypoint를 연결하는 정본.
# 좌표와 yaw는 이 표에 넣지 않고 반드시 locations row에서 실행 시 snapshot한다.
APPROACH_WAYPOINT_BY_LOCATION: dict[str, str] = {
    "INBOUND_01": "inbound_slot_1_approach",
    "INBOUND_02": "inbound_slot_2_approach",
    "OUTBOUND_01": "outbound_slot_1_approach",
    "OUTBOUND_02": "outbound_slot_2_approach",
    "STORAGE_01": "warehouse_b_approach",
    "STORAGE_02": "warehouse_a_approach",
    "STORAGE_03": "warehouse_d_approach",
    "STORAGE_04": "warehouse_c_approach",
    "STORAGE_S1": "warehouse_a_approach",
    "STORAGE_S2": "warehouse_b_approach",
    "STORAGE_S3": "warehouse_c_approach",
    "STORAGE_S4": "warehouse_d_approach",
}


def business_timeline() -> list[dict[str, Any]]:
    """Create the nine Main-owned business steps before Movement dispatch."""
    timeline: list[dict[str, Any]] = []
    for index, (code, label) in enumerate(BUSINESS_STEPS):
        transfer_action = "load" if code == "LOAD" else "unload" if code == "UNLOAD" else None
        timeline.append(
            {
                "step_index": index,
                "kind": code,
                "step_code": code,
                "label": label,
                "status": "PENDING",
                "command_id": None,
                "transfer_action": transfer_action,
            }
        )
    return timeline


def _require_business_location(conn, location_id: str, expected_type: str) -> dict[str, Any]:
    row = locations.get_location(conn, location_id)
    if not row:
        raise HTTPException(status_code=409, detail={"code": "location_not_found", "location_id": location_id})
    actual_type = str(row.get("type") or "").lower()
    if actual_type != expected_type:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "scenario_location_type_mismatch",
                "location_id": location_id,
                "expected_type": expected_type,
                "actual_type": actual_type,
            },
        )
    if not row.get("enabled", True):
        raise HTTPException(status_code=409, detail={"code": "location_disabled", "location_id": location_id})
    return row


def _approach_snapshot(conn, location_id: str) -> dict[str, Any]:
    candidates = [
        APPROACH_WAYPOINT_BY_LOCATION.get(location_id.upper()),
        f"scan_{location_id}",
    ]
    approach = None
    for waypoint_id in candidates:
        if not waypoint_id:
            continue
        row = locations.get_location(conn, waypoint_id)
        if row and row.get("x") is not None and row.get("y") is not None:
            approach = row
            break
    if not approach:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "approach_waypoint_missing",
                "location_id": location_id,
                "expected_waypoint_ids": [item for item in candidates if item],
            },
        )
    waypoint_id = str(approach.get("waypoint_id") or approach.get("location_id") or approach.get("slot_id") or "")
    values = (float(approach["x"]), float(approach["y"]), float(approach.get("yaw") or 0.0))
    if not waypoint_id or not all(math.isfinite(value) for value in values):
        raise HTTPException(
            status_code=409,
            detail={"code": "approach_coordinate_invalid", "location_id": location_id},
        )
    return {"waypoint_id": waypoint_id, "x": values[0], "y": values[1], "yaw": values[2]}


def _floor(value: Any, *, field: str, status_code: int = 409) -> int:
    try:
        floor = int(value)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status_code, detail={"code": "floor_missing", "field": field}) from exc
    if floor not in {1, 2}:
        raise HTTPException(status_code=status_code, detail={"code": "floor_invalid", "field": field})
    return floor


def build_params(conn, task: dict[str, Any]) -> dict[str, Any]:
    """Snapshot the Main DB business locations and approach poses for one Task."""
    task_type = str(task.get("task_type") or "").upper()
    if task_type == "INBOUND":
        scenario_type = "inbound"
        pickup_type, dropoff_type = "inbound", "storage"
    elif task_type == "OUTBOUND":
        scenario_type = "outbound"
        pickup_type, dropoff_type = "storage", "outbound"
    else:
        raise HTTPException(status_code=409, detail={"code": "scenario_task_type_unsupported"})

    pickup_id = str(task.get("from_location_id") or "")
    dropoff_id = str(task.get("to_location_id") or "")
    if not pickup_id or not dropoff_id:
        raise HTTPException(status_code=409, detail={"code": "scenario_location_missing"})
    _require_business_location(conn, pickup_id, pickup_type)
    _require_business_location(conn, dropoff_id, dropoff_type)

    return {
        "scenario_type": scenario_type,
        "map": {"map_id": settings.movement_active_map_id, "frame_id": FRAME_ID},
        "pickup": {
            "location_id": pickup_id,
            "floor": _floor(task.get("from_floor"), field="from_floor"),
            "approach": _approach_snapshot(conn, pickup_id),
        },
        "dropoff": {
            "location_id": dropoff_id,
            "floor": _floor(task.get("to_floor"), field="to_floor"),
            "approach": _approach_snapshot(conn, dropoff_id),
        },
    }


def build_command(
    params: dict[str, Any],
    *,
    command_id: str,
    task_id: int | None,
    robot_id: str,
    callback_url: str,
) -> dict[str, Any]:
    """Build the only body allowed for Movement POST /scenario-commands."""
    if task_id is None:
        raise HTTPException(status_code=400, detail={"code": "scenario_task_id_required"})
    required = {"scenario_type", "map", "pickup", "dropoff"}
    if set(params) != required:
        raise HTTPException(
            status_code=400,
            detail={"code": "scenario_params_invalid", "fields": sorted(set(params) ^ required)},
        )
    scenario_type = params.get("scenario_type")
    if scenario_type not in {"inbound", "outbound"}:
        raise HTTPException(status_code=400, detail={"code": "scenario_type_invalid"})
    map_context = params.get("map")
    if not isinstance(map_context, dict) or set(map_context) != {"map_id", "frame_id"}:
        raise HTTPException(status_code=400, detail={"code": "scenario_map_invalid"})
    if not str(map_context.get("map_id") or "") or map_context.get("frame_id") != FRAME_ID:
        raise HTTPException(status_code=400, detail={"code": "scenario_map_invalid"})
    for role in ("pickup", "dropoff"):
        location = params.get(role)
        if not isinstance(location, dict) or set(location) != {"location_id", "floor", "approach"}:
            raise HTTPException(status_code=400, detail={"code": "scenario_location_invalid", "role": role})
        if not str(location.get("location_id") or ""):
            raise HTTPException(status_code=400, detail={"code": "scenario_location_invalid", "role": role})
        _floor(location.get("floor"), field=f"{role}.floor", status_code=400)
        approach = location.get("approach")
        if not isinstance(approach, dict) or set(approach) != {"waypoint_id", "x", "y", "yaw"}:
            raise HTTPException(status_code=400, detail={"code": "scenario_approach_invalid", "role": role})
        try:
            x, y, yaw = float(approach["x"]), float(approach["y"]), float(approach["yaw"])
        except (KeyError, TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=400, detail={"code": "scenario_approach_invalid", "role": role}
            ) from exc
        if (
            not str(approach.get("waypoint_id") or "")
            or not all(math.isfinite(value) for value in (x, y, yaw))
            or not -math.pi <= yaw <= math.pi
        ):
            raise HTTPException(status_code=400, detail={"code": "scenario_approach_invalid", "role": role})
    if not callback_url:
        raise HTTPException(status_code=500, detail={"code": "scenario_callback_url_missing"})
    return {
        "contract_version": CONTRACT_VERSION,
        "command_id": command_id,
        "task_id": int(task_id),
        "robot_name": movement_robot_key(robot_id),
        "scenario_type": scenario_type,
        "map": params["map"],
        "pickup": params["pickup"],
        "dropoff": params["dropoff"],
        "callback_url": callback_url,
    }
