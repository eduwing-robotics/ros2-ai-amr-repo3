"""DBML evidence_events / safety_stops runtime helpers."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.core.config import settings
from app.db.postgres import locations, robot_command_definitions, runtime_records, safety_stops, tasks
from app.domains.execution import inout_scenarios
from app.domains.movement.commands import normalize_dock_transfer_params

CRITICAL_SEVERITIES = {"CRITICAL", "HIGH"}

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
        if action_type == "inout_scenario":
            steps.append(
                {
                    "seq": idx,
                    "kind": "inout_scenario",
                    "label": step.get("name") or "movement-scenario-v1",
                    "params": dict(step.get("params") or {}),
                    "status": "pending",
                    "command_id": None,
                    "route_timeline": inout_scenarios.business_timeline(),
                    "route_timeline_current_index": 0,
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


def build_scenario_from_task(conn, task: dict[str, Any]) -> dict[str, Any]:
    snap = task.get("preset_snapshot") or {}
    if snap.get("steps") or snap.get("map_id"):
        return snap

    task_type = str(task.get("task_type") or "").upper()
    if task_type in {"INBOUND", "OUTBOUND"}:
        return {
            "map_id": settings.movement_active_map_id,
            "steps": [{
                "action_type": "inout_scenario",
                "name": f"{task_type.lower()}-scenario-v1",
                "params": inout_scenarios.build_params(conn, task),
            }],
        }

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
