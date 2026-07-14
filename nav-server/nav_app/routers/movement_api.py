"""Movement API HTTP routes."""
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from route_builder import RouteBuildError, build_movement_steps, list_inventory
from traffic_manager import TrafficLockConflict

from nav_app.config import (
    current_ros_domain_id,
)
from nav_app.models import (
    GlobalLocalizationRequest,
    InitialPoseRequest,
    ManualRotateRequest,
    ManualStartRequest,
    ManualStopRequest,
    ManualTranslateRequest,
    MovementCommandRequest,
    MovementRouteRequest,
    MovementStep,
)
from nav_app.runtime import runtime
from nav_app.settings import (
    ACTIVE_ROBOT_ID,
    ARUCO_DETECTION_MAX_AGE_SEC,
    GATE_TIMEOUT_SEC,
    is_simulation_mode,
)
from nav_app.util.time import utc_now as _utc_now
from nav_app.services import capabilities
from nav_app.services import command_state
from nav_app.services import manual_control
from nav_app.services import map_state
from nav_app.services import movement_executor
from nav_app.services.safety import engage_estop
from nav_app.services import robot_commands
from nav_app.services import robot_context
from nav_app.services.lift_backends import synthetic_hil_admitted
from nav_app.services.route_helpers import (
    raw_route_preview,
    raw_steps_from_route_request,
    traffic_segments_from_steps,
)
from nav_app.security import require_main_signature

router = APIRouter()


@router.get("/movement-api/v1/aruco/latest")
def movement_latest_aruco(marker_id: Optional[int] = None):
    """Return the latest ArUco detections received from aruco_detector_node.py."""
    if not runtime.navigator:
        raise HTTPException(status_code=503, detail="시스템 초기화 중입니다.")
    if marker_id is None:
        detections = runtime.navigator.get_latest_aruco_detection(max_age_sec=ARUCO_DETECTION_MAX_AGE_SEC)
    else:
        detection = runtime.navigator.get_latest_aruco_detection(marker_id, max_age_sec=ARUCO_DETECTION_MAX_AGE_SEC)
        detections = [detection] if detection else []
    return {
        "robot_name": robot_context.active_bridge_robot_id(),
        "topic": robot_context.aruco_detection_topic(),
        "marker_id": marker_id,
        "detections": detections,
        "max_age_sec": ARUCO_DETECTION_MAX_AGE_SEC,
        "reported_at": _utc_now(),
    }


@router.get("/movement-api/v1/robots")
def movement_list_robots():
    """Main Server 스펙의 로봇 상태 목록 endpoint입니다."""
    return {"robots": [robot_context.movement_robot_summary()]}


@router.post("/movement-api/v1/commands", dependencies=[Depends(require_main_signature)])
def movement_accept_command(req: MovementCommandRequest, background_tasks: BackgroundTasks):
    return _movement_accept_command(req, background_tasks)


def _ensure_synthetic_hil_live_admission(
    *,
    request_dry_run: bool = False,
    steps: list[MovementStep] | None = None,
) -> None:
    if not synthetic_hil_admitted():
        return
    bypasses = []
    if request_dry_run or (steps and any(bool(step.payload.get("dry_run")) for step in steps)):
        bypasses.append("request_dry_run")
    if is_simulation_mode():
        bypasses.append("process_simulation")
    if runtime.mission_manager and runtime.mission_manager.dry_run:
        bypasses.append("mission_dry_run")
    if bypasses:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "synthetic_hil_simulation_forbidden",
                "message": "synthetic HIL virtualizes only lift; navigation and docking must remain live",
                "bypasses": bypasses,
            },
        )


