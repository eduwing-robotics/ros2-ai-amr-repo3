"""Movement diagnostics, callbacks, and command trace routes."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.core.api_logs import list_logs as list_api_logs
from app.core.config import settings
from app.core.health_cache import clear_cache
from app.db.connection import transaction
from app.db.postgres import operational_events
from app.db.postgres import robots as postgres_robots
from app.domains.movement import callbacks, missions
from app.domains.movement.client import MovementClientError, movement_client, set_robot_emergency
from app.domains.movement.commands import dispatch_robot_command, get_command_status
from app.domains.movement.health import base_url_for, get_movement_health
from app.domains.movement.navigation import (
    localization_snapshot,
    movement_map_state,
    movement_reason,
    resolve_movement_map_id,
    runtime_map_context_route,
)
from app.domains.movement.pose_monitor import pose_runtime_metrics
from app.domains.movement.pose_runtime import UnknownRobotError, pose_runtime
from app.domains.movement.teleop import execute_teleop
from app.domains.records import movement_commands
from app.models.common import ApiMessage
from app.models.movement import (
    MovementCallbackAck,
    MovementRobotStatusCallback,
    RobotCommandEvent,
)
from app.models.robot_commands import RobotCommandRequest, RobotCommandResponse
from app.models.robots import (
    InitialPoseRequest,
    RobotPose,
    RobotPoseUpdate,
    TeleopRequest,
    TeleopResponse,
)

router = APIRouter(tags=["movement"])


def require_callback_token(request: Request) -> None:
    """Require the shared Movement callback token when configured."""
    expected = settings.movement_callback_token
    if not expected:
        return
    supplied = request.headers.get("X-Movement-Callback-Token", "")
    if not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid movement callback token")


@router.get("/robots/{robot_id}/localization")
def robot_localization(robot_id: str) -> dict:
    """로봇 localization/pose 미표시 원인을 구조화해 반환한다."""
    with transaction() as conn:
        if not postgres_robots.exists(conn, robot_id):
            raise HTTPException(status_code=404, detail="robot not found")
    return localization_snapshot(robot_id)


@router.get("/robots/{robot_id}/nav-state")
def robot_nav_state(robot_id: str) -> dict:
    """Movement nav-state API를 우선 사용하고, 없으면 health 기반으로 보정한다."""
    with transaction() as conn:
        if not postgres_robots.exists(conn, robot_id):
            raise HTTPException(status_code=404, detail="robot not found")
    health = get_movement_health([robot_id]).get(robot_id, {})
    try:
        payload = movement_client.nav_state(robot_id)
        movement_robot_id = payload.get("robot_id")
        payload = {**payload, "movement_robot_id": movement_robot_id}
        payload["robot_id"] = robot_id
        return {"ok": True, "base_url": base_url_for(robot_id), **payload}
    except MovementClientError as exc:
        reason, action = movement_reason(health)
        return {
            "ok": bool(health.get("ok")),
            "robot_id": robot_id,
            "robot_name": health.get("robot_name") or robot_id,
            "base_url": health.get("base_url") or base_url_for(robot_id),
            "robot_online": health.get("robot_online"),
            "command_accepting": health.get("command_accepting"),
            "nav2_ready": health.get("nav2_ready"),
            "navigator_status": health.get("navigator_status"),
            "is_emergency": health.get("is_emergency"),
            "current_command_id": health.get("current_command_id"),
            "localized": health.get("localized"),
            "reason": reason,
            "action_required": action,
            "source": "health_fallback",
            "fallback_error": str(exc),
            "health": health,
        }


@router.get("/movement/map-state")
def movement_map_state_route() -> dict:
    """Movement active map 상태를 반환한다. API가 없으면 Main 설정/DB 기준으로 보정한다."""
    return movement_map_state()


@router.get("/movement/runtime-map-context")
def movement_runtime_map_context_route() -> dict:
    """Nav2 runtime map context를 반환하고 pose 경계 검사에도 반영한다."""
    context = runtime_map_context_route()
    pose_runtime.update_map_context(context)
    return context


@router.get("/movement/sync-status")
def movement_sync_status() -> dict:
    """로봇별 Movement 동기화/진단 상태를 한 번에 반환한다."""
    with transaction() as conn:
        robot_ids = [
            r["robot_id"]
            for r in postgres_robots.list_robots(
                conn,
            )
        ]
        events = operational_events.list_operational_events(conn, limit=120)
    logs = list_api_logs(service="movement", limit=120)
    map_state = movement_map_state()
    pose_runtime.update_map_context(map_state)
    rows = []
    for robot_id in robot_ids:
        snapshot = localization_snapshot(robot_id)
        robot_events = [
            e for e in events if e.get("robot_id") == robot_id and str(e.get("event_type", "")).startswith("MOVEMENT_")
        ]
        robot_logs = [log for log in logs if log.get("source") == robot_id]
        last_callback = robot_events[0].get("created_at") if robot_events else None
        last_poll = robot_logs[0].get("finished_at") if robot_logs else None
        rows.append(
            {
                "robot_id": robot_id,
                "base_url": snapshot.get("base_url"),
                "api_ok": snapshot.get("ok"),
                "robot_online": snapshot.get("robot_online"),
                "command_accepting": snapshot.get("command_accepting"),
                "localized": snapshot.get("localized"),
                "pose_state": snapshot.get("pose_state"),
                "reason": snapshot.get("reason"),
                "action_required": snapshot.get("action_required"),
                "current_command_id": snapshot.get("health", {}).get("current_command_id"),
                "last_callback_at": last_callback,
                "last_poll_at": last_poll,
                "health_checked_at": snapshot.get("health", {}).get("checked_at"),
            }
        )
    return {"robots": rows, "map_state": map_state, "movement_logs": logs[:20]}


@router.get("/aruco/latest")
def aruco_latest(
    robot_id: str = Query(..., min_length=1),
    marker_id: int = Query(..., ge=0),
) -> dict:
    """이동서버 ArUco 검출 readout 프록시 — 수동 정렬 테스트."""
    with transaction() as conn:
        if not postgres_robots.exists(conn, robot_id):
            raise HTTPException(status_code=404, detail="robot not found")
    try:
        payload = movement_client.aruco_latest(robot_id, marker_id)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail="aruco/latest not available on movement client") from exc
    except MovementClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return payload


@router.post("/robots/{robot_id}/initial-pose")
def set_robot_initial_pose(robot_id: str, payload: InitialPoseRequest) -> dict:
    """웹에서 지정한 초기 pose를 Movement 서버로 전달한다. map_id는 runtime active map으로 해석한다."""
    with transaction() as conn:
        if not postgres_robots.exists(conn, robot_id):
            raise HTTPException(status_code=404, detail="robot not found")
    runtime_map_id, map_state = resolve_movement_map_id(payload.map_id)
    map_context = {
        "ui_map_id": payload.map_id,
        "runtime_map_id": runtime_map_id,
        "runtime_confidence": map_state.get("confidence"),
    }
    body = payload.model_dump(exclude={"map_id"})
    body["frame_id"] = str(map_state.get("frame_id") or payload.frame_id or "map")
    try:
        response = movement_client.initial_pose(robot_id, body)
    except MovementClientError as exc:
        detail = str(exc)
        status = 502
        error = "movement_initial_pose_failed"
        if "404" in detail or "405" in detail:
            error = "movement_initial_pose_api_missing"
        raise HTTPException(
            status_code=status, detail={"error": error, "message": detail, "robot_id": robot_id}
        ) from exc
    with transaction() as conn:
        operational_events.append(
            conn,
            event_type="MOVEMENT_INITIAL_POSE",
            robot_id=robot_id,
            message=f"initial pose ui_map={payload.map_id} runtime_map={runtime_map_id}",
            payload={"request": payload.model_dump(), "map_context": map_context, "response": response},
        )
    return {"ok": True, "robot_id": robot_id, "map_context": map_context, "response": response}


@router.get("/movement/commands/{command_id}/trace")
def movement_command_trace(command_id: str, robot_id: str | None = Query(default=None)) -> dict:
    """command_id 기준 DB 기록, callback 이벤트, Movement polling 상태를 묶어 반환한다."""
    with transaction() as conn:
        commands = movement_commands.list_movement_command_records(conn, limit=200)
        events = operational_events.list_operational_events(conn, limit=200)
    command = next((c for c in commands if c.get("command_id") == command_id), None)
    resolved_robot_id = robot_id or (command or {}).get("robot_id")
    callbacks = [e for e in events if e.get("command_id") == command_id]
    polling: dict | None = None
    polling_error: str | None = None
    if resolved_robot_id:
        try:
            polling = missions.command_status(resolved_robot_id, command_id)
        except HTTPException as exc:
            polling_error = str(exc.detail)
    state = None
    if polling:
        state = polling.get("state") or polling.get("status")
    if state is None and callbacks:
        state = callbacks[0].get("event_type")
    if state is None and command:
        state = command.get("status")
    return {
        "command_id": command_id,
        "robot_id": resolved_robot_id,
        "state": state,
        "command": command,
        "callbacks": callbacks,
        "callback_count": len(callbacks),
        "last_callback_at": callbacks[0].get("created_at") if callbacks else None,
        "polling": polling,
        "polling_error": polling_error,
        "source": "polling" if polling else "callback" if callbacks else "db" if command else "none",
    }


@router.post("/movement/command-events", response_model=MovementCallbackAck)
def movement_command_event(payload: RobotCommandEvent, request: Request) -> MovementCallbackAck:
    """Movement callback_url 이벤트를 수신해 이벤트 타임라인에 기록한다."""
    require_callback_token(request)
    with transaction() as conn:
        return MovementCallbackAck(**callbacks.ingest_command_event(conn, payload.to_payload()))


@router.post("/movement/robots/{robot_name}/status", response_model=ApiMessage)
def movement_robot_status(robot_name: str, payload: MovementRobotStatusCallback, request: Request) -> ApiMessage:
    """Movement robot status callback을 current robot/pose에 반영한다."""
    require_callback_token(request)
    body = payload.to_payload()
    try:
        callbacks.ingest_robot_status_pose(robot_name, body)
    except UnknownRobotError as exc:
        raise HTTPException(status_code=404, detail="robot not registered") from exc
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=f"invalid pose: {exc}") from exc
    if "is_emergency" in body:
        with transaction() as conn:
            callbacks.ingest_estop_status(conn, robot_name, body)
    if callbacks.robot_status_requires_event(body):
        with transaction() as conn:
            callbacks.ingest_robot_status(conn, robot_name, body)
        return ApiMessage(message="movement robot status issue saved")
    return ApiMessage(message="movement robot status accepted")


@router.post("/robots/estop-all")
@router.post("/robot/estop")
def robot_estop_all() -> dict:
    """등록된 모든 로봇에 비상 정지를 요청한다."""
    with transaction() as conn:
        results = estop_all_robots(conn)
    return {"ok": all(r.get("ok") for r in results), "robots": results}


@router.post("/robots/clear-estop-all")
@router.post("/robot/clear_estop")
def robot_clear_estop_all() -> dict:
    """등록된 운용 로봇의 비상 정지를 해제하고 미확인 로봇을 분리한다."""
    with transaction() as conn:
        results = clear_estop_all_robots(conn)
    attempted = [r for r in results if r.get("attempted", True)]
    unknown = [r["robot_id"] for r in results if r.get("state") == "clear_unconfirmed"]
    failed = [r["robot_id"] for r in attempted if not r.get("ok")]
    ok = bool(attempted) and not failed
    state = "partial" if unknown else "failed" if failed else "clear" if ok else "unknown"
    return {"ok": ok, "state": state, "partial": bool(unknown), "unknown_robots": unknown, "robots": results}


@router.post("/robot-commands", response_model=RobotCommandResponse)
def post_robot_command(payload: RobotCommandRequest, request: Request) -> RobotCommandResponse:
    """단일 envelope로 이동·수동조작·estop·(dry_run) dock_transfer 를 전달한다."""
    with transaction() as conn:
        return dispatch_robot_command(conn, payload, request)


@router.get("/robot-commands/{command_id}", response_model=RobotCommandResponse)
def get_robot_command(command_id: str, robot_id: str = Query(...)) -> RobotCommandResponse:
    """Movement command 상태 조회(콜백 누락 폴백)."""
    return get_command_status(robot_id, command_id)


@router.get("/robot-poses", response_model=list[RobotPose])
def list_robot_poses() -> list[RobotPose]:
    """DB나 Movement 호출 없이 프로세스 메모리의 최신 pose를 반환한다."""
    return [RobotPose(**row) for row in pose_runtime.list_snapshots()]


@router.post("/robots/{robot_id}/pose", response_model=ApiMessage)
def report_robot_pose_for_robot(robot_id: str, payload: RobotPoseUpdate) -> ApiMessage:
    """ROS pose bridge의 canonical 실시간 pose 수신점."""
    try:
        accepted = pose_runtime.ingest(
            robot_id,
            payload.model_dump(),
            source_kind="canonical",
            localized=payload.localized,
        )
    except UnknownRobotError as exc:
        raise HTTPException(status_code=404, detail="robot not registered") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return ApiMessage(message="robot pose accepted" if accepted else "older robot pose ignored")


@router.get("/movement/pose-runtime")
def movement_pose_runtime() -> dict:
    """실시간 pose 런타임 및 issue writer 진단 지표."""
    return pose_runtime_metrics()


@router.post("/teleop", response_model=TeleopResponse)
def teleop(payload: TeleopRequest) -> TeleopResponse:
    """수동조작 요청을 서비스 계층으로 위임한다."""
    return execute_teleop(payload)


def estop_all_robots(conn) -> list[dict[str, Any]]:
    """Request estop for every registered robot and record outcomes."""
    from app.domains.safety.hazard import mark_running_tasks_awaiting_operator

    mark_running_tasks_awaiting_operator(conn, reason="operator_estop")
    robot_ids = [
        r["robot_id"]
        for r in postgres_robots.list_robots(
            conn,
        )
    ]
    results: list[dict[str, Any]] = []
    for robot_id in robot_ids:
        set_robot_emergency(robot_id, True)
        request_id = secrets.token_hex(12)
        operational_events.append(
            conn,
            event_type="ROBOT_ESTOP_REQUESTED",
            robot_id=robot_id,
            message=f"estop requested: {robot_id}",
            payload={"request_id": request_id},
        )
        try:
            payload = movement_client.estop(robot_id)
            results.append(
                {
                    "robot_id": robot_id,
                    "ok": True,
                    "state": "stop_confirmed",
                    "request_id": request_id,
                    "response": payload,
                }
            )
            operational_events.append(
                conn,
                event_type="ROBOT_ESTOP_CONFIRMED",
                robot_id=robot_id,
                message=f"estop: {robot_id}",
                payload={**payload, "request_id": request_id},
            )
        except MovementClientError as exc:
            results.append(
                {
                    "robot_id": robot_id,
                    "ok": False,
                    "state": "stop_unconfirmed",
                    "request_id": request_id,
                    "error": str(exc),
                }
            )
            operational_events.append(
                conn,
                event_type="ROBOT_ESTOP_UNCONFIRMED",
                robot_id=robot_id,
                message=f"estop unconfirmed: {robot_id}",
                payload={"request_id": request_id, "error": str(exc)},
            )
    clear_cache()
    return results


def clear_estop_all_robots(conn) -> list[dict[str, Any]]:
    """Attempt clear for every enabled robot; never skip solely on stale health."""
    robot_rows = postgres_robots.list_robots(conn)
    results: list[dict[str, Any]] = []
    for robot in robot_rows:
        robot_id = robot["robot_id"]
        if not robot.get("enabled", True):
            results.append({"robot_id": robot_id, "ok": True, "attempted": False, "state": "disabled"})
            continue
        request_id = secrets.token_hex(12)
        operational_events.append(
            conn,
            event_type="ROBOT_CLEAR_ESTOP_REQUESTED",
            robot_id=robot_id,
            message=f"clear estop requested: {robot_id}",
            payload={"request_id": request_id},
        )
        try:
            payload = movement_client.clear_estop(robot_id)
            set_robot_emergency(robot_id, False)
            results.append(
                {
                    "robot_id": robot_id,
                    "ok": True,
                    "attempted": True,
                    "state": "clear_confirmed",
                    "request_id": request_id,
                    "response": payload,
                }
            )
            operational_events.append(
                conn,
                event_type="ROBOT_CLEAR_ESTOP_CONFIRMED",
                robot_id=robot_id,
                message=f"clear estop: {robot_id}",
                payload={**payload, "request_id": request_id},
            )
        except MovementClientError as exc:
            results.append(
                {
                    "robot_id": robot_id,
                    "ok": False,
                    "attempted": True,
                    "state": "clear_unconfirmed",
                    "request_id": request_id,
                    "error": str(exc),
                }
            )
            operational_events.append(
                conn,
                event_type="ROBOT_CLEAR_ESTOP_UNCONFIRMED",
                robot_id=robot_id,
                message=f"clear estop unconfirmed: {robot_id}",
                payload={"request_id": request_id, "error": str(exc)},
            )
    clear_cache()
    return results
