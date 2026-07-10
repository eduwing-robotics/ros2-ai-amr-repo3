"""Movement route helpers (goto) and command trace recording."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.api.helpers import command_events_callback_url
from app.db.repo_bridge import event_repo, movement_repo
from app.services.movement import MovementClientError, movement_client


def default_command_id(task_id: int | None, robot_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    prefix = f"task-{task_id}" if task_id is not None else "mission"
    return f"{prefix}-{robot_id}-scenario-{stamp}"


def default_route_command_id(task_id: int | None, robot_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    prefix = f"task-{task_id}" if task_id is not None else "coord"
    return f"{prefix}-{robot_id}-{stamp}"


def build_goto_route_request(request: dict[str, Any]) -> dict[str, Any]:
    command_id = request.get("command_id") or default_route_command_id(request.get("task_id"), request["robot_id"])
    body: dict[str, Any] = {
        "command_id": command_id,
        "task_id": request.get("task_id"),
        "robot_name": request["robot_id"],
        "x": request["x"],
        "y": request["y"],
        "yaw": request.get("yaw", 0.0),
        "waypoint": request.get("waypoint") or "operator_clicked_goal",
    }
    # Legacy route payloads may contain callback_base_url, but the destination
    # is Main configuration rather than a service/API caller capability.
    body["callback_url"] = command_events_callback_url()
    return body


def preview_goto_route(conn, robot_id: str, request: dict[str, Any]) -> dict[str, Any]:
    body = build_goto_route_request(request)
    try:
        response = movement_client.route_preview(robot_id, body)
    except MovementClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    record_mission_call(conn, body, robot_id, "route_preview", "PREVIEWED", response)
    return response


def start_goto_route(conn, robot_id: str, request: dict[str, Any]) -> dict[str, Any]:
    body = build_goto_route_request(request)
    try:
        response = movement_client.route_command(robot_id, body)
    except MovementClientError as exc:
        record_mission_call(conn, body, robot_id, "route_command", "FAILED", {"error": str(exc)})
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    status = "ACCEPTED" if response.get("accepted", True) else "REJECTED"
    record_mission_call(conn, body, robot_id, "route_command", status, response)
    event_repo(conn).append(
        event_type=f"ROUTE_COMMAND_{status}",
        robot_id=robot_id,
        command_id=body["command_id"],
        message=response.get("message") or response.get("state") or "route command submitted",
        payload=response,
    )
    return response


def command_status(robot_id: str, command_id: str) -> dict[str, Any]:
    try:
        return movement_client.command_status(robot_id, command_id)
    except MovementClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


def record_mission_call(conn, payload: dict[str, Any], robot_id: str, command_type: str, status: str, response: dict[str, Any]) -> None:
    command_id = payload.get("command_id") or default_command_id(payload.get("task_id"), robot_id)
    movement_repo(conn).create(
        command_id=command_id if command_type == "mission_start" else f"{command_id}-{command_type}",
        robot_id=robot_id,
        command_type=command_type,
        command=f"{command_type}:{payload.get('scenario', {}).get('preset_id') or payload.get('waypoint') or '-'}",
        status=status,
        request_payload=payload,
        response_payload=response,
    )