def _movement_accept_command(
    req: MovementCommandRequest,
    background_tasks: BackgroundTasks,
    *,
    allow_runtime_test_dock_transfer: bool = False,
    request_dry_run: bool = False,
):
    """Main Server 스펙의 전체 steps command dispatch endpoint입니다."""
    if not runtime.navigator or not runtime.mission_manager:
        raise HTTPException(status_code=503, detail="시스템 초기화 중입니다.")
    if req.robot_name != robot_context.active_bridge_robot_id():
        raise HTTPException(
            status_code=409,
            detail=(
                f"이 Movement API 프로세스는 {robot_context.active_bridge_robot_id()}만 담당합니다. "
                f"{req.robot_name} 명령은 해당 robot_name 프로세스로 보내야 합니다."
            ),
        )
    if not req.steps:
        raise HTTPException(status_code=400, detail="steps는 비어 있을 수 없습니다.")
    request_is_dry_run = all(bool(step.payload.get("dry_run")) for step in req.steps)
    _ensure_synthetic_hil_live_admission(request_dry_run=request_dry_run, steps=req.steps)
    capabilities.ensure_steps_supported(
        req.steps,
        allow_runtime_test_dock_transfer=allow_runtime_test_dock_transfer,
    )
    explicit_bypass = bool(is_simulation_mode() or request_is_dry_run or runtime.mission_manager.dry_run)
    localization = robot_context.localization_health()
    if not explicit_bypass and not localization["localized"]:
        raise HTTPException(status_code=409, detail={"message": "movement requires localized AMCL/scan/TF state", "localization": localization})
    if not explicit_bypass and not runtime.navigator.ensure_nav2_ready():
        raise HTTPException(status_code=503, detail={"message": "Nav2 lifecycle/action is not ready", "nav2_ready": False})
    if not is_simulation_mode() and not request_is_dry_run and not runtime.mission_manager.dry_run and not robot_context.active_robot_online():
        raise HTTPException(
            status_code=503,
            detail={
                "message": "실제 로봇 bringup이 감지되지 않습니다. /cmd_vel subscriber를 확인하세요.",
                "cmd_vel_topic": "/cmd_vel",
                "cmd_vel_subscribers": robot_context.cmd_vel_subscriber_count(),
                "cmd_vel_subscriber_nodes": robot_context.cmd_vel_subscribers(),
            },
        )

    existing = runtime.movement_commands.get(req.command_id)
    if existing:
        return {
            "accepted": True,
            "command_id": req.command_id,
            "state": existing["state"],
            "duplicate": True,
        }

    active_command = next(
        (command for command in runtime.movement_commands.values()
         if command.get("robot_name") == req.robot_name and command.get("state") in ("ACCEPTED", "RUNNING")),
        None,
    )
    if active_command:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "robot already has an active movement command",
                "active_command_id": active_command.get("command_id"),
                "active_state": active_command.get("state"),
            },
        )

    traffic_segments = traffic_segments_from_steps(req.steps)
    traffic_locks = []
    if traffic_segments:
        if not runtime.traffic_manager:
            raise HTTPException(status_code=503, detail="Traffic manager 초기화 중입니다.")
        try:
            traffic_locks = runtime.traffic_manager.acquire_many(
                traffic_segments,
                robot_id=req.robot_name,
                command_id=req.command_id,
                route_type=req.steps[0].payload.get("route_type") if req.steps else None,
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=f"등록되지 않은 traffic segment입니다: {exc.args[0]}")
        except TrafficLockConflict as exc:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": "traffic segment locked",
                    "traffic_state": "WAITING_TRAFFIC",
                    "segment_id": exc.segment_id,
                    "current_lock": exc.current_lock,
                    "requested_segments": traffic_segments,
                },
            )

    runtime.movement_commands[req.command_id] = {
        "command_id": req.command_id,
        "task_id": req.task_id,
        "robot_name": req.robot_name,
        "state": "ACCEPTED",
        "current_step_index": None,
        "current_step_action": None,
        "message": "accepted",
        "traffic_segments": traffic_segments,
        "traffic_locks": traffic_locks,
        "traffic_state": "LOCKED" if traffic_segments else None,
        "callback_url": req.callback_url,
        "step_actions": [step.action for step in req.steps],
        "gate_timeout_sec": next((step.payload.get("gate_timeout_sec") for step in req.steps if step.payload.get("gate_timeout_sec") is not None), GATE_TIMEOUT_SEC),
        "simulation_mode": is_simulation_mode(),
        "created_at": _utc_now(),
        "updated_at": _utc_now(),
    }
    robot_context.report_movement_robot_status(req.robot_name, req.command_id, "busy")
    command_state.report_command_callback(runtime.movement_commands[req.command_id], "ACCEPTED", "accepted")
    background_tasks.add_task(movement_executor.execute_movement_command, req)
    return {"accepted": True, "command_id": req.command_id, "state": "ACCEPTED"}


@router.get("/movement-api/v1/commands/{command_id}")
def movement_get_command(command_id: str):
    command = runtime.movement_commands.get(command_id)
    if not command:
        raise HTTPException(status_code=404, detail=f"알 수 없는 command_id입니다: {command_id}")
    return command


