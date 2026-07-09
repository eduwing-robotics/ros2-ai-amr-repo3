"""Legacy mission HTTP routes."""

from fastapi import APIRouter, BackgroundTasks, HTTPException

from nav_app.config import active_robot_profile
from nav_app.models import MissionRequest, StatusResponse
from nav_app.runtime import runtime
from nav_app.settings import is_simulation_mode
from nav_app.services import command_state
from nav_app.services import mission_helpers
from nav_app.services import robot_context

router = APIRouter()


@router.get("/robot/status", response_model=StatusResponse)
def get_status():
    """로봇의 현재 실시간 상태를 반환합니다."""
    if not runtime.navigator or not runtime.mission_manager:
        raise HTTPException(status_code=503, detail="시스템 초기화 중입니다.")

    snapshot = runtime.mission_manager.get_status_snapshot()
    return StatusResponse(
        robot_id=snapshot["robot_id"],
        bridge_robot_id=snapshot["bridge_robot_id"],
        ros_domain_id=snapshot["ros_domain_id"],
        center_domain_id=snapshot["center_domain_id"],
        namespace=snapshot["namespace"],
        teleop_command_topic=snapshot["teleop_command_topic"],
        camera_topic=snapshot["camera_topic"],
        capabilities=snapshot["capabilities"],
        status=snapshot["navigator_status"],
        mission_status=snapshot["mission_status"],
        battery=snapshot["battery"],
        is_emergency=snapshot["is_emergency"],
        current_mission=snapshot["mission_type"],
        mission_id=snapshot["mission_id"],
        item_name=snapshot["item_name"],
        count=snapshot["count"],
        last_error=snapshot["last_error"],
        pose=snapshot.get("pose"),
        localized=snapshot.get("pose") is not None,
        robot_online=robot_context.active_robot_online(),
        dry_run=snapshot["dry_run"],
    )


@router.post("/mission/start")
def start_mission(req: MissionRequest, background_tasks: BackgroundTasks):
    """새로운 물류 미션을 시작합니다."""
    if not runtime.navigator or not runtime.mission_manager:
        raise HTTPException(status_code=503, detail="시스템 초기화 중입니다.")

    mission_helpers.validate_request(req)

    if mission_helpers.is_busy():
        raise HTTPException(status_code=409, detail="로봇이 이미 다른 작업을 수행 중입니다.")

    if runtime.navigator.safety.estop:
        raise HTTPException(status_code=400, detail="비상 정지 상태에서는 미션을 시작할 수 없습니다.")
    if not is_simulation_mode() and not runtime.mission_manager.dry_run and not robot_context.active_robot_online():
        raise HTTPException(
            status_code=503,
            detail={
                "message": "실제 로봇 bringup이 감지되지 않습니다. /cmd_vel subscriber를 확인하세요.",
                "cmd_vel_topic": "/cmd_vel",
                "cmd_vel_subscribers": robot_context.cmd_vel_subscriber_count(),
                "cmd_vel_subscriber_nodes": robot_context.cmd_vel_subscribers(),
            },
        )

    profile = active_robot_profile()
    mission_id = runtime.mission_manager.accept_mission(req.robot_id, req.mission_type, req.item_name, req.count)
    background_tasks.add_task(mission_helpers.execute_mission, req, mission_id)

    return {
        "message": f"{req.mission_type} 미션이 접수되었습니다.",
        "robot_id": req.robot_id,
        "bridge_robot_id": profile.get("bridge_robot_id"),
        "ros_domain_id": profile["ros_domain_id"],
        "center_domain_id": profile.get("center_domain_id"),
        "namespace": profile["namespace"],
        "teleop_command_topic": profile.get("teleop_command_topic"),
        "camera_topic": profile.get("camera_topic"),
        "mission_id": mission_id,
        "mission_status": runtime.mission_manager.mission_status,
        "dry_run": runtime.mission_manager.dry_run,
    }


@router.post("/robot/estop")
def trigger_estop():
    """즉시 비상 정지 명령을 내립니다."""
    if not runtime.navigator or not runtime.mission_manager:
        raise HTTPException(status_code=503, detail="시스템 초기화 중입니다.")

    runtime.navigator.safety.enable_estop()
    runtime.navigator.nav.cancelTask()
    runtime.navigator.publish_stop_velocity()
    aborted_commands = command_state.abort_active_commands_for_estop()
    runtime.mission_manager.is_emergency = True
    runtime.mission_manager._set_mission_status("EMERGENCY", "API 비상 정지 명령")

    return {"message": "비상 정지 명령이 실행되었습니다.", "aborted_commands": aborted_commands}


@router.post("/robot/clear_estop")
def clear_estop():
    """비상 정지 상태를 해제합니다."""
    if not runtime.navigator or not runtime.mission_manager:
        raise HTTPException(status_code=503, detail="시스템 초기화 중입니다.")

    runtime.navigator.safety.clear_estop()
    runtime.mission_manager.is_emergency = False
    if runtime.mission_manager.mission_status == "EMERGENCY":
        runtime.mission_manager._set_mission_status("IDLE")
    return {"message": "비상 정지 상태가 해제되었습니다."}
