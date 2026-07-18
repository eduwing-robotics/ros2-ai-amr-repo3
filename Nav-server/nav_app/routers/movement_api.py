"""Movement API HTTP routes."""
import time
import json
import threading
from typing import Any, Dict, Optional

from fastapi import APIRouter, BackgroundTasks, Header, HTTPException

from route_builder import RouteBuildError, build_inbound2_storage_b_scenario, build_movement_steps, list_inventory
from traffic_manager import TrafficLockConflict

from nav_app.adapters.callbacks import post_json_callback
from nav_app.config import (
    active_route_config,
    current_ros_domain_id,
)
from nav_app.models import (
    InitialPoseRequest,
    Inbound2StorageBScenarioRequest,
    ManualRotateRequest,
    ManualStartRequest,
    ManualStopRequest,
    ManualTranslateRequest,
    MovementCommandRequest,
    MovementRouteRequest,
    MovementStep,
    ResumeCommandRequest,
)
from nav_app.runtime import runtime
from nav_app.settings import (
    ACTIVE_ROBOT_ID,
    ARUCO_DETECTION_MAX_AGE_SEC,
    GATE_TIMEOUT_SEC,
    is_simulation_mode,
)
from nav_app.util.time import utc_now as _utc_now
from nav_app.services import command_state
from nav_app.services import manual_control
from nav_app.services import map_state
from nav_app.services import mission_helpers
from nav_app.services import movement_executor
from nav_app.services import robot_commands
from nav_app.services import robot_context
from nav_app.services.route_helpers import (
    raw_route_preview,
    raw_steps_from_route_request,
    traffic_segments_from_steps,
)

router = APIRouter()


def _inbound2_storage_b_preview(req: Inbound2StorageBScenarioRequest):
    if req.robot_name != "tb3_2":
        raise HTTPException(status_code=400, detail="inbound2-storage-b 시나리오는 tb3_2 전용입니다.")
    if req.robot_name != robot_context.active_bridge_robot_id():
        raise HTTPException(
            status_code=409,
            detail=f"이 Movement API 프로세스는 {robot_context.active_bridge_robot_id()}만 담당합니다. tb3_2의 8002 포트로 요청하세요.",
        )
    scenario = build_inbound2_storage_b_scenario(dry_run=req.dry_run, skip_lift=req.skip_lift)
    if req.scenario_version != scenario["scenario_version"]:
        raise HTTPException(status_code=409, detail=f"unsupported scenario_version: {req.scenario_version}")
    pose = runtime.navigator.get_current_pose() if runtime.navigator else None
    emergency = bool(runtime.navigator and runtime.navigator.safety.estop)
    robot_online = robot_context.active_robot_online() if runtime.navigator else False
    navigator_status = getattr(runtime.navigator, "status", None) if runtime.navigator else None
    command_accepting = bool(runtime.navigator and runtime.mission_manager and robot_context.command_accepting(emergency))
    active = next(
        (item.get("command_id") for item in runtime.movement_commands.values() if item.get("state") in ("ACCEPTED", "RUNNING", "STOPPING", "STOP_REQUESTED")),
        None,
    )
    blockers = []
    if not runtime.navigator or not runtime.mission_manager:
        blockers.append("system_initializing")
    if emergency:
        blockers.append("estop_latched")
    if not req.dry_run and not robot_online:
        blockers.append("robot_offline")
    if not req.dry_run and pose is None:
        blockers.append("localization_unavailable")
    if not req.dry_run and navigator_status != "IDLE":
        blockers.append("navigator_not_idle")
    if not req.dry_run and not command_accepting:
        blockers.append("command_not_accepting")
    if active and active != req.command_id:
        blockers.append("active_execution")
    return {
        "command_id": req.command_id,
        "task_id": req.task_id,
        **scenario,
        "executable": not blockers,
        "blocking_reasons": blockers,
        "active_execution": active,
        "health": {
            "robot_online": robot_online,
            "command_accepting": command_accepting,
            "localized": pose is not None,
            "pose_fresh": pose is not None and robot_online,
            "is_emergency": emergency,
            "navigator_status": navigator_status,
        },
    }