@router.get("/movement-api/v1/robots/{robot_name}/pose")
def movement_robot_pose(robot_name: str):
    """Return the latest map-frame pose for the active robot."""
    if not runtime.navigator:
        raise HTTPException(status_code=503, detail="시스템 초기화 중입니다.")
    robot_context.assert_active_bridge_robot(robot_name, "위치 조회")
    pose = runtime.navigator.get_current_pose()
    localization = robot_context.localization_health()
    return {
        "robot_name": robot_name,
        "robot_id": ACTIVE_ROBOT_ID,
        "ros_domain_id": current_ros_domain_id(),
        "localized": localization["localized"],
        "localization": localization,
        "pose": pose,
        "reported_at": _utc_now(),
    }


@router.get("/movement-api/v1/robots/{robot_name}/localization")
def movement_robot_localization(robot_name: str):
    """Return normalized localization diagnostics for Main/UI."""
    if not runtime.navigator:
        raise HTTPException(status_code=503, detail="시스템 초기화 중입니다.")
    robot_context.assert_active_bridge_robot(robot_name, "localization 조회")
    return robot_context.localization_payload(robot_name)


@router.post("/movement-api/v1/robots/{robot_name}/localization/global-search", dependencies=[Depends(require_main_signature)])
def movement_robot_global_localization(robot_name: str, req: GlobalLocalizationRequest):
    """Start fail-closed map-wide AMCL search; motion is explicit and profile-bounded."""
    if not runtime.navigator:
        raise HTTPException(status_code=503, detail="시스템 초기화 중입니다.")
    robot_context.assert_active_bridge_robot(robot_name, "global localization 요청")
    try:
        result = robot_context.start_global_localization(req.strategy, req.allow_motion)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "accepted": bool(result["search"].get("accepted")),
        "robot_name": robot_name,
        "robot_id": ACTIVE_ROBOT_ID,
        "ros_domain_id": current_ros_domain_id(),
        "source": req.source,
        **result,
        "reported_at": _utc_now(),
    }


@router.post("/movement-api/v1/robots/{robot_name}/initial-pose", dependencies=[Depends(require_main_signature)])
def movement_robot_initial_pose(robot_name: str, req: InitialPoseRequest):
    """Publish an AMCL initial pose from a map click."""
    if not runtime.navigator:
        raise HTTPException(status_code=503, detail="시스템 초기화 중입니다.")
    robot_context.assert_active_bridge_robot(robot_name, "initial pose 요청")
    if req.frame_id != "map":
        raise HTTPException(status_code=400, detail="현재 initial pose frame_id는 map만 지원합니다.")
    requested_pose = runtime.navigator.set_initial_pose(
        {"x": req.x, "y": req.y, "yaw": req.yaw},
        frame_id=req.frame_id,
        covariance=req.covariance,
    )
    localization = robot_context.start_localization({"map_id": robot_context.localization_gate().config["map_id"], "map_metadata_identity": robot_context.localization_gate().config["map_metadata_identity"], "saved_at_epoch_sec": __import__("time").time(), "pose": requested_pose})
    return {
        "accepted": True,
        "robot_name": robot_name,
        "robot_id": ACTIVE_ROBOT_ID,
        "ros_domain_id": current_ros_domain_id(),
        "frame_id": req.frame_id,
        "source": req.source,
        "requested_pose": requested_pose,
        "message": "initial pose published to /initialpose",
        "localization": localization,
        "reported_at": _utc_now(),
    }


