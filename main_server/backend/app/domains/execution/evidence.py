"""DBML evidence_events / safety_stops runtime helpers."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from app.core.config import settings
from app.db.postgres import locations, robot_command_definitions, runtime_records, safety_stops, tasks
from app.domains.movement.client import movement_robot_key
from app.domains.movement.commands import normalize_dock_transfer_params

logger = logging.getLogger(__name__)

CRITICAL_SEVERITIES = {"CRITICAL", "HIGH"}

MOVEMENT_SECTION_IDS = {
    "INBOUND_01": "inbound_slot_1",
    "INBOUND_02": "inbound_slot_2",
    "OUTBOUND_01": "outbound_slot_1",
    "OUTBOUND_02": "outbound_slot_2",
    "STORAGE_01": "warehouse_section_b",
    "STORAGE_02": "warehouse_section_a",
    "STORAGE_03": "warehouse_section_d",
    "STORAGE_04": "warehouse_section_c",
    "STORAGE_S1": "warehouse_section_a",
    "STORAGE_S2": "warehouse_section_b",
    "STORAGE_S3": "warehouse_section_c",
    "STORAGE_S4": "warehouse_section_d",
}

MOVEMENT_STORAGE_ROUTE_ITEMS = {
    "warehouse_section_a": "bolt",
    "warehouse_section_b": "nut",
    "warehouse_section_c": "wire",
    "warehouse_section_d": "rubber_packing",
}


def plan_command_steps(conn, scenario: dict[str, Any], task_id: int, robot_id: str) -> list[dict[str, Any]]:
    map_id = scenario.get("map_id")
    if not map_id:
        raise HTTPException(status_code=409, detail="scenario missing map_id")
    waypoints = {w["waypoint_id"]: w for w in locations.list_map_markers(conn, map_id=map_id)}
    raw_steps = sorted(scenario.get("steps") or [], key=lambda item: item.get("seq", 0))
    if not raw_steps:
        raise HTTPException(status_code=409, detail="scenario has no steps")

    steps: list[dict[str, Any]] = []
    for idx, step in enumerate(raw_steps, start=1):
        action_type = str(step.get("action_type") or "move")
        if action_type == "scenario":
            steps.append(
                {
                    "seq": idx,
                    "kind": "scenario",
                    "label": step.get("name") or "movement-owned-scenario",
                    "params": dict(step.get("params") or {}),
                    "status": "pending",
                    "command_id": None,
                }
            )
            continue
        if action_type == "route":
            steps.append(
                {
                    "seq": idx,
                    "kind": "route",
                    "label": step.get("name") or "movement-owned-route",
                    "params": dict(step.get("params") or {}),
                    "status": "pending",
                    "command_id": None,
                }
            )
            continue
        if action_type == "dock_transfer":
            params = dict(step.get("params") or {})
            normalized = normalize_dock_transfer_params(
                params,
                status_code=409,
                detail_prefix=f"dock_transfer step {idx}",
            )
            steps.append(
                {
                    "seq": idx,
                    "kind": "dock_transfer",
                    "label": step.get("name") or f"dock-{idx}",
                    "params": normalized,
                    "status": "pending",
                    "command_id": None,
                }
            )
            continue

        if action_type in ("leave_dock", "aruco_align"):
            steps.append(
                {
                    "seq": idx,
                    "kind": action_type,
                    "label": step.get("name") or f"{action_type}-{idx}",
                    "params": dict(step.get("params") or {}),
                    "status": "pending",
                    "command_id": None,
                }
            )
            continue

        waypoint_id = step.get("waypoint_id")
        waypoint = waypoints.get(waypoint_id)
        if waypoint:
            params = {"waypoint_id": str(waypoint_id)}
            label = step.get("name") or waypoint.get("name") or f"step-{idx}"
        elif step.get("x") is not None and step.get("y") is not None:
            params = {
                "map_id": map_id,
                "x": float(step["x"]),
                "y": float(step["y"]),
                "yaw": float(step.get("yaw", 0.0)),
            }
            label = step.get("name") or f"step-{idx}"
        else:
            raise HTTPException(status_code=409, detail=f"step {idx} has no pose")
        planned_step = {
            "seq": idx,
            "kind": "move_to_point",
            "label": label,
            "params": params,
            "status": "pending",
            "command_id": None,
        }
        if step.get("transfer_action") in {"load", "unload"}:
            planned_step["transfer_action"] = step["transfer_action"]
            planned_step["transfer_level"] = int(step.get("transfer_level") or 1)
        steps.append(planned_step)
    return steps


def attach_orchestration(task: dict[str, Any] | None, conn) -> dict[str, Any] | None:
    if not task:
        return None
    orch = runtime_records.get_orchestration(conn, int(task["task_id"]))
    if orch:
        snap = dict(task.get("preset_snapshot") or {})
        snap["_orchestration"] = orch
        task = dict(task)
        task["preset_snapshot"] = snap
    return task


def save_orchestration(conn, task_id: int, orchestration: dict[str, Any]) -> None:
    runtime_records.save_orchestration(conn, task_id, orchestration)


def list_orchestrated_running(conn, limit: int = 50) -> list[dict[str, Any]]:
    rows = tasks.list_tasks(conn, limit=limit, status="RUNNING")
    out: list[dict[str, Any]] = []
    for row in rows:
        enriched = attach_orchestration(row, conn)
        if enriched and (enriched.get("preset_snapshot") or {}).get("_orchestration"):
            out.append(enriched)
    return out


def _scan_id_for_dock(dock_id: str) -> str:
    return f"scan_{dock_id}"


def _require_location(conn, location_id: str, *, label: str) -> dict[str, Any]:
    loc = locations.get_location(conn, location_id)
    if not loc:
        raise HTTPException(status_code=409, detail=f"{label} location not found: {location_id}")
    if loc.get("x") is None or loc.get("y") is None:
        raise HTTPException(status_code=409, detail=f"{label} location missing coordinates: {location_id}")
    return loc


def _resolve_scan_for_dock(conn, dock_id: str) -> dict[str, Any]:
    scan_id = _scan_id_for_dock(dock_id)
    scan = locations.get_location(conn, scan_id)
    if scan and scan.get("x") is not None and scan.get("y") is not None:
        return scan
    dock = locations.get_location(conn, dock_id)
    if dock and dock.get("marker_id") is not None:
        for candidate in locations.list_by_type(conn, "scan"):
            if candidate.get("marker_id") == dock.get("marker_id"):
                if candidate.get("x") is not None and candidate.get("y") is not None:
                    return candidate
    raise HTTPException(
        status_code=409,
        detail=f"scan approach missing for dock {dock_id} (expected location id {scan_id})",
    )


def _aruco_marker_for_dock(conn, dock_id: str, scan: dict[str, Any]) -> int:
    marker = scan.get("marker_id")
    if marker is None:
        dock = locations.get_location(conn, dock_id)
        marker = dock.get("marker_id") if dock else None
    if marker is None:
        raise HTTPException(status_code=409, detail=f"dock {dock_id} missing aruco_marker_id")
    return int(marker)


def _move_step(
    scan: dict[str, Any],
    *,
    name: str,
    transfer_action: str | None = None,
    transfer_level: int | None = None,
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "action_type": "move",
        "name": name,
        "waypoint_id": scan.get("slot_id") or scan.get("location_id"),
        "x": float(scan["x"]),
        "y": float(scan["y"]),
        "yaw": float(scan.get("yaw") or 0.0),
    }
    if transfer_action:
        step["transfer_action"] = transfer_action
        step["transfer_level"] = int(transfer_level or 1)
    return step


def _append_dock_gate(
    conn,
    steps: list[dict[str, Any]],
    dock_id: str,
    action: str,
    floor: int,
) -> None:
    scan = _resolve_scan_for_dock(conn, dock_id)
    _require_location(conn, dock_id, label="dock")
    # Movement expands this canonical waypoint into Nav2 + ArUco 0.4m + wait +
    # straight insert 0.2m. A second dock_transfer would repeat the insertion.
    steps.append(
        _move_step(
            scan,
            name=f"precision:{scan.get('slot_id') or dock_id}:{action}",
            transfer_action=action,
            transfer_level=floor,
        )
    )


def _append_park_gate(conn, steps: list[dict[str, Any]], dock_id: str) -> None:
    """정밀 주차: home approach 이동 후 ArUco 정밀 정렬(aruco_align, 리프트 없음)."""
    scan = _resolve_scan_for_dock(conn, dock_id)
    _require_location(conn, dock_id, label="park")
    marker = _aruco_marker_for_dock(conn, dock_id, scan)
    steps.append(_move_step(scan, name=f"scan:{scan.get('slot_id') or dock_id}"))
    steps.append(
        {
            "action_type": "aruco_align",
            "name": f"park:{dock_id}",
            "params": {"aruco_marker_id": marker, "final": "park"},
        }
    )


def _build_inout_scenario(conn, task: dict[str, Any]) -> dict[str, Any]:
    task_type = str(task.get("task_type") or "").upper()
    map_id = settings.movement_active_map_id
    floor = int(task.get("to_floor") or task.get("from_floor") or 1)
    steps: list[dict[str, Any]] = []

    # 항상 출차(후진)로 시작: 미도킹 상태면 이동서버가 no-op 처리한다(계약 §3.4/§5).
    steps.append({"action_type": "leave_dock", "name": "leave_dock", "params": {}})

    if task_type == "INBOUND":
        inbound_id = task.get("from_location_id")
        storage_id = task.get("to_location_id")
        if not inbound_id or not storage_id:
            raise HTTPException(status_code=409, detail="inbound task missing from/to locations")
        _append_dock_gate(conn, steps, str(inbound_id), "load", floor)
        _append_dock_gate(conn, steps, str(storage_id), "unload", floor)
    elif task_type == "OUTBOUND":
        storage_id = task.get("from_location_id")
        outbound_id = task.get("to_location_id")
        if not storage_id or not outbound_id:
            raise HTTPException(status_code=409, detail="outbound task missing from/to locations")
        _append_dock_gate(conn, steps, str(storage_id), "load", floor)
        _append_dock_gate(conn, steps, str(outbound_id), "unload", floor)
    else:
        raise HTTPException(status_code=409, detail=f"unsupported in/out task_type={task_type}")

    waiting = locations.get_location(conn, "vehicle_2_approach")
    if waiting:
        home = waiting
    else:
        home_rows = locations.list_by_type(conn, "home")
        if not home_rows:
            raise HTTPException(status_code=409, detail="home location not configured")
        home = home_rows[0]
    if home.get("x") is None or home.get("y") is None:
        raise HTTPException(status_code=409, detail="home location missing coordinates")
    home_id = str(home.get("slot_id") or home.get("location_id"))
    # 새 계약은 대기2(vehicle_2)를 canonical 복귀 지점으로 사용한다. 구형 DB만 home으로 폴백한다.
    try:
        _append_park_gate(conn, steps, home_id)
    except HTTPException as exc:
        logger.warning(
            "park gate unavailable for home %s (%s) — falling back to plain move",
            home_id,
            exc.detail,
        )
        steps.append(_move_step(home, name=f"home:{home_id}"))

    return {"map_id": map_id, "steps": steps}


def _is_inbound2_storage_b_contract(task: dict[str, Any]) -> bool:
    if not settings.inbound2_storage_b_scenario_enabled:
        return False
    robot_id = str(task.get("assigned_robot_id") or "")
    try:
        to_floor = int(task.get("to_floor") or 0)
    except (TypeError, ValueError):
        return False
    return (
        str(task.get("task_type") or "").upper() == "INBOUND"
        and str(task.get("from_location_id") or "").upper() == "INBOUND_02"
        and str(task.get("to_location_id") or "").upper() == "STORAGE_01"
        and to_floor == 2
        and movement_robot_key(robot_id) == "tb3_2"
    )


def _build_inbound2_storage_b_contract() -> dict[str, Any]:
    """문서 검증본: Main은 한 명령만 보내고 Movement가 내부 9단계를 소유한다."""
    return {
        "map_id": settings.movement_active_map_id,
        "steps": [
            {
                "action_type": "scenario",
                "name": "inbound2-storage-b",
                "params": {
                    "scenario_id": settings.inbound2_storage_b_scenario_id,
                    "scenario_version": settings.inbound2_storage_b_scenario_version,
                    "expected_plan_hash": settings.inbound2_storage_b_plan_hash,
                    "skip_lift": settings.inbound2_storage_b_skip_lift,
                },
            }
        ],
    }


def _build_inout_route_contract(task: dict[str, Any]) -> dict[str, Any]:
    task_type = str(task.get("task_type") or "").upper()
    floor_value = task.get("to_floor") if task_type == "INBOUND" else task.get("from_floor")
    floor = int(floor_value or 1)
    if floor != 1:
        raise HTTPException(status_code=409, detail="movement_route_floor_not_supported")
    source = MOVEMENT_SECTION_IDS.get(str(task.get("from_location_id") or "").upper())
    target = MOVEMENT_SECTION_IDS.get(str(task.get("to_location_id") or "").upper())
    if not source or not target:
        raise HTTPException(status_code=409, detail="movement_route_section_not_mapped")
    item_id = str(task.get("item_id") or "").strip()
    if not item_id:
        raise HTTPException(status_code=409, detail="movement_route_item_missing")
    storage_section = target if task_type == "INBOUND" else source
    item_name = MOVEMENT_STORAGE_ROUTE_ITEMS.get(storage_section)
    if not item_name:
        raise HTTPException(status_code=409, detail="movement_route_storage_profile_missing")
    robot_id = str(task.get("assigned_robot_id") or "")
    return {
        "map_id": settings.movement_active_map_id,
        "steps": [{
            "action_type": "route",
            "name": f"{task_type.lower()}-route",
            "params": {
                "route_type": task_type.lower(),
                "item_name": item_name,
                "count": int(task.get("quantity") or 1),
                "source_section_id": source,
                "target_section_id": target,
                "return_waypoint": "vehicle_2_approach" if movement_robot_key(robot_id) == "tb3_2" else "vehicle_1_approach",
            },
        }],
    }


def build_scenario_from_task(conn, task: dict[str, Any]) -> dict[str, Any]:
    snap = task.get("preset_snapshot") or {}
    if snap.get("steps") or snap.get("map_id"):
        return snap

    if _is_inbound2_storage_b_contract(task):
        return _build_inbound2_storage_b_contract()

    task_type = str(task.get("task_type") or "").upper()
    if task_type in {"INBOUND", "OUTBOUND"}:
        if task.get("item_id"):
            return _build_inout_route_contract(task)
        return _build_inout_scenario(conn, task)

    map_id = settings.movement_active_map_id
    steps: list[dict[str, Any]] = []
    for loc_key, label in (
        ("from_location_id", "from"),
        ("to_location_id", "to"),
    ):
        loc_id = task.get(loc_key)
        if not loc_id:
            continue
        loc = locations.get_location(conn, loc_id)
        if loc and loc.get("x") is not None and loc.get("y") is not None:
            steps.append(
                {
                    "action_type": "move",
                    "name": f"{label}:{loc_id}",
                    "x": float(loc["x"]),
                    "y": float(loc["y"]),
                    "yaw": float(loc.get("yaw") or 0.0),
                }
            )
    if not steps and task.get("to_location_id"):
        loc = locations.get_location(conn, task["to_location_id"])
        if loc:
            steps.append(
                {
                    "action_type": "move",
                    "name": task["to_location_id"],
                    "x": float(loc.get("x") or 0),
                    "y": float(loc.get("y") or 0),
                }
            )
    return {"map_id": map_id, "steps": steps}


def resolve_command_def_id(conn, task: dict[str, Any], step_index: int, step_kind: str) -> int | None:
    """Map the orchestration step index to static commands.id."""
    task_type = str(task.get("task_type") or "MOVE").upper()
    return robot_command_definitions.resolve_for_step(conn, task_type, step_index + 1, step_kind)


def record_movement_evidence(
    conn,
    *,
    task_id: int | None,
    command_def_id: int | None,
    event_type: str,
    source: str = "movement",
    data_json: dict[str, Any] | None = None,
    severity: str | None = None,
    trusted: bool = True,
) -> int:
    ev_id = runtime_records.append(
        conn,
        task_id=task_id,
        command_id=command_def_id,
        event_type=event_type,
        source=source,
        severity=severity,
        trusted=trusted,
        data_json=data_json or {},
    )
    if severity and severity.upper() in CRITICAL_SEVERITIES and trusted:
        safety_stops.open_from_evidence(conn, ev_id)
    return ev_id


def finalize_task_log(
    conn,
    task: dict[str, Any],
    result: str,
    *,
    error_reason: str | None = None,
    summary: str | None = None,
) -> None:
    task_id = int(task["task_id"])
    task_type = str(task.get("task_type") or "MOVE")
    evidence = runtime_records.list_for_task(conn, task_id, limit=50)
    compact = [
        {"event_type": e["event_type"], "source": e["source"], "observed_at": e["observed_at"]} for e in evidence[:20]
    ]
    tasks.append_task_log(
        conn,
        task_id=task_id,
        task_type=task_type,
        result=result,
        error_reason=error_reason,
        summary=summary or f"task {task_id} {result.lower()}",
        snapshot={"task": task, "evidence": compact},
    )
