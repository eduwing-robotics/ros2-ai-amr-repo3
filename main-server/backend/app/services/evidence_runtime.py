"""DBML evidence_events / safety_stops runtime helpers (PHASE_63)."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import HTTPException

from app.core.config import settings
from app.db.repo_bridge import command_repo, evidence_repo, location_repo, safety_stop_repo, task_repo
from app.services import field_bindings

logger = logging.getLogger(__name__)

CRITICAL_SEVERITIES = {"CRITICAL", "HIGH"}

# At the charge/home marker the parked robot is already about 0.30 m from the
# marker. Departure must add enough travel before Nav2 starts turning so the
# robot clears the adjacent charge bay. When marker ranging is unavailable,
# use the required conservative travel distance rather than Nav's generic
# 0.20 m fallback.
HOME_DEPARTURE_MARKER_CLEARANCE_M = 0.70
HOME_DEPARTURE_FALLBACK_M = 0.50


def attach_orchestration(task: dict[str, Any] | None, conn) -> dict[str, Any] | None:
    if not task:
        return None
    orch = evidence_repo(conn).get_orchestration(int(task["task_id"]))
    if orch:
        snap = dict(task.get("preset_snapshot") or {})
        snap["_orchestration"] = orch
        task = dict(task)
        task["preset_snapshot"] = snap
    return task


def save_orchestration(conn, task_id: int, orchestration: dict[str, Any]) -> None:
    evidence_repo(conn).save_orchestration(task_id, orchestration)


def list_orchestrated_running(conn, limit: int = 50) -> list[dict[str, Any]]:
    rows = task_repo(conn).list(limit=limit, status="RUNNING")
    out: list[dict[str, Any]] = []
    for row in rows:
        enriched = attach_orchestration(row, conn)
        if enriched and (enriched.get("preset_snapshot") or {}).get("_orchestration"):
            out.append(enriched)
    return out


def _require_location(conn, location_id: str, *, label: str) -> dict[str, Any]:
    loc = location_repo(conn).get(location_id)
    if not loc:
        raise HTTPException(status_code=409, detail=f"{label} location not found: {location_id}")
    if loc.get("x") is None or loc.get("y") is None:
        raise HTTPException(status_code=409, detail=f"{label} location missing coordinates: {location_id}")
    # Repository-backed rows always carry map_id.  Keeping old isolated unit
    # doubles (which predate the column) usable avoids weakening production
    # validation: every real task location is checked against the field file.
    if loc.get("map_id") is not None:
        field_bindings.validate_runtime_location(loc, location_id)
    return loc


def _resolve_scan_for_dock(conn, dock_id: str) -> dict[str, Any]:
    scan_id, _ = field_bindings.scan_binding_for(dock_id)
    scan = location_repo(conn).get(scan_id)
    if not scan or scan.get("x") is None or scan.get("y") is None:
        raise HTTPException(
            status_code=409,
            detail=f"scan approach missing for dock {dock_id} (expected location id {scan_id})",
        )
    if scan.get("map_id") is not None:
        field_bindings.validate_runtime_location(scan, scan_id, scan=True)
    return scan


def _aruco_marker_for_dock(conn, dock_id: str, scan: dict[str, Any]) -> int:
    marker = scan.get("marker_id")
    if marker is None:
        raise HTTPException(status_code=409, detail=f"dock {dock_id} missing aruco_marker_id")
    try:
        return int(marker)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=f"dock {dock_id} invalid aruco_marker_id") from exc


def _move_step(
    scan: dict[str, Any],
    *,
    name: str,
    command_sequence_no: int | None = None,
    human_hazard_monitor: bool = True,
) -> dict[str, Any]:
    step = {
        "action_type": "move",
        "name": name,
        "waypoint_id": scan.get("slot_id") or scan.get("location_id"),
        "x": float(scan["x"]),
        "y": float(scan["y"]),
        "yaw": float(scan.get("yaw") or 0.0),
    }
    if command_sequence_no is not None:
        step["command_sequence_no"] = int(command_sequence_no)
    # Persist an explicit false as well. A missing key is reserved for legacy
    # orchestration snapshots and is handled conservatively on upgrade.
    step["human_hazard_monitor"] = bool(human_hazard_monitor)
    return step


def _append_route_and_scan(
    conn,
    steps: list[dict[str, Any]],
    scan: dict[str, Any],
    *,
    scan_name: str,
    command_sequence_no: int | None = None,
    human_hazard_monitor: bool = True,
) -> None:
    scan_id = str(scan.get("slot_id") or scan.get("location_id") or "")
    scan_map_id = scan.get("map_id")
    seen = {scan_id}
    for route_step in location_repo(conn).list_route_steps(scan_id):
        waypoint_id = str(route_step.get("slot_id") or route_step.get("location_id") or "")
        if waypoint_id in seen:
            continue
        if route_step.get("type") != "transit":
            raise HTTPException(status_code=409, detail=f"scan route step is not transit: {waypoint_id}")
        if route_step.get("x") is None or route_step.get("y") is None:
            raise HTTPException(status_code=409, detail=f"scan route step missing coordinates: {waypoint_id}")
        if not scan_map_id or route_step.get("map_id") != scan_map_id:
            raise HTTPException(status_code=409, detail=f"scan route step map mismatch: {waypoint_id}")
        # Transit waypoints and the final scan pose are implementation details of
        # one logical recipe command.  They therefore share commands.sequence_no
        # instead of consuming extra command definitions as the route grows.
        steps.append(
            _move_step(
                route_step,
                name=f"route:{waypoint_id}",
                command_sequence_no=command_sequence_no,
                human_hazard_monitor=human_hazard_monitor,
            )
        )
        seen.add(waypoint_id)
    steps.append(
        _move_step(
            scan,
            name=scan_name,
            command_sequence_no=command_sequence_no,
            human_hazard_monitor=human_hazard_monitor,
        )
    )


def _dock_step(
    conn,
    dock_id: str,
    scan: dict[str, Any],
    action: str,
    floor: int,
    *,
    command_sequence_no: int,
    evidence_sequence_no: int,
) -> dict[str, Any]:
    marker_id = _aruco_marker_for_dock(conn, dock_id, scan)
    params: dict[str, Any] = {
        "aruco_marker_id": marker_id,
        "action": action,
        "level": floor,
    }
    if action == "load" and floor == 1:
        # The field-proven level-1 sequence begins from raw lift home (0 mm).
        # Use the existing dock_transfer pre-insert phase instead of adding a
        # second lift-only orchestration API.
        params.update({"pre_insert_lift_mm": 0, "pre_insert_force_move": True})
    return {
        "action_type": "dock_transfer",
        "name": f"dock:{dock_id}:{action}",
        "params": params,
        "command_sequence_no": int(command_sequence_no),
        "evidence_sequence_no": int(evidence_sequence_no),
        "human_hazard_monitor": False,
    }


def _append_dock_gate(
    conn,
    steps: list[dict[str, Any]],
    dock_id: str,
    action: str,
    floor: int,
    *,
    move_sequence_no: int,
    dock_sequence_no: int,
    evidence_sequence_no: int,
    human_hazard_monitor: bool = True,
) -> None:
    scan = _resolve_scan_for_dock(conn, dock_id)
    _require_location(conn, dock_id, label="dock")
    _append_route_and_scan(
        conn,
        steps,
        scan,
        scan_name=f"scan:{scan.get('slot_id') or dock_id}",
        command_sequence_no=move_sequence_no,
        human_hazard_monitor=human_hazard_monitor,
    )
    steps.append(
        _dock_step(
            conn,
            dock_id,
            scan,
            action,
            floor,
            command_sequence_no=dock_sequence_no,
            evidence_sequence_no=evidence_sequence_no,
        )
    )


def _append_aruco_align_gate(
    conn,
    steps: list[dict[str, Any]],
    location_id: str,
    *,
    label: str,
    move_sequence_no: int,
    align_sequence_no: int | None = None,
) -> None:
    """Append a scan move and its non-lift final ArUco alignment."""
    scan = _resolve_scan_for_dock(conn, location_id)
    _require_location(conn, location_id, label=label)
    marker = _aruco_marker_for_dock(conn, location_id, scan)
    _append_route_and_scan(
        conn,
        steps,
        scan,
        scan_name=f"scan:{scan.get('slot_id') or location_id}",
        command_sequence_no=move_sequence_no,
    )
    align_step = {
        "action_type": "aruco_align",
        "name": f"{label}:{location_id}",
        "params": {"aruco_marker_id": marker, "final": label},
        "human_hazard_monitor": False,
    }
    # For return-home the final alignment is part of the same logical movement
    # recipe.  CHARGE has a dedicated alignment recipe step.
    align_step["command_sequence_no"] = int(align_sequence_no or move_sequence_no)
    steps.append(align_step)

def _build_inout_scenario(conn, task: dict[str, Any]) -> dict[str, Any]:
    task_type = str(task.get("task_type") or "").upper()
    floor = int(task.get("to_floor") or task.get("from_floor") or 1)
    home_id = field_bindings.home_location_for_robot(task.get("assigned_robot_id"))
    preset = task.get("preset_snapshot") if isinstance(task.get("preset_snapshot"), dict) else {}
    reserved = preset.get("_orchestration") if isinstance(preset.get("_orchestration"), dict) else {}
    chain_context = reserved.get("chain_context") if isinstance(reserved.get("chain_context"), dict) else {}
    start_dock_id = str(chain_context.get("start_dock_location_id") or home_id)
    steps: list[dict[str, Any]] = []

    # 항상 현재 도크에서 출차(후진)로 시작한다. 일반 작업은 로봇별 HOME,
    # 연속 작업은 직전 작업의 하역 도크가 시작점이다. 정확한 마커·pose를
    # 보내 Nav가 stale process state보다 fresh physical evidence를 우선한다.
    start_binding = field_bindings.binding_for(start_dock_id)
    _, start_scan = field_bindings.scan_binding_for(start_dock_id)
    start_pose = start_binding["pose"]
    leave_dock_params: dict[str, Any] = {
        "aruco_marker_id": int(start_scan["marker_id"]),
        "parking_pose": {
            "map_id": str(start_binding["map_id"]),
            "x": float(start_pose["x"]),
            "y": float(start_pose["y"]),
            "yaw": float(start_pose["yaw"]),
        },
    }
    if start_binding["kind"] == "home":
        leave_dock_params.update({
            "reverse_clearance_marker_distance_m": HOME_DEPARTURE_MARKER_CLEARANCE_M,
            "reverse_clearance_fallback_m": HOME_DEPARTURE_FALLBACK_M,
        })
    steps.append({
        "action_type": "leave_dock",
        "name": "leave_dock",
        "params": leave_dock_params,
        "human_hazard_monitor": False,
    })

    if task_type == "INBOUND":
        inbound_id = task.get("from_location_id")
        storage_id = task.get("to_location_id")
        if not inbound_id or not storage_id:
            raise HTTPException(status_code=409, detail="inbound task missing from/to locations")
        map_id = field_bindings.map_for_locations([str(inbound_id), str(storage_id), home_id, start_dock_id])
        _append_dock_gate(
            conn,
            steps,
            str(inbound_id),
            "load",
            floor,
            move_sequence_no=1,
            dock_sequence_no=2,
            evidence_sequence_no=3,
        )
        _append_dock_gate(
            conn,
            steps,
            str(storage_id),
            "unload",
            floor,
            move_sequence_no=4,
            dock_sequence_no=6,
            evidence_sequence_no=5,
            human_hazard_monitor=True,
        )
    elif task_type == "OUTBOUND":
        storage_id = task.get("from_location_id")
        outbound_id = task.get("to_location_id")
        if not storage_id or not outbound_id:
            raise HTTPException(status_code=409, detail="outbound task missing from/to locations")
        map_id = field_bindings.map_for_locations([str(storage_id), str(outbound_id), home_id, start_dock_id])
        _append_dock_gate(
            conn,
            steps,
            str(storage_id),
            "load",
            floor,
            move_sequence_no=1,
            dock_sequence_no=2,
            evidence_sequence_no=3,
        )
        _append_dock_gate(
            conn,
            steps,
            str(outbound_id),
            "unload",
            floor,
            move_sequence_no=4,
            dock_sequence_no=6,
            evidence_sequence_no=5,
            human_hazard_monitor=True,
        )
    else:
        raise HTTPException(status_code=409, detail=f"unsupported in/out task_type={task_type}")

    _require_location(conn, home_id, label="home")
    # Lift work completes only after a configured scan approach and final ArUco park.
    # A missing or malformed home/park setup blocks scenario creation instead of
    # silently degrading a cargo-return task to an imprecise plain move.
    _append_aruco_align_gate(conn, steps, home_id, label="park", move_sequence_no=7)

    return {"map_id": map_id, "steps": steps, "start_location_id": start_dock_id}


def build_scenario_from_task(conn, task: dict[str, Any]) -> dict[str, Any]:
    snap = task.get("preset_snapshot") or {}
    if snap.get("steps") or snap.get("map_id"):
        return snap

    task_type = str(task.get("task_type") or "").upper()
    if task_type in {"INBOUND", "OUTBOUND"}:
        return _build_inout_scenario(conn, task)
    if task_type == "CHARGE":
        charge_id = task.get("to_location_id") or task.get("from_location_id")
        if not charge_id:
            raise HTTPException(status_code=409, detail="charge task missing charge location")
        map_id = field_bindings.map_for_locations([str(charge_id)])
        steps = [{
            "action_type": "leave_dock",
            "name": "leave_dock",
            "params": {},
            "human_hazard_monitor": False,
        }]
        _append_aruco_align_gate(
            conn,
            steps,
            str(charge_id),
            label="charge",
            move_sequence_no=1,
            align_sequence_no=2,
        )
        return {"map_id": map_id, "steps": steps}

    map_id = settings.movement_active_map_id
    steps: list[dict[str, Any]] = []
    for loc_key, label in (
        ("from_location_id", "from"),
        ("to_location_id", "to"),
    ):
        loc_id = task.get(loc_key)
        if not loc_id:
            continue
        loc = location_repo(conn).get(loc_id)
        if loc and loc.get("x") is not None and loc.get("y") is not None:
            steps.append({
                "action_type": "move",
                "name": f"{label}:{loc_id}",
                "x": float(loc["x"]),
                "y": float(loc["y"]),
                "yaw": float(loc.get("yaw") or 0.0),
                "human_hazard_monitor": True,
            })
    if not steps and task.get("to_location_id"):
        loc = location_repo(conn).get(task["to_location_id"])
        if loc:
            steps.append({
                "action_type": "move",
                "name": task["to_location_id"],
                "x": float(loc.get("x") or 0),
                "y": float(loc.get("y") or 0),
                "human_hazard_monitor": True,
            })
    return {"map_id": map_id, "steps": steps}


def resolve_command_def_id(
    conn,
    task: dict[str, Any],
    cursor: int,
    leg_kind: str | None,
    *,
    sequence_no: int | None = None,
) -> int | None:
    """Map one logical recipe sequence to static ``commands.id``.

    ``cursor`` remains as a legacy fallback for old orchestration snapshots.
    New runtime steps carry ``command_sequence_no`` so extra transit waypoints do
    not shift the DB recipe mapping.
    """
    task_type = str(task.get("task_type") or "MOVE").upper()
    resolved_sequence = int(sequence_no) if sequence_no is not None else cursor + 1
    return command_repo(conn).resolve_for_leg(
        task_type,
        resolved_sequence,
        None if sequence_no is not None else leg_kind,
    )


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
    ev_id = evidence_repo(conn).append(
        task_id=task_id,
        command_id=command_def_id,
        event_type=event_type,
        source=source,
        severity=severity,
        trusted=trusted,
        data_json=data_json or {},
    )
    if severity and severity.upper() in CRITICAL_SEVERITIES and trusted:
        safety_stop_repo(conn).open_from_evidence(ev_id)
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
    evidence = evidence_repo(conn).list_for_task(task_id, limit=50)
    compact = [{"event_type": e["event_type"], "source": e["source"], "observed_at": e["observed_at"]} for e in evidence[:20]]
    task_repo(conn).append_task_log(
        task_id=task_id,
        task_type=task_type,
        result=result,
        error_reason=error_reason,
        summary=summary or f"task {task_id} {result.lower()}",
        snapshot={"task": task, "evidence": compact},
    )


def derived_movement_commands(conn, limit: int = 50) -> list[dict[str, Any]]:
    """Evidence-based movement timeline for /comm/logs facade."""
    rows = evidence_repo(conn).list(limit=limit)
    out: list[dict[str, Any]] = []
    for row in rows:
        if row.get("source") not in {"movement", "orchestrator", "runtime"}:
            continue
        data = row.get("data_json") or {}
        out.append({
            "command_id": str(data.get("movement_command_id") or data.get("command_id") or row["id"]),
            "robot_id": data.get("robot_id"),
            "command_type": row["event_type"],
            "command": data.get("command") or row["event_type"],
            "status": data.get("status") or row["event_type"],
            "request_payload": data.get("request") or data,
            "response_payload": data.get("response") or {},
            "created_at": row.get("observed_at") or "",
            "layer": "dbml",
            "source_table": "evidence_events",
        })
    return out[:limit]