@router.get("/movement-api/v1/robots/{robot_name}/nav-state")
def movement_robot_nav_state(robot_name: str):
    """Return command/nav readiness diagnostics for Main/UI."""
    if not runtime.navigator or not runtime.mission_manager:
        raise HTTPException(status_code=503, detail="시스템 초기화 중입니다.")
    robot_context.assert_active_bridge_robot(robot_name, "nav-state 조회")
    pose = runtime.navigator.get_current_pose()
    localization = robot_context.localization_health()
    online = robot_context.active_robot_online()
    cmd_vel_subscribers = robot_context.cmd_vel_subscriber_count()
    is_emergency = bool(runtime.navigator.safety.estop)
    command_accepting = robot_context.command_accepting(is_emergency)
    pose_age = pose.get("age_sec") if pose else None
    return {
        "robot_name": robot_name,
        "robot_id": ACTIVE_ROBOT_ID,
        "ros_domain_id": current_ros_domain_id(),
        "map_frame": "map",
        "dry_run": runtime.mission_manager.dry_run,
        "simulation_mode": is_simulation_mode(),
        "robot_online": online,
        "cmd_vel_topic": "/cmd_vel",
        "cmd_vel_subscribers": cmd_vel_subscribers,
        "cmd_vel_subscriber_nodes": robot_context.cmd_vel_subscribers(),
        "command_accepting": command_accepting,
        "nav2_ready": bool(runtime.mission_manager.dry_run or getattr(runtime.navigator, "nav2_ready", False)),
        "navigator_status": runtime.navigator.status,
        "mission_status": runtime.mission_manager.mission_status,
        "is_emergency": is_emergency,
        "localized": localization["localized"],
        "localization": localization,
        "pose": pose,
        "pose_age_sec": pose_age,
        "last_pose_age_sec": pose_age,
        "pose_source": pose.get("source") if pose else None,
        "amcl_pose_received": bool(runtime.navigator.has_amcl_pose()),
        "simulated_pose_received": bool(runtime.navigator.has_simulated_pose()),
        "initial_pose_required": pose is None and online and not is_simulation_mode(),
        "reason": localization["reason"],
        "active_commands": [
            command_id for command_id, command in runtime.movement_commands.items()
            if command.get("robot_name") == robot_name and command.get("state") in ("ACCEPTED", "RUNNING")
        ],
        "reported_at": _utc_now(),
    }


@router.get("/movement-api/v1/map-state")
def movement_map_state():
    """Return the active map metadata used by Movement/Nav2."""
    return map_state.map_state_payload()


@router.get("/movement-api/v1/waypoints")
def movement_list_waypoints():
    """Configured map-frame waypoint catalog for Main Server/UI."""
    waypoints = robot_commands.load_waypoint_goals()
    return {
        "frame_id": "map",
        "count": len(waypoints),
        "waypoints": [
            {
                "waypoint_id": waypoint_id,
                "x": float(data["x"]),
                "y": float(data["y"]),
                "yaw": float(data.get("theta", data.get("yaw", 0.0))),
                "role": data.get("role"),
            }
            for waypoint_id, data in sorted(waypoints.items())
        ],
    }
@router.get("/movement-api/v1/inventory")
def movement_list_inventory():
    """Configured warehouse item-to-section mapping for Main Server/UI."""
    return {"items": list_inventory()}


@router.get("/movement-api/v1/simulation-state")
def movement_simulation_state():
    """Return API-only simulation state for Gazebo-less integration tests."""
    if not runtime.navigator:
        raise HTTPException(status_code=503, detail="시스템 초기화 중입니다.")
    return {
        "simulation_mode": is_simulation_mode(),
        "robot_name": robot_context.active_bridge_robot_id(),
        "robot_id": ACTIVE_ROBOT_ID,
        "pose": runtime.navigator.get_current_pose(),
        "is_emergency": bool(runtime.navigator.safety.estop),
        "active_commands": [
            command_id for command_id, command in runtime.movement_commands.items()
            if command.get("state") in ("ACCEPTED", "RUNNING")
        ],
        "reported_at": _utc_now(),
    }


# These root compatibility routes are registered before legacy mission routes, so
# Main's existing HttpMovementClient path remains protected without widening the
# public read-only health/status policy.
@router.post("/robot/estop", dependencies=[Depends(require_main_signature)])
def movement_estop():
    if not runtime.navigator or not runtime.mission_manager:
        raise HTTPException(status_code=503, detail="시스템 초기화 중입니다.")
    engage_estop()
    aborted_commands = command_state.abort_active_commands_for_estop()
    runtime.mission_manager.is_emergency = True
    runtime.mission_manager._set_mission_status("EMERGENCY", "API 비상 정지 명령")
    return {"message": "비상 정지 명령이 실행되었습니다.", "aborted_commands": aborted_commands}


@router.post("/robot/clear_estop", dependencies=[Depends(require_main_signature)])
def movement_clear_estop():
    if not runtime.navigator or not runtime.mission_manager:
        raise HTTPException(status_code=503, detail="시스템 초기화 중입니다.")
    runtime.navigator.safety.clear_estop()
    runtime.mission_manager.is_emergency = False
    if runtime.mission_manager.mission_status == "EMERGENCY":
        runtime.mission_manager._set_mission_status("IDLE")
    return {"message": "비상 정지 상태가 해제되었습니다."}