def _movement_step_to_dict(step: MovementStep) -> Dict[str, Any]:
    if hasattr(step, "model_dump"):
        return step.model_dump()
    return step.dict()


def _movement_steps_to_dicts(steps):
    return [_movement_step_to_dict(step) for step in steps]


def _command_fingerprint(req: MovementCommandRequest) -> str:
    data = req.model_dump() if hasattr(req, "model_dump") else req.dict()
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


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


def _report_initial_acceptance(command: Dict[str, Any], callback_payload: Optional[Dict[str, Any]]):
    """Send acceptance reports without delaying the command HTTP ACK or execution."""
    callback_url = command.get("callback_url")
    if callback_url and callback_payload:
        if runtime.state_store:
            runtime.state_store.enqueue_callback(callback_url, callback_payload)
        delivered = post_json_callback(
            callback_url, callback_payload, label="CommandCallback",
            on_failure=(lambda outcome: runtime.state_store.record_callback_failure(callback_payload["event_id"], outcome))
            if runtime.state_store else None,
        )
        if delivered and runtime.state_store:
            runtime.state_store.mark_callback_delivered(callback_payload["event_id"])
    robot_context.report_movement_robot_status(command["robot_name"], command["command_id"], "busy")


def _dispatch_initial_acceptance(command: Dict[str, Any]):
    # Reserve ACCEPTED sequence synchronously so RUNNING can never overtake it.
    callback_payload = None
    if command.get("callback_url"):
        callback_payload = command_state.command_callback_payload(command, "COMMAND_ACCEPTED", "accepted")
    threading.Thread(
        target=_report_initial_acceptance,
        args=(command, callback_payload),
        name=f"movement-accepted-{command['command_id']}",
        daemon=True,
    ).start()


