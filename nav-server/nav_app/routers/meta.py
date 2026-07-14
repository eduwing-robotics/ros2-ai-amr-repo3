"""Meta and health HTTP routes."""
import os

from fastapi import APIRouter

from nav_app.config import (
    ROBOT_PROFILES,
    active_endpoint_contract,
    active_route_config,
    current_ros_domain_id,
    process_ros_domain_id,
)
from nav_app.runtime import runtime
from nav_app.settings import (
    ACTIVE_ROBOT_ID,
    ARUCO_DETECTION_MAX_AGE_SEC,
    is_simulation_mode,
)
from nav_app.services import robot_context
from nav_app.services.capabilities import active_lift_status, profile_capabilities
from nav_app.config import active_robot_profile
from nav_app.services.lift_backends import lift_provenance

router = APIRouter()


@router.get("/robots")
def list_robots():
    """메인 서버가 사용할 수 있는 robot_id 라우팅 테이블을 반환합니다."""
    return {
        "active_robot_id": ACTIVE_ROBOT_ID,
        "active_ros_domain_id": current_ros_domain_id(),
        "endpoint_contract_url": "/movement-api/v1/endpoints",
        "robots": list(ROBOT_PROFILES.values()),
    }


@router.get("/movement-api/v1/endpoints")
def movement_endpoint_contract():
    """관제 서버가 hostname-first API endpoint 계약과 resolve 상태를 조회합니다."""
    return active_endpoint_contract()


@router.get("/movement-api/v1/health")
def movement_health():
    """Movement API 연결 확인용 health endpoint입니다."""
    dry_run = runtime.mission_manager.dry_run if runtime.mission_manager else os.getenv("DRY_RUN_MISSION", "0") == "1"
    navigator_status = runtime.navigator.status if runtime.navigator else "offline"
    is_emergency = bool(runtime.navigator and runtime.navigator.safety.estop)
    robot_online = robot_context.active_robot_online()
    cmd_vel_subscribers = robot_context.cmd_vel_subscriber_count()
    command_accepting = robot_context.command_accepting(is_emergency)
    pose = runtime.navigator.get_current_pose() if runtime.navigator else None
    localization = robot_context.localization_health()
    return {
        "ok": True,
        "service": "slam_nav_ws movement-api",
        "active_robot_id": ACTIVE_ROBOT_ID,
        "robot_name": robot_context.active_bridge_robot_id(),
        "endpoint_contract_url": "/movement-api/v1/endpoints",
        "advertised_nav_api_url": active_route_config().get("nav_api_url"),
        "ros_domain_id": current_ros_domain_id(),
        "process_ros_domain_id": process_ros_domain_id(),
        "dry_run": dry_run,
        "robot_online": robot_online,
        "cmd_vel_topic": "/cmd_vel",
        "cmd_vel_subscribers": cmd_vel_subscribers,
        "cmd_vel_subscriber_nodes": robot_context.cmd_vel_subscribers(),
        "command_accepting": command_accepting,
        "nav2_ready": bool(dry_run or (runtime.navigator and getattr(runtime.navigator, "nav2_ready", False))),
        "navigator_status": navigator_status,
        "is_emergency": is_emergency,
        "map_frame": "map",
        "pose": pose,
        "localized": localization["localized"],
        "localization": localization,
        "localization_required": not dry_run and not is_simulation_mode(),
        "simulation_mode": is_simulation_mode(),
        "capabilities": profile_capabilities(active_robot_profile()),
        "lift": active_lift_status(active_robot_profile()),
        **lift_provenance(backend=getattr(runtime, "lift_client", None)),
        "aruco_detection_topic": robot_context.aruco_detection_topic(),
        "latest_aruco_detections": runtime.navigator.get_latest_aruco_detection(max_age_sec=ARUCO_DETECTION_MAX_AGE_SEC) if runtime.navigator else [],
    }