@router.post("/movement-api/v1/manual/rotate", dependencies=[Depends(require_main_signature)])
def movement_manual_rotate(req: ManualRotateRequest):
    """Manual rotation endpoint for short operator jog commands."""
    manual_control.prepare_manual_control(req.robot_name, req.override_nav)
    if req.direction not in ("left", "right"):
        raise HTTPException(status_code=400, detail="direction은 left 또는 right만 가능합니다.")

    signed_angular_z = req.angular_z if req.direction == "left" else -req.angular_z
    executed = manual_control.execute_manual_velocity(0.0, signed_angular_z, req.duration_sec)
    if not executed:
        raise HTTPException(status_code=409, detail="수동 회전 명령이 실행되지 않았습니다.")

    return {
        "accepted": True,
        "robot_name": req.robot_name,
        "direction": req.direction,
        "duration_sec": req.duration_sec,
        "angular_z": signed_angular_z,
        "dry_run": runtime.mission_manager.dry_run,
    }


@router.post("/movement-api/v1/manual/translate", dependencies=[Depends(require_main_signature)])
def movement_manual_translate(req: ManualTranslateRequest):
    """Manual forward/backward endpoint for short operator jog commands."""
    manual_control.prepare_manual_control(req.robot_name, req.override_nav)
    if req.direction not in ("forward", "backward"):
        raise HTTPException(status_code=400, detail="direction은 forward 또는 backward만 가능합니다.")

    signed_linear_x = req.linear_x if req.direction == "forward" else -req.linear_x
    executed = manual_control.execute_manual_velocity(signed_linear_x, 0.0, req.duration_sec)
    if not executed:
        raise HTTPException(status_code=409, detail="수동 직진/후진 명령이 실행되지 않았습니다.")

    return {
        "accepted": True,
        "robot_name": req.robot_name,
        "direction": req.direction,
        "duration_sec": req.duration_sec,
        "linear_x": signed_linear_x,
        "dry_run": runtime.mission_manager.dry_run,
    }


@router.post("/movement-api/v1/manual/start", dependencies=[Depends(require_main_signature)])
def movement_manual_start(req: ManualStartRequest):
    """Start continuous manual jog until /manual/stop or timeout_sec."""
    manual_control.prepare_manual_control(req.robot_name, req.override_nav, allow_manual_busy=True)
    if req.command not in ("forward", "backward", "left", "right", "stop"):
        raise HTTPException(status_code=400, detail="command는 forward, backward, left, right, stop만 가능합니다.")

    linear_x = 0.0
    angular_z = 0.0
    if req.command == "forward":
        linear_x = req.linear_x
    elif req.command == "backward":
        linear_x = -req.linear_x
    elif req.command == "left":
        angular_z = req.angular_z
    elif req.command == "right":
        angular_z = -req.angular_z

    if req.command == "stop":
        if not runtime.mission_manager.dry_run:
            runtime.navigator.publish_stop_velocity()
        return {
            "accepted": True,
            "robot_name": req.robot_name,
            "command": req.command,
            "stopped": True,
            "dry_run": runtime.mission_manager.dry_run,
        }

    if not runtime.mission_manager.dry_run:
        executed = runtime.navigator.start_continuous_velocity(
            linear_x=linear_x,
            angular_z=angular_z,
            timeout_sec=req.timeout_sec,
        )
        if not executed:
            raise HTTPException(status_code=409, detail="수동 연속 조작 명령이 실행되지 않았습니다.")

    return {
        "accepted": True,
        "robot_name": req.robot_name,
        "command": req.command,
        "linear_x": linear_x,
        "angular_z": angular_z,
        "timeout_sec": req.timeout_sec,
        "dry_run": runtime.mission_manager.dry_run,
    }


@router.post("/movement-api/v1/manual/stop", dependencies=[Depends(require_main_signature)])
def movement_manual_stop(req: ManualStopRequest):
    """Manual non-estop stop endpoint for operator jog commands."""
    if not runtime.navigator or not runtime.mission_manager:
        raise HTTPException(status_code=503, detail="시스템 초기화 중입니다.")
    if req.robot_name != robot_context.active_bridge_robot_id():
        raise HTTPException(
            status_code=409,
            detail=(
                f"이 Movement API 프로세스는 {robot_context.active_bridge_robot_id()}만 담당합니다. "
                f"{req.robot_name} 명령은 해당 robot_name 프로세스로 보내야 합니다."
            ),
        )
    if not runtime.mission_manager.dry_run:
        runtime.navigator.publish_stop_velocity()

    return {
        "accepted": True,
        "robot_name": req.robot_name,
        "stopped": True,
        "dry_run": runtime.mission_manager.dry_run,
    }


