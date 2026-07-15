"""Movement diagnostics, callbacks, and command trace routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.movement_helpers import (
    localization_snapshot,
    movement_map_state,
    movement_reason,
    resolve_movement_map_id,
    runtime_map_context_route,
)
from app.core.config import settings
from app.db.connection import transaction
from app.db.repo_bridge import event_repo, movement_repo, robot_repo
from app.models.schemas import ApiMessage, InitialPoseRequest
from app.security import ReplayCache, verify_headers
from app.services import missions as mission_service
from app.services import movement_callbacks as callbacks
from app.services.api_logs import list_logs as list_api_logs
from app.services.movement import MovementClientError, movement_client
from app.services.movement_health import base_url_for, get_movement_health

router = APIRouter(tags=["movement"])
_callback_replay_cache = ReplayCache()


async def require_nav_callback_signature(request: Request) -> None:
    body = await request.body()
    ok, status, detail = verify_headers(
        settings.movement_hmac_secret,
        request.method,
        request.url.path + (f"?{request.url.query}" if request.url.query else ""),
        body,
        request.headers,
        skew_sec=settings.movement_hmac_clock_skew_sec,
        replay_cache=_callback_replay_cache,
    )
    if not ok:
        raise HTTPException(status_code=status, detail=detail)


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
    """PHASE_21 — Nav2 runtime map context (수동 명령·pose overlay 기준)."""
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
        robot_events = [e for e in events if e.get("robot_id") == robot_id and str(e.get("event_type", "")).startswith("MOVEMENT_")]
        robot_logs = [log for log in logs if log.get("source") == robot_id]
        last_callback = robot_events[0].get("created_at") if robot_events else None
        last_poll = robot_logs[0].get("finished_at") if robot_logs else None
        rows.append({
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
        })
    return {"robots": rows, "map_state": map_state, "movement_logs": logs[:20], "planned_paths": _planned_paths_for_sync(conn, map_state)}


def _planned_paths_for_sync(conn, map_state: dict) -> list[dict]:
    """fake 모드 시연용 Nav2 예상 경로. Movement 서버 연동 전 dry-run 데모."""
    if settings.movement_client_mode.strip().lower() != "fake":
        return []
    active_map = map_state.get("active_map_id") or settings.movement_active_map_id
    paths: list[dict] = []
    for row in robot_repo(conn).list():
        x0, y0 = row.get("pose_x"), row.get("pose_y")
        if x0 is None or y0 is None:
            continue
        map_id = row.get("pose_map_id") or active_map
        paths.append({
            "robot_id": row["robot_id"],
            "map_id": map_id,
            "label": "Nav2",
            "points": [
                {"x": float(x0), "y": float(y0)},
                {"x": float(x0) + 1.2, "y": float(y0)},
                {"x": float(x0) + 1.2, "y": float(y0) + 0.8},
                {"x": float(x0) + 2.0, "y": float(y0) + 0.8},
            ],
        })
    return paths


@router.get("/aruco/latest")
def aruco_latest(
    robot_id: str = Query(..., min_length=1),
    marker_id: int = Query(..., ge=0),
) -> dict:
    """이동서버 ArUco 검출 readout 프록시 — 수동 정렬 테스트(PHASE_19)."""
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
    """Publish an initial pose only into the exact, content-verified active map."""
    with transaction() as conn:
        if not robot_repo(conn).exists(robot_id):
            raise HTTPException(status_code=404, detail="robot not found")
    runtime_map_id, map_state = resolve_movement_map_id(payload.map_id, robot_id=robot_id)
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
        raise HTTPException(status_code=status, detail={"error": error, "message": detail, "robot_id": robot_id}) from exc
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


@router.post("/movement/command-events", response_model=ApiMessage, dependencies=[Depends(require_nav_callback_signature)])
def movement_command_event(payload: dict) -> ApiMessage:
    """Movement callback_url 이벤트를 수신해 이벤트 타임라인에 기록한다."""
    with transaction() as conn:
        callbacks.ingest_command_event(conn, payload)
    return ApiMessage(message="movement command event saved")


@router.post("/movement/results", response_model=ApiMessage, dependencies=[Depends(require_nav_callback_signature)])
def movement_result(payload: dict) -> ApiMessage:
    """Movement result callback을 수신해 이벤트 타임라인에 기록한다."""
    with transaction() as conn:
        callbacks.ingest_result(conn, payload)
    return ApiMessage(message="movement result saved")


@router.post("/movement/robots/{robot_name}/status", response_model=ApiMessage, dependencies=[Depends(require_nav_callback_signature)])
def movement_robot_status(robot_name: str, payload: dict) -> ApiMessage:
    """Accept health status and persist only issues; pose uses the canonical route."""
    if callbacks.robot_status_requires_event(payload):
        with transaction() as conn:
            callbacks.ingest_robot_status(conn, robot_name, {**payload, "pose": None})
        return ApiMessage(message="movement robot status issue saved")
    return ApiMessage(message="movement robot status accepted")


@router.post("/robots/estop-all")
@router.post("/robot/estop")
def robot_estop_all() -> dict:
    """등록된 모든 로봇에 비상 정지를 요청한다."""
    with transaction() as conn:
        results = callbacks.estop_all_robots(conn)
    return {"ok": all(r.get("ok") for r in results), "robots": results}


@router.post("/robots/clear-estop-all")
@router.post("/robot/clear_estop")
def robot_clear_estop_all() -> dict:
    """등록된 모든 로봇의 비상 정지를 해제한다."""
    with transaction() as conn:
        results = callbacks.clear_estop_all_robots(conn)
    attempted = [row for row in results if row.get("attempted", True)]
    unknown = [row["robot_id"] for row in results if row.get("state") == "unknown"]
    active = [row["robot_id"] for row in results if row.get("state") == "active"]
    ok = bool(attempted) and not unknown and not active and all(row.get("ok") for row in attempted)
    state = "active" if active else "partial" if unknown else "clear" if ok else "unknown"
    return {
        "ok": ok,
        "state": state,
        "partial": bool(unknown or active),
        "unknown_robots": unknown,
        "active_robots": active,
        "robots": results,
    }