def _accept_movement_command(
    req: MovementCommandRequest,
    background_tasks: BackgroundTasks,
    *,
    source_metadata: Optional[Dict[str, Any]] = None,
):
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

    request_fingerprint = _command_fingerprint(req)
    source_fingerprint = (source_metadata or {}).get("source_request_fingerprint")
    with runtime.command_state_lock:
        existing = runtime.movement_commands.get(req.command_id)
        if existing:
            fingerprint_key = "source_request_fingerprint" if source_fingerprint is not None else "request_fingerprint"
            expected_fingerprint = source_fingerprint if source_fingerprint is not None else request_fingerprint
            if existing.get(fingerprint_key) != expected_fingerprint:
                raise HTTPException(status_code=409, detail="same command_id was already used with a different payload")
            return {
                "accepted": True,
                "command_id": req.command_id,
                "state": existing["state"],
                "duplicate": True,
            }

        active_command = next(
            (command for command in runtime.movement_commands.values()
             if command.get("robot_name") == req.robot_name and command.get("state") in ("ACCEPTED", "RUNNING", "STOPPING", "STOP_REQUESTED")),
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

        command = {
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
            "steps": _movement_steps_to_dicts(req.steps),
            "gate_timeout_sec": next((step.payload.get("gate_timeout_sec") for step in req.steps if step.payload.get("gate_timeout_sec") is not None), GATE_TIMEOUT_SEC),
            "simulation_mode": is_simulation_mode(),
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "request_fingerprint": request_fingerprint,
            "callback_sequence": -1,
        }
        if source_metadata:
            command.update(source_metadata)
        runtime.movement_commands[req.command_id] = command
        command_state.persist_command(command)

    _dispatch_initial_acceptance(command)
    background_tasks.add_task(movement_executor.execute_movement_command, req)
    return {"accepted": True, "command_id": req.command_id, "state": "ACCEPTED"}


@router.post("/movement-api/v1/commands")
def movement_accept_command(req: MovementCommandRequest, background_tasks: BackgroundTasks):
    """Main Server 스펙의 전체 steps command dispatch endpoint입니다."""
    return _accept_movement_command(req, background_tasks)


@router.get("/movement-api/v1/commands/{command_id}")
def movement_get_command(command_id: str):
    command = runtime.movement_commands.get(command_id)
    if not command:
        raise HTTPException(status_code=404, detail=f"알 수 없는 command_id입니다: {command_id}")
    return {**command, "last_sequence": command.get("callback_sequence", -1)}


@router.post("/movement-api/v1/commands/{command_id}/resume")
def movement_resume_command(command_id: str, req: ResumeCommandRequest, background_tasks: BackgroundTasks):
    source = runtime.movement_commands.get(command_id)
    if not source:
        raise HTTPException(status_code=404, detail=f"알 수 없는 command_id입니다: {command_id}")
    if source.get("state") not in ("FAILED", "ABORTED", "STOPPED"):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "only FAILED, ABORTED, or STOPPED commands can be resumed",
                "state": source.get("state"),
            },
        )
    if runtime.navigator and runtime.navigator.safety.estop:
        raise HTTPException(status_code=409, detail="estop is latched")
    if not is_simulation_mode() and not robot_context.active_robot_online():
        raise HTTPException(status_code=409, detail="robot is offline")
    if not is_simulation_mode() and runtime.navigator and runtime.navigator.get_current_pose() is None:
        raise HTTPException(status_code=409, detail="localization is unavailable")
    if not req.force and not source.get("resumable"):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "command is not marked resumable",
                "reason": source.get("reason"),
                "stage": source.get("stage"),
            },
        )

    stored_steps = source.get("steps")
    if not isinstance(stored_steps, list) or not stored_steps:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "source command has no stored steps; cannot resume this older command",
                "command_id": command_id,
            },
        )

    diagnostics = source.get("failure_diagnostics") if isinstance(source.get("failure_diagnostics"), dict) else {}
    failed_index = source.get("current_step_index")
    if not isinstance(failed_index, int):
        failed_index = diagnostics.get("failed_step_index")
    if not isinstance(failed_index, int):
        failed_index = 0
    from_step_index = req.from_step_index if req.from_step_index is not None else failed_index
    if source.get("scenario_id") and req.from_step_index is not None:
        matching = [
            index for index, step in enumerate(stored_steps)
            if (step.get("payload") or {}).get("business_step_index") == req.from_step_index
            and (step.get("payload") or {}).get("business_step_start", True)
        ]
        if not matching:
            raise HTTPException(status_code=400, detail="from_step_index must be a scenario business step boundary")
        from_step_index = matching[0]
    if from_step_index < 0 or from_step_index >= len(stored_steps):
        raise HTTPException(
            status_code=400,
            detail={
                "message": "from_step_index is outside stored steps",
                "from_step_index": from_step_index,
                "step_count": len(stored_steps),
            },
        )

    resume_steps = [MovementStep(**step) for step in stored_steps[from_step_index:]]
    resume_command_id = req.command_id or f"{command_id}-resume-{int(time.time())}"
    movement_req = MovementCommandRequest(
        command_id=resume_command_id,
        task_id=source.get("task_id"),
        robot_name=source.get("robot_name"),
        steps=resume_steps,
        callback_url=req.callback_url if req.callback_url is not None else source.get("callback_url"),
    )
    resume_business_index = (resume_steps[0].payload or {}).get("business_step_index")
    source_metadata = {
        "input_mode": "resume",
        "source_command_id": command_id,
        "resume_from_step_index": resume_business_index if resume_business_index is not None else from_step_index,
        "resume_source_reason": source.get("reason"),
        "resume_source_stage": source.get("stage"),
        "resume_source_diagnostics": diagnostics or None,
        "scenario": source.get("scenario"),
        "scenario_id": source.get("scenario_id"),
        "scenario_version": source.get("scenario_version"),
        "execution_id": f"exec-{resume_command_id}",
        "parent_execution_id": source.get("execution_id"),
        "authority_owner": "MOVEMENT",
        "authority_released": False,
        "cargo_state": source.get("cargo_state", "EMPTY"),
        "business_completed": bool(source.get("business_completed")),
        "last_completed_step_index": source.get("last_completed_step_index"),
        "return_poses": dict(source.get("return_poses") or {}),
    }
    response = _accept_movement_command(movement_req, background_tasks, source_metadata=source_metadata)
    resume_command = runtime.movement_commands.get(resume_command_id)
    if resume_command is not None:
        command_state.persist_command(resume_command)
    return {
        **response,
        "source_command_id": command_id,
        "resume_from_step_index": resume_business_index if resume_business_index is not None else from_step_index,
        "resumed_step_actions": [step.action for step in resume_steps],
    }