@router.post("/movement-api/v1/routes/preview", dependencies=[Depends(require_main_signature)])
def movement_preview_route(req: MovementRouteRequest):
    """Build item-based or coordinate-based route steps without executing them."""
    if req.robot_name != robot_context.active_bridge_robot_id():
        raise HTTPException(
            status_code=409,
            detail=(
                f"이 Movement API 프로세스는 {robot_context.active_bridge_robot_id()}만 담당합니다. "
                f"{req.robot_name} 명령은 해당 robot_name 프로세스로 보내야 합니다."
            ),
        )

    raw_steps = raw_steps_from_route_request(req)
    if raw_steps is not None:
        return raw_route_preview(req, raw_steps)

    route_type = (req.route_type or "").strip().lower()
    if not route_type:
        raise HTTPException(
            status_code=400,
            detail="route_type이 필요합니다. 좌표 기반 명령은 steps, goal, goals, 또는 x/y/yaw를 사용하세요.",
        )
    if route_type not in ("standby", "return_to_standby") and not req.item_name:
        raise HTTPException(
            status_code=400,
            detail="품목 운송 명령은 item_name이 필요합니다. 리프트 없는 복귀는 route_type=standby와 return_waypoint를 사용하세요.",
        )

    try:
        route = build_movement_steps(
            req.route_type,
            req.item_name,
            req.wait_sec,
            req.source_section_id,
            req.target_section_id,
            req.return_waypoint,
        )
    except RouteBuildError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {
        "command_id": req.command_id,
        "task_id": req.task_id,
        "robot_name": req.robot_name,
        "route_type": route["route_type"],
        "item": route["item"],
        "waypoints": route["waypoints"],
        "steps": route["steps"],
        "traffic_policy": route.get("traffic_policy"),
        "traffic_segments": route.get("traffic_segments", []),
        "yield_candidates": route.get("yield_candidates", []),
        "dock_transfer": route.get("dock_transfer"),
        "pickup_transfer": route.get("pickup_transfer"),
        "dropoff_transfer": route.get("dropoff_transfer"),
        "operation_sequence": route.get("operation_sequence", []),
        "source_section_id": route.get("source_section_id"),
        "target_section_id": route.get("target_section_id"),
        "return_waypoint": route.get("return_waypoint"),
        "input_mode": "item",
    }


@router.post("/movement-api/v1/routes/commands", dependencies=[Depends(require_main_signature)])
def movement_accept_route_command(req: MovementRouteRequest, background_tasks: BackgroundTasks):
    """Accept an item-based or coordinate-based route and execute it as a Movement command."""
    try:
        preview = movement_preview_route(req)
    except HTTPException:
        raise
    command_req = MovementCommandRequest(
        command_id=req.command_id,
        task_id=req.task_id,
        robot_name=req.robot_name,
        steps=[MovementStep(**step) for step in preview["steps"]],
        callback_url=req.callback_url,
    )
    response = movement_accept_command(command_req, background_tasks)
    command = runtime.movement_commands.get(req.command_id)
    if command is not None:
        command["route_type"] = preview["route_type"]
        command["item"] = preview["item"]
        command["waypoints"] = preview["waypoints"]
        command["input_mode"] = preview.get("input_mode")
        command["operation_sequence"] = preview.get("operation_sequence", [])
        command["pickup_transfer"] = preview.get("pickup_transfer")
        command["dropoff_transfer"] = preview.get("dropoff_transfer")
        command["source_section_id"] = preview.get("source_section_id")
        command["target_section_id"] = preview.get("target_section_id")
        command["return_waypoint"] = preview.get("return_waypoint")
    return {
        **response,
        "route_type": preview["route_type"],
        "item": preview["item"],
        "waypoints": preview["waypoints"],
        "steps": preview["steps"],
        "traffic_policy": preview.get("traffic_policy"),
        "traffic_segments": preview.get("traffic_segments", []),
        "yield_candidates": preview.get("yield_candidates", []),
        "input_mode": preview.get("input_mode"),
        "dock_transfer": preview.get("dock_transfer"),
        "pickup_transfer": preview.get("pickup_transfer"),
        "dropoff_transfer": preview.get("dropoff_transfer"),
        "operation_sequence": preview.get("operation_sequence", []),
        "source_section_id": preview.get("source_section_id"),
        "target_section_id": preview.get("target_section_id"),
        "return_waypoint": preview.get("return_waypoint"),
    }
