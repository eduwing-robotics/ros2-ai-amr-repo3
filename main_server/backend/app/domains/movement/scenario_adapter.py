"""책임: Scenario API v1 request 계약을 검증하고 Movement용 body로 변환한다.
비책임: 업무 위치 계획, Task 상태 전이와 물리 동작 완료 판정."""

from __future__ import annotations

import math
from typing import Any

from fastapi import HTTPException

from app.domains.movement.client import movement_robot_key

CONTRACT_VERSION = "1.0"
FRAME_ID = "map"
# 검증 좌표는 소수 셋째 자리 정본을 유지하므로 π의 반올림값 3.142까지 허용한다.
YAW_ROUNDING_TOLERANCE_RAD = 0.0005


def build_scenario_command(
    params: dict[str, Any], *, command_id: str, task_id: int | None, robot_id: str, callback_url: str
) -> dict[str, Any]:
    """검증된 Scenario body를 반환하며 반환은 Movement 접수나 물리 완료를 뜻하지 않는다."""
    if task_id is None:
        raise HTTPException(status_code=400, detail={"code": "scenario_task_id_required"})
    required = {"scenario_type", "map", "pickup", "dropoff"}
    if set(params) != required:
        raise HTTPException(status_code=400, detail={"code": "scenario_params_invalid", "fields": sorted(set(params) ^ required)})
    scenario_type = params.get("scenario_type")
    if scenario_type not in {"inbound", "outbound"}:
        raise HTTPException(status_code=400, detail={"code": "scenario_type_invalid"})
    map_context = params.get("map")
    if not isinstance(map_context, dict) or set(map_context) != {"map_id", "frame_id"}:
        raise HTTPException(status_code=400, detail={"code": "scenario_map_invalid"})
    if not str(map_context.get("map_id") or "") or map_context.get("frame_id") != FRAME_ID:
        raise HTTPException(status_code=400, detail={"code": "scenario_map_invalid"})
    for role in ("pickup", "dropoff"):
        _validate_location(params.get(role), role)
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


def _validate_location(location: object, role: str) -> None:
    if not isinstance(location, dict) or set(location) != {"location_id", "floor", "approach"}:
        raise HTTPException(status_code=400, detail={"code": "scenario_location_invalid", "role": role})
    if not str(location.get("location_id") or "") or location.get("floor") not in {1, 2}:
        raise HTTPException(status_code=400, detail={"code": "scenario_location_invalid", "role": role})
    approach = location.get("approach")
    if not isinstance(approach, dict) or set(approach) != {"waypoint_id", "x", "y", "yaw"}:
        raise HTTPException(status_code=400, detail={"code": "scenario_approach_invalid", "role": role})
    try:
        values = tuple(float(approach[key]) for key in ("x", "y", "yaw"))
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail={"code": "scenario_approach_invalid", "role": role}) from exc
    yaw_limit = math.pi + YAW_ROUNDING_TOLERANCE_RAD
    if (
        not str(approach.get("waypoint_id") or "")
        or not all(math.isfinite(value) for value in values)
        or not -yaw_limit <= values[2] <= yaw_limit
    ):
        raise HTTPException(status_code=400, detail={"code": "scenario_approach_invalid", "role": role})