@router.get("/movement-api/v1/robots/{robot_name}/pose")
def movement_robot_pose(robot_name: str):
    """Return the latest map-frame pose for the active robot."""
    if not runtime.navigator:
        raise HTTPException(status_code=503, detail="시스템 초기화 중입니다.")
    robot_context.assert_active_bridge_robot(robot_name, "위치 조회")
    is_emergency = bool(runtime.navigator.safety.estop)
    readiness = robot_context.readiness_snapshot(is_emergency)
    return {
        "robot_name": robot_name,
        "robot_id": ACTIVE_ROBOT_ID,
        "ros_domain_id": current_ros_domain_id(),
        "localized": readiness["localized"],
        "pose_fresh": readiness["pose_fresh"],
        "pose_in_map": readiness["pose_in_map"],
        "pose": readiness["pose"],
        "reported_at": _utc_now(),
    }


@router.get("/movement-api/v1/robots/{robot_name}/localization")
def movement_robot_localization(robot_name: str):
    """Return normalized localization diagnostics for Main/UI."""
    if not runtime.navigator:
        raise HTTPException(status_code=503, detail="시스템 초기화 중입니다.")
    robot_context.assert_active_bridge_robot(robot_name, "localization 조회")
    return robot_context.localization_payload(robot_name)


@router.post("/movement-api/v1/robots/{robot_name}/initial-pose")
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
    return {
        "accepted": True,
        "robot_name": robot_name,
        "robot_id": ACTIVE_ROBOT_ID,
        "ros_domain_id": current_ros_domain_id(),
        "frame_id": req.frame_id,
        "source": req.source,
        "requested_pose": requested_pose,
        "message": "initial pose published to /initialpose",
        "localization": robot_context.localization_payload(robot_name),
        "reported_at": _utc_now(),
    }


@router.get("/movement-api/v1/robots/{robot_name}/nav-state")
def movement_robot_nav_state(robot_name: str):
    """Return command/nav readiness diagnostics for Main/UI."""
    if not runtime.navigator or not runtime.mission_manager:
        raise HTTPException(status_code=503, detail="시스템 초기화 중입니다.")
    robot_context.assert_active_bridge_robot(robot_name, "nav-state 조회")
    is_emergency = bool(runtime.navigator.safety.estop)
    readiness = robot_context.readiness_snapshot(is_emergency)
    pose = readiness["pose"]
    online = readiness["robot_online"]
    cmd_vel_subscribers = robot_context.cmd_vel_subscriber_count()
    command_accepting = readiness["command_accepting"]
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
        "nav2_ready": readiness["nav2_ready"],
        "navigator_status": runtime.navigator.status,
        "mission_status": runtime.mission_manager.mission_status,
        "is_emergency": is_emergency,
        "localized": pose is not None,
        "pose": pose,
        "pose_age_sec": pose_age,
        "last_pose_age_sec": pose_age,
        "pose_source": pose.get("source") if pose else None,
        "amcl_pose_received": bool(runtime.navigator.has_amcl_pose()),
        "simulated_pose_received": bool(runtime.navigator.has_simulated_pose()),
        "initial_pose_required": pose is None and online and not is_simulation_mode(),
        "reason": readiness["reason"],
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


@router.post("/movement-api/v1/manual/rotate")
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


@router.post("/movement-api/v1/manual/translate")
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


@router.post("/movement-api/v1/manual/start")
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


@router.post("/movement-api/v1/manual/stop")
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


@router.post("/movement-api/v1/routes/preview")
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


