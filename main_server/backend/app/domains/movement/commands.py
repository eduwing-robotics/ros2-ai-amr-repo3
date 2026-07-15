"""Robot command envelope dispatch.

단일 POST /robot-commands + kind 로 이동·수동조작·estop 을 라우팅한다.
DB robot_commands 테이블 저장은 Phase C 이후 — 기존 movement_commands 기록 경로는 유지한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Request

from app.api.helpers import callback_base_url
from app.db.postgres import operational_events, robots
from app.domains.movement import missions
from app.domains.movement.client import MovementClientError, movement_client, movement_robot_key
from app.domains.movement.navigation import resolve_movement_map_id
from app.domains.movement.teleop import execute_teleop
from app.models.movement import MissionStatusResponse
from app.models.robot_commands import RobotCommandRequest, RobotCommandResponse
from app.models.robots import TeleopRequest


def default_command_id(task_id: int | None, robot_id: str, kind: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
    prefix = f"task-{task_id}" if task_id is not None else "cmd"
    return f"{prefix}-{robot_id}-{kind}-{stamp}"


def to_mission_status(result: RobotCommandResponse) -> MissionStatusResponse:
    return MissionStatusResponse(
        robot_id=result.robot_id,
        command_id=result.command_id,
        response=result.response,
    )


def resolve_callback_url(request: Request | None, override: str | None) -> str:
    if override:
        base = override.rstrip("/")
        if base.endswith("/movement/command-events"):
            return base
        return f"{base}/movement/command-events"
    if request is None:
        return ""
    return f"{callback_base_url(request)}/movement/command-events"


def dispatch_robot_command(conn, payload: RobotCommandRequest, request: Request | None = None) -> RobotCommandResponse:
    if not robots.exists(conn, payload.robot_id):
        raise HTTPException(status_code=404, detail="robot not found")

    command_id = payload.command_id or default_command_id(payload.task_id, payload.robot_id, payload.kind)
    callback_url = payload.callback_url or resolve_callback_url(request, None)

    if payload.kind == "move_to_point":
        return _dispatch_move_to_point(conn, payload, command_id, callback_url)
    if payload.kind == "manual_drive":
        return _dispatch_manual_drive(payload, command_id)
    if payload.kind == "estop":
        return _dispatch_estop(payload, command_id)
    if payload.kind == "dock_transfer":
        return _dispatch_dock_transfer(payload, command_id, callback_url)
    if payload.kind == "aruco_align":
        return _dispatch_aruco_align(payload, command_id, callback_url)
    if payload.kind == "leave_dock":
        return _dispatch_leave_dock(payload, command_id, callback_url)

    raise HTTPException(status_code=400, detail=f"unsupported kind={payload.kind}")


def _callback_base(callback_url: str) -> str | None:
    if not callback_url:
        return None
    return callback_url.removesuffix("/movement/command-events").rstrip("/") or None


def _dispatch_move_to_point(
    conn, payload: RobotCommandRequest, command_id: str, callback_url: str
) -> RobotCommandResponse:
    p = payload.params
    waypoint_id = str(p.get("waypoint_id") or "").strip()
    if waypoint_id:
        passthrough = RobotCommandRequest(
            robot_id=payload.robot_id,
            kind=payload.kind,
            command_id=payload.command_id,
            task_id=payload.task_id,
            dry_run=payload.dry_run,
            params={"waypoint_id": waypoint_id},
            callback_url=payload.callback_url,
        )
        result = _dispatch_passthrough(passthrough, command_id, callback_url)
        operational_events.append(
            conn,
            event_type="MOVEMENT_COMMAND_WAYPOINT_CONTEXT",
            robot_id=payload.robot_id,
            command_id=result.command_id,
            message=f"waypoint={waypoint_id}",
            payload={"waypoint_id": waypoint_id},
        )
        return result

    for key in ("map_id", "x", "y"):
        if key not in p:
            raise HTTPException(status_code=400, detail=f"move_to_point.params.{key} required")
    lms_map_id = str(p["map_id"])
    movement_map_id, map_state = resolve_movement_map_id(lms_map_id, payload.robot_id)
    map_context = {
        "ui_map_id": lms_map_id,
        "runtime_map_id": movement_map_id,
        "runtime_confidence": map_state.get("confidence"),
    }

    passthrough = RobotCommandRequest(
        robot_id=payload.robot_id,
        kind=payload.kind,
        command_id=payload.command_id,
        task_id=payload.task_id,
        dry_run=payload.dry_run,
        params={**dict(p), "map_id": movement_map_id},
        callback_url=payload.callback_url,
    )

    result = _dispatch_passthrough(passthrough, command_id, callback_url)
    operational_events.append(
        conn,
        event_type="MOVEMENT_COMMAND_MAP_CONTEXT",
        robot_id=payload.robot_id,
        command_id=result.command_id,
        message=f"ui_map={lms_map_id} runtime_map={movement_map_id}",
        payload=map_context,
    )
    return result


def _dispatch_manual_drive(payload: RobotCommandRequest, command_id: str) -> RobotCommandResponse:
    if payload.dry_run:
        return RobotCommandResponse(
            command_id=command_id,
            robot_id=payload.robot_id,
            kind="manual_drive",
            dry_run=True,
            accepted=True,
            response={"validated": True, "message": "manual_drive ignores dry_run execution"},
        )
    p = payload.params
    result = execute_teleop(
        TeleopRequest(
            robot_id=payload.robot_id,
            command=str(p.get("command", "stop")),
            hold=bool(p.get("hold", False)),
            source="robot_commands",
        )
    )
    return RobotCommandResponse(
        command_id=result.command_id or command_id,
        robot_id=payload.robot_id,
        kind="manual_drive",
        dry_run=False,
        accepted=result.accepted,
        response=result.model_dump(),
    )


def _dispatch_estop(payload: RobotCommandRequest, command_id: str) -> RobotCommandResponse:
    op = str(payload.params.get("op", "stop"))
    try:
        response = (
            movement_client.clear_estop(payload.robot_id) if op == "clear" else movement_client.estop(payload.robot_id)
        )
    except MovementClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return RobotCommandResponse(
        command_id=command_id,
        robot_id=payload.robot_id,
        kind="estop",
        dry_run=False,
        accepted=True,
        response=response,
    )


def _normalize_aruco_tolerance(raw: Any) -> dict[str, float]:
    """Movement handoff: {xy_m, yaw_deg} 객체. 스칼라는 하위호환 {xy_m: 값}."""
    if isinstance(raw, dict):
        out: dict[str, float] = {}
        if "xy_m" in raw:
            out["xy_m"] = float(raw["xy_m"])
        elif "xy" in raw:
            out["xy_m"] = float(raw["xy"])
        if "yaw_deg" in raw:
            out["yaw_deg"] = float(raw["yaw_deg"])
        elif "yaw" in raw:
            out["yaw_deg"] = float(raw["yaw"])
        if out:
            return out
    if raw is not None:
        try:
            return {"xy_m": float(raw)}
        except (TypeError, ValueError):
            pass
    return {"xy_m": 0.05}


DOCK_TRANSFER_OPTIONAL_KEYS = ("lift_height_mm", "lift_timeout_sec", "home_on_unload")


def normalize_dock_transfer_params(
    raw: dict[str, Any],
    *,
    status_code: int = 400,
    detail_prefix: str = "dock_transfer.params",
) -> dict[str, Any]:
    """dock_transfer params 정규화 — 필수 3필드 + 선택 lift override 화이트리스트."""
    for key in ("aruco_marker_id", "action"):
        if key not in raw:
            raise HTTPException(status_code=status_code, detail=f"{detail_prefix}.{key} required")
    action = str(raw["action"])
    if action not in ("load", "unload"):
        raise HTTPException(status_code=status_code, detail=f"{detail_prefix}.action must be load or unload")
    try:
        aruco_marker_id = int(raw["aruco_marker_id"])
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status_code, detail=f"{detail_prefix}.aruco_marker_id must be an integer"
        ) from exc
    try:
        level = int(raw.get("level", 1))
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=status_code, detail=f"{detail_prefix}.level must be an integer") from exc
    if level not in (1, 2):
        raise HTTPException(status_code=status_code, detail=f"{detail_prefix}.level must be 1 or 2")

    out: dict[str, Any] = {
        "aruco_marker_id": aruco_marker_id,
        "action": action,
        "level": level,
    }
    for key in DOCK_TRANSFER_OPTIONAL_KEYS:
        if key not in raw:
            continue
        val = raw[key]
        if key == "home_on_unload":
            if not isinstance(val, bool):
                raise HTTPException(status_code=status_code, detail=f"{detail_prefix}.home_on_unload must be a boolean")
            out[key] = val
        else:
            try:
                out[key] = float(val)
            except (TypeError, ValueError) as exc:
                raise HTTPException(status_code=status_code, detail=f"{detail_prefix}.{key} must be a number") from exc
    return out


def _map_movement_client_error(exc: MovementClientError, *, kind: str) -> HTTPException:
    """Movement HTTP 오류를 Main 응답으로 매핑한다(409 게이트·404 미구현 구분)."""
    detail = str(exc)
    code = exc.status_code
    if code == 409:
        return HTTPException(status_code=409, detail=detail)
    if kind in {"dock_transfer", "aruco_align"} and (code == 404 or "404" in detail or "Not Found" in detail):
        return HTTPException(
            status_code=501,
            detail=(
                "movement_robot_commands_api_missing: "
                f"{kind} execution requires Movement POST /robot-commands, "
                "but the Movement server returned 404. Use dry_run only until Movement implements the envelope endpoint."
            ),
        )
    return HTTPException(status_code=502, detail=detail)


def _dispatch_dock_transfer(payload: RobotCommandRequest, command_id: str, callback_url: str) -> RobotCommandResponse:
    payload.params = normalize_dock_transfer_params(payload.params)
    if payload.dry_run:
        return RobotCommandResponse(
            command_id=command_id,
            robot_id=payload.robot_id,
            kind="dock_transfer",
            dry_run=True,
            accepted=True,
            response={"validated": True, "message": "dry_run ok", "params": payload.params},
        )
    return _dispatch_passthrough(payload, command_id, callback_url)


def _dispatch_aruco_align(payload: RobotCommandRequest, command_id: str, callback_url: str) -> RobotCommandResponse:
    p = payload.params
    if "aruco_marker_id" not in p:
        raise HTTPException(status_code=400, detail="aruco_align.params.aruco_marker_id required")
    try:
        aruco_marker_id = int(p["aruco_marker_id"])
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="aruco_align.params.aruco_marker_id must be an integer") from exc
    payload.params = {
        "aruco_marker_id": aruco_marker_id,
        "final": str(p.get("final", "park")),
        "tolerance": _normalize_aruco_tolerance(p.get("tolerance", 0.05)),
    }
    if payload.dry_run:
        return RobotCommandResponse(
            command_id=command_id,
            robot_id=payload.robot_id,
            kind="aruco_align",
            dry_run=True,
            accepted=True,
            response={"validated": True, "message": "dry_run ok", "params": payload.params},
        )
    return _dispatch_passthrough(payload, command_id, callback_url)


def _dispatch_leave_dock(payload: RobotCommandRequest, command_id: str, callback_url: str) -> RobotCommandResponse:
    """출차(후진) — 정면 주차/대기에서 후진 탈출. params는 모두 선택(Movement 기본값 사용)."""
    if payload.dry_run:
        return RobotCommandResponse(
            command_id=command_id,
            robot_id=payload.robot_id,
            kind="leave_dock",
            dry_run=True,
            accepted=True,
            response={"validated": True, "message": "dry_run ok", "params": dict(payload.params)},
        )
    return _dispatch_passthrough(payload, command_id, callback_url)


def _dispatch_passthrough(payload: RobotCommandRequest, command_id: str, callback_url: str) -> RobotCommandResponse:
    """— 네이티브 POST /robot-commands envelope 패스스루."""
    bridge_key = movement_robot_key(payload.robot_id)
    envelope: dict[str, Any] = {
        "robot_id": bridge_key,
        "robot_name": bridge_key,
        "kind": payload.kind,
        "command_id": command_id,
        "dry_run": payload.dry_run,
        "params": payload.params,
        "task_id": payload.task_id,
    }
    if callback_url:
        envelope["callback_url"] = callback_url
    try:
        response = movement_client.robot_command(payload.robot_id, envelope)
    except NotImplementedError as exc:
        raise HTTPException(
            status_code=501,
            detail=f"{payload.kind} execution pending — movement server robot-commands passthrough",
        ) from exc
    except MovementClientError as exc:
        raise _map_movement_client_error(exc, kind=payload.kind) from exc
    return RobotCommandResponse(
        command_id=str(response.get("command_id") or command_id),
        robot_id=payload.robot_id,
        kind=payload.kind,
        dry_run=payload.dry_run,
        accepted=bool(response.get("accepted", True)),
        response=response,
    )


def get_command_status(robot_id: str, command_id: str) -> RobotCommandResponse:
    response = missions.command_status(robot_id, command_id)
    state = str(response.get("state") or response.get("status") or "")
    kind = str(response.get("kind") or response.get("command_kind") or "move_to_point")
    return RobotCommandResponse(
        command_id=command_id,
        robot_id=robot_id,
        kind=kind,
        dry_run=bool(response.get("dry_run")),
        accepted=state.upper() not in {"FAILED", "REJECTED"},
        response=response,
    )
