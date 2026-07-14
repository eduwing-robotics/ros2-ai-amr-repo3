"""Movement diagnostics, callbacks, and command trace routes."""

from __future__ import annotations

import secrets
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request

from app.core.api_logs import list_logs as list_api_logs
from app.core.config import settings
from app.core.health_cache import clear_cache
from app.db.connection import transaction
from app.db.mvp import event_repo, movement_repo, robot_repo
from app.domains.execution import orchestrator as orchestrator_service
from app.domains.movement import missions as mission_service
from app.domains.movement.client import MovementClientError, movement_client, set_robot_emergency
from app.domains.movement.commands import dispatch_robot_command, get_command_status
from app.domains.movement.health import base_url_for, get_movement_health
from app.domains.movement.navigation import (
    get_runtime_map_context,
    localization_snapshot,
    movement_map_state,
    movement_reason,
    pose_in_bounds,
    report_pose_for_robot,
    resolve_movement_map_id,
    runtime_map_context_route,
)
from app.domains.movement.teleop import execute_teleop
from app.models.schemas import (
    ApiMessage,
    InitialPoseRequest,
    MovementCallbackAck,
    MovementRobotStatusCallback,
    RobotCommandEvent,
    RobotCommandRequest,
    RobotCommandResponse,
    RobotCommandResult,
    RobotPose,
    RobotPoseReport,
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
        if not robot_repo(conn).exists(robot_id):
            raise HTTPException(status_code=404, detail="robot not found")
    return localization_snapshot(robot_id)


@router.get("/robots/{robot_id}/nav-state")
def robot_nav_state(robot_id: str) -> dict:
    """Movement nav-state API를 우선 사용하고, 없으면 health 기반으로 보정한다."""
    with transaction() as conn:
        if not robot_repo(conn).exists(robot_id):
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
    """— Nav2 runtime map context (수동 명령·pose overlay 기준)."""
    return runtime_map_context_route()


@router.get("/movement/sync-status")
def movement_sync_status() -> dict:
    """로봇별 Movement 동기화/진단 상태를 한 번에 반환한다."""
    with transaction() as conn:
        robots = [r["robot_id"] for r in robot_repo(conn).list()]
        events = event_repo(conn).list(limit=120)
    logs = list_api_logs(service="movement", limit=120)
    map_state = movement_map_state()
    rows = []
    for robot_id in robots:
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
        if not robot_repo(conn).exists(robot_id):
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
        if not robot_repo(conn).exists(robot_id):
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
        event_repo(conn).append(
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
        commands = movement_repo(conn).list(limit=200)
        events = event_repo(conn).list(limit=200)
    command = next((c for c in commands if c.get("command_id") == command_id), None)
    resolved_robot_id = robot_id or (command or {}).get("robot_id")
    callbacks = [e for e in events if e.get("command_id") == command_id]
    polling: dict | None = None
    polling_error: str | None = None
    if resolved_robot_id:
        try:
            polling = mission_service.command_status(resolved_robot_id, command_id)
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
        return MovementCallbackAck(**ingest_command_event(conn, payload.to_payload()))


@router.post("/movement/results", response_model=MovementCallbackAck)
def movement_result(payload: RobotCommandResult, request: Request) -> MovementCallbackAck:
    """Legacy result callback을 기록하고 command lifecycle에 반영한다."""
    require_callback_token(request)
    with transaction() as conn:
        return MovementCallbackAck(**ingest_result(conn, payload.to_payload()))


@router.post("/movement/robots/{robot_name}/status", response_model=ApiMessage)
def movement_robot_status(robot_name: str, payload: MovementRobotStatusCallback, request: Request) -> ApiMessage:
    """Movement robot status callback을 current robot/pose에 반영한다."""
    require_callback_token(request)
    with transaction() as conn:
        ingest_robot_status(conn, robot_name, payload.to_payload())
    return ApiMessage(message="movement robot status saved")


@router.post("/robot/estop")
def robot_estop_all() -> dict:
    """등록된 모든 로봇에 비상 정지를 요청한다."""
    with transaction() as conn:
        results = estop_all_robots(conn)
    return {"ok": all(r.get("ok") for r in results), "robots": results}


@router.post("/robot/clear_estop")
def robot_clear_estop_all() -> dict:
    """등록된 모든 로봇의 비상 정지를 해제한다."""
    with transaction() as conn:
        results = clear_estop_all_robots(conn)
    return {"ok": all(r.get("ok") for r in results), "robots": results}


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
def list_robot_poses(map_id: str | None = None) -> list[RobotPose]:
    """로봇별 최신 map pose — Movement live state + robots 목록.

    DBML에 pose current-state 컬럼이 없으므로 DB pose 테이블을 사용하지 않는다.
    """
    with transaction() as conn:
        robot_ids = [r["robot_id"] for r in robot_repo(conn).list()]

    rows: dict[str, dict] = {}
    map_state = movement_map_state()
    active_map_id = map_state.get("active_map_id")
    ctx = get_runtime_map_context()

    for robot_id in robot_ids:
        try:
            live = movement_client.robot_pose(robot_id)
        except MovementClientError:
            continue
        pose = live.get("pose") or {}
        if not live.get("localized") or not pose:
            continue
        display_map_id = map_id or active_map_id or pose.get("frame_id") or "map"
        px = float(pose["x"])
        py = float(pose["y"])
        rows[robot_id] = {
            "robot_id": robot_id,
            "map_id": display_map_id,
            "x": px,
            "y": py,
            "yaw": pose.get("yaw", 0.0),
            "linear_velocity": None,
            "angular_velocity": None,
            "source": pose.get("source") or "movement_pose",
            "frame_id": pose.get("frame_id"),
            "child_frame_id": pose.get("child_frame_id"),
            "age_sec": pose.get("age_sec"),
            "covariance": pose.get("covariance"),
            "reported_at": pose.get("reported_at") or live.get("reported_at"),
            "received_at": pose.get("reported_at") or live.get("reported_at"),
            "in_bounds": pose_in_bounds(px, py, ctx),
        }
    return [RobotPose(**p) for p in sorted(rows.values(), key=lambda item: item["robot_id"])]


@router.post("/robot-poses/report", response_model=ApiMessage)
def report_robot_pose(payload: RobotPoseReport) -> ApiMessage:
    """Movement/Nav 서버 또는 테스트 도구가 최신 pose를 보고한다 (last_seen 갱신만)."""
    with transaction() as conn:
        report_pose_for_robot(conn, payload.robot_id, RobotPoseUpdate(**payload.model_dump(exclude={"robot_id"})))
    return ApiMessage(message="robot pose accepted")


@router.post("/robots/{robot_id}/pose", response_model=ApiMessage)
def report_robot_pose_for_robot(robot_id: str, payload: RobotPoseUpdate) -> ApiMessage:
    """ROS pose bridge가 robot_id별 최신 map pose를 보고한다."""
    with transaction() as conn:
        report_pose_for_robot(conn, robot_id, payload)
    return ApiMessage(message="robot pose accepted")


@router.post("/movement/missions/{command_id}/pose", response_model=ApiMessage)
def report_mission_pose(command_id: str, payload: RobotPoseReport) -> ApiMessage:
    """Movement mission pose callback."""
    update = RobotPoseUpdate(**payload.model_dump(exclude={"robot_id"}))
    with transaction() as conn:
        report_pose_for_robot(conn, payload.robot_id, update, source=payload.source or "movement_mission")
        event_repo(conn).append(
            event_type="MOVEMENT_POSE",
            robot_id=payload.robot_id,
            command_id=command_id,
            message=f"pose received for {payload.robot_id}",
            payload={"command_id": command_id, **payload.model_dump()},
        )
    return ApiMessage(message="mission pose accepted")


@router.post("/teleop", response_model=TeleopResponse)
def teleop(payload: TeleopRequest) -> TeleopResponse:
    """수동조작 요청을 서비스 계층으로 위임한다."""
    return execute_teleop(payload)


RESULT_EVENT_MAP = {
    "OK": "DONE",
    "SUCCESS": "DONE",
    "SUCCEEDED": "DONE",
    "COMPLETED": "DONE",
    "CANCELED": "CANCELED",
    "CANCELLED": "CANCELLED",
    "STOPPED": "STOPPED",
    "ABORTED": "ABORTED",
    "FAILED": "FAILED",
    "REJECTED": "REJECTED",
}


def _is_duplicate_callback(repo, payload: dict[str, Any]) -> bool:
    event_id = str(payload.get("event_id") or "")
    return bool(event_id and repo.callback_event_exists(event_id))


def _event_payload(payload: dict[str, Any]) -> dict[str, Any]:
    out = dict(payload)
    if payload.get("event_id"):
        out["callback_event_id"] = payload["event_id"]
    return out


def ingest_command_event(conn, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist Movement command callback and advance orchestration when applicable."""
    repo = event_repo(conn)
    if _is_duplicate_callback(repo, payload):
        return {"message": "duplicate movement callback ignored", "duplicate": True, "task_advanced": False}
    command_id = payload.get("command_id")
    robot_id = payload.get("robot_name") or payload.get("robot_id")
    event = payload.get("event") or payload.get("state") or "UNKNOWN"
    repo.append(
        event_type=f"MOVEMENT_COMMAND_{event}",
        robot_id=robot_id,
        command_id=command_id,
        message=payload.get("message") or str(event),
        payload=_event_payload(payload),
    )
    advanced = orchestrator_service.handle_command_event(conn, payload) is not None
    return {"message": "movement command event saved", "duplicate": False, "task_advanced": advanced}


def ingest_result(conn, payload: dict[str, Any]) -> dict[str, Any]:
    """Persist Movement result callback and update movement command record."""
    repo = event_repo(conn)
    if _is_duplicate_callback(repo, payload):
        return {"message": "duplicate movement result ignored", "duplicate": True, "task_advanced": False}
    command_id = payload.get("command_id")
    robot_id = payload.get("robot_name") or payload.get("robot_id")
    result = str(payload.get("result") or "UNKNOWN").upper()
    repo.append(
        event_type=f"MOVEMENT_RESULT_{result}",
        robot_id=robot_id,
        command_id=command_id,
        message=payload.get("message") or str(result),
        payload=_event_payload(payload),
    )
    if not command_id:
        return {"message": "movement result saved without command", "duplicate": False, "task_advanced": False}
    movement_repo(conn).record_result(
        command_id,
        str(result),
        payload.get("message") or str(result),
        payload,
    )
    normalized = {**payload, "event": RESULT_EVENT_MAP.get(result, result)}
    advanced = orchestrator_service.handle_command_event(conn, normalized) is not None
    return {"message": "movement result saved", "duplicate": False, "task_advanced": advanced}


def ingest_robot_status(conn, robot_name: str, payload: dict[str, Any]) -> None:
    """Apply Movement robot status callback to pose and event timeline."""
    pose = payload.get("pose") or {}
    if pose and payload.get("localized", True):
        update = RobotPoseUpdate(
            map_id=pose.get("frame_id") or "map",
            x=pose["x"],
            y=pose["y"],
            yaw=pose.get("yaw", 0.0),
            source=pose.get("source") or "movement_status",
            reported_at=pose.get("reported_at") or payload.get("reported_at"),
        )
        report_pose_for_robot(conn, robot_name, update, source=update.source)
    event_repo(conn).append(
        event_type="MOVEMENT_ROBOT_STATUS",
        robot_id=robot_name,
        command_id=payload.get("current_command_id"),
        message=payload.get("state") or "status",
        payload=payload,
    )


def estop_all_robots(conn) -> list[dict[str, Any]]:
    """Request estop for every registered robot and record outcomes."""
    from app.domains.safety.hazard import mark_running_tasks_awaiting_operator

    mark_running_tasks_awaiting_operator(conn, reason="operator_estop")
    robot_ids = [r["robot_id"] for r in robot_repo(conn).list()]
    results: list[dict[str, Any]] = []
    for robot_id in robot_ids:
        set_robot_emergency(robot_id, True)
        try:
            payload = movement_client.estop(robot_id)
            results.append({"robot_id": robot_id, "ok": True, "response": payload})
            event_repo(conn).append(
                event_type="ROBOT_ESTOP",
                robot_id=robot_id,
                message=f"estop: {robot_id}",
                payload=payload,
            )
        except MovementClientError as exc:
            results.append({"robot_id": robot_id, "ok": False, "error": str(exc)})
    clear_cache()
    return results


def clear_estop_all_robots(conn) -> list[dict[str, Any]]:
    """Clear estop for every registered robot and record outcomes."""
    robot_ids = [r["robot_id"] for r in robot_repo(conn).list()]
    results: list[dict[str, Any]] = []
    for robot_id in robot_ids:
        try:
            payload = movement_client.clear_estop(robot_id)
            set_robot_emergency(robot_id, False)
            results.append({"robot_id": robot_id, "ok": True, "response": payload})
            event_repo(conn).append(
                event_type="ROBOT_CLEAR_ESTOP",
                robot_id=robot_id,
                message=f"clear estop: {robot_id}",
                payload=payload,
            )
        except MovementClientError as exc:
            results.append({"robot_id": robot_id, "ok": False, "error": str(exc)})
    clear_cache()
    return results