@router.post(
    "/movement-api/v1/scenarios/inbound2-storage-b/preview",
    description="Fixed legacy inbound2-storage-b profile preview; not a validator for generic ScenarioCommandRequest payloads.",
)
def movement_preview_inbound2_storage_b(req: Inbound2StorageBScenarioRequest):
    """Preview the fixed tb3_2 inbound2 load -> storage B unload -> wait2 park scenario."""
    return _inbound2_storage_b_preview(req)


@router.post("/movement-api/v1/scenarios/inbound2-storage-b/commands")
def movement_accept_inbound2_storage_b(
    req: Inbound2StorageBScenarioRequest,
    background_tasks: BackgroundTasks,
    idempotency_key: Optional[str] = Header(default=None, alias="Idempotency-Key"),
):
    """Execute the fixed scenario as one idempotent Movement command."""
    preview = _inbound2_storage_b_preview(req)
    if idempotency_key is not None and idempotency_key != req.command_id:
        raise HTTPException(status_code=422, detail="Idempotency-Key must equal command_id")
    if not preview["executable"] and not req.dry_run:
        raise HTTPException(status_code=409, detail={"message": "scenario is not executable", "blocking_reasons": preview["blocking_reasons"]})
    command_req = MovementCommandRequest(
        command_id=req.command_id,
        task_id=req.task_id,
        robot_name=req.robot_name,
        steps=[MovementStep(**step) for step in preview["steps"]],
        callback_url=req.callback_url,
    )
    request_data = req.model_dump() if hasattr(req, "model_dump") else req.dict()
    source_metadata = {
        "source_request_fingerprint": json.dumps(request_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        "scenario": preview["scenario"],
        "scenario_id": preview["scenario_id"],
        "scenario_version": preview["scenario_version"],
        "execution_id": f"exec-{req.command_id}",
        "authority_owner": "MOVEMENT",
        "authority_released": False,
        "cargo_state": "EMPTY",
        "business_completed": False,
        "current_step_code": None,
        "last_completed_step_index": None,
        "plan_hash": preview["plan_hash"],
    }
    response = _accept_movement_command(command_req, background_tasks, source_metadata=source_metadata)
    command = runtime.movement_commands.get(req.command_id)
    if command is not None:
        command["scenario"] = preview["scenario"]
        command["scenario_id"] = preview["scenario_id"]
        command["scenario_version"] = preview["scenario_version"]
        command["execution_id"] = f"exec-{req.command_id}"
        command["authority_owner"] = "MOVEMENT"
        command["authority_released"] = False
        command["cargo_state"] = "EMPTY"
        command["business_completed"] = False
        command["current_step_index"] = None
        command["current_step_code"] = None
        command["last_completed_step_index"] = None
        command["waypoints"] = preview["waypoints"]
        command["operation_sequence"] = preview["operation_sequence"]
    return {
        **response,
        "execution_id": command.get("execution_id") if command else f"exec-{req.command_id}",
        "scenario_id": preview["scenario_id"],
        "scenario_version": preview["scenario_version"],
        "authority_owner": "MOVEMENT",
        "plan_hash": preview["plan_hash"],
    }


@router.post("/movement-api/v1/commands/{command_id}/safe-stop")
def movement_safe_stop(command_id: str):
    command = runtime.movement_commands.get(command_id)
    if not command:
        raise HTTPException(status_code=404, detail=f"알 수 없는 command_id입니다: {command_id}")
    if command.get("state") in ("DONE", "FAILED", "ABORTED", "STOPPED", "CANCELLED"):
        return {"command_id": command_id, "state": command.get("state"), "duplicate": True}
    command["safe_stop_requested"] = True
    command["state"] = "STOPPING"
    command["message"] = "safe stop requested"
    command["resumable"] = True
    command["updated_at"] = _utc_now()
    command_state.persist_command(command)
    if runtime.navigator:
        cancel_task = getattr(getattr(runtime.navigator, "nav", None), "cancelTask", None)
        if callable(cancel_task):
            cancel_task()
        runtime.navigator.publish_stop_velocity()
    return {"command_id": command_id, "state": "STOPPING", "stop_requested": True}


@router.post("/movement-api/v1/routes/commands")
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
