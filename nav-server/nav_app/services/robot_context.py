"""Robot connectivity and localization payload helpers."""
import os

from fastapi import HTTPException

from nav_app.config import active_robot_profile, current_ros_domain_id
from nav_app.runtime import runtime
from nav_app.settings import ACTIVE_ROBOT_ID, is_simulation_mode
from nav_app.util.time import utc_now as _utc_now
from nav_app.adapters.callbacks import post_main_callback as _post_main_callback
from nav_app.services.status_helpers import robot_state_from_mission_status
from nav_app.services.capabilities import active_lift_status, profile_capabilities
from nav_app.services.localization import GLOBAL_SEARCH, LocalizationGate

def active_bridge_robot_id():
    return active_robot_profile().get("bridge_robot_id")


def aruco_detection_topic():
    profile = active_robot_profile()
    configured = os.getenv("ARUCO_DETECTION_TOPIC") or profile.get("aruco_detection_topic")
    if configured:
        return configured
    bridge_robot_id = profile.get("bridge_robot_id") or "tb3_1"
    return f"/mission/{bridge_robot_id}/aruco/detections"


def cmd_vel_subscribers():
    if not runtime.navigator:
        return []
    return runtime.navigator.cmd_vel_subscribers()


def cmd_vel_subscriber_count():
    return len(cmd_vel_subscribers())


def active_robot_online():
    if not runtime.navigator:
        return False
    if is_simulation_mode():
        return True
    if runtime.mission_manager and runtime.mission_manager.dry_run:
        return True
    return cmd_vel_subscriber_count() > 0


def command_accepting(is_emergency: bool = False):
    if not runtime.navigator:
        return False
    return bool(not is_emergency and active_robot_online() and localization_health()["localized"])


def localization_gate():
    profile = active_robot_profile()
    if runtime.localization is None or runtime.localization.profile is not profile:
        runtime.localization = LocalizationGate(profile)
    return runtime.localization


def localization_health():
    gate = localization_gate()
    if gate.state == "UNLOCALIZED":
        gate.start(None)
        if runtime.navigator and hasattr(runtime.navigator, "request_global_localization"):
            runtime.navigator.request_global_localization()
    if runtime.navigator and hasattr(runtime.navigator, "localization_observation"):
        observation = runtime.navigator.localization_observation()
        if isinstance(observation, dict):
            gate.observe(observation)
    return gate.health()


def start_localization(seed=None):
    """Start a seed attempt or fail-closed global search when no valid seed exists."""
    gate = localization_gate()
    state = gate.start(seed)
    if runtime.navigator:
        if state == GLOBAL_SEARCH and hasattr(runtime.navigator, "request_global_localization"):
            runtime.navigator.request_global_localization()
        elif state != GLOBAL_SEARCH and seed and hasattr(runtime.navigator, "set_initial_pose"):
            runtime.navigator.set_initial_pose(seed.get("pose", seed), frame_id="map")
    return gate.health()


def assert_active_bridge_robot(robot_name: str, noun: str = "요청"):
    if robot_name != active_bridge_robot_id():
        raise HTTPException(
            status_code=409,
            detail=(
                f"이 Movement API 프로세스는 {active_bridge_robot_id()}만 담당합니다. "
                f"{robot_name} {noun}은 해당 robot_name 프로세스로 보내야 합니다."
            ),
        )


def localization_reason(pose, online: bool):
    if not runtime.navigator:
        return "unknown"
    if not online:
        return "robot_offline"
    return localization_health()["reason"]


def localization_payload(robot_name: str):
    pose = runtime.navigator.get_current_pose() if runtime.navigator else None
    online = active_robot_online()
    amcl_pose_received = bool(runtime.navigator and runtime.navigator.has_amcl_pose())
    health = localization_health()
    reason = localization_reason(pose, online)
    pose_age = pose.get("age_sec") if pose else None
    return {
        "robot_name": robot_name,
        "robot_id": ACTIVE_ROBOT_ID,
        "ros_domain_id": current_ros_domain_id(),
        "map_frame": "map",
        "robot_online": online,
        "cmd_vel_topic": "/cmd_vel",
        "cmd_vel_subscribers": cmd_vel_subscriber_count(),
        "cmd_vel_subscriber_nodes": cmd_vel_subscribers(),
        "localized": health["localized"],
        **health,
        "localization_required": not (runtime.mission_manager.dry_run if runtime.mission_manager else False) and not is_simulation_mode(),
        "pose": pose,
        "pose_source": pose.get("source") if pose else None,
        "last_pose_age_sec": pose_age,
        "pose_age_sec": pose_age,
        "amcl_pose_received": amcl_pose_received,
        "initial_pose_required": not health["localized"] and online,
        "reason": reason,
        "action_required": reason != "ok",
        "reported_at": _utc_now(),
    }


def movement_robot_status_payload(robot_name=None, command_id=None, state=None):
    pose = None
    online = active_robot_online()
    if not runtime.navigator or not runtime.mission_manager:
        battery = 0.0
        state = state or "offline"
    else:
        snapshot = runtime.mission_manager.get_status_snapshot()
        battery = snapshot["battery"]
        pose = snapshot.get("pose")
        state = state or robot_state_from_mission_status(runtime.mission_manager.mission_status)
    if not online:
        state = "offline"
    health = localization_health()
    return {
        "robot_name": robot_name or active_bridge_robot_id(),
        "robot_online": online,
        "command_accepting": command_accepting(),
        "online": online,
        "cmd_vel_topic": "/cmd_vel",
        "cmd_vel_subscribers": cmd_vel_subscriber_count(),
        "cmd_vel_subscriber_nodes": cmd_vel_subscribers(),
        "state": state,
        "current_command_id": command_id,
        "battery": battery,
        "pose": pose,
        "localized": health["localized"],
        "localization": health,
        "simulation_mode": is_simulation_mode(),
        "capabilities": profile_capabilities(active_robot_profile()),
        "lift": active_lift_status(active_robot_profile()),
        "reported_at": _utc_now(),
    }


def report_movement_robot_status(robot_name: str, command_id=None, state=None):
    return _post_main_callback(
        f"/movement/robots/{robot_name}/status",
        movement_robot_status_payload(robot_name=robot_name, command_id=command_id, state=state),
    )


def movement_robot_summary():
    profile = active_robot_profile()
    command_id = None
    if runtime.mission_manager and runtime.mission_manager.mission_status in ("ACCEPTED", "RUNNING", "EMERGENCY", "CHARGING"):
        command_id = runtime.mission_manager.current_mission_id
    pose = runtime.navigator.get_current_pose() if runtime.navigator else None
    online = active_robot_online()
    state = robot_state_from_mission_status(runtime.mission_manager.mission_status) if runtime.mission_manager else "offline"
    if not online:
        state = "offline"
    health = localization_health()
    return {
        "robot_name": profile.get("bridge_robot_id"),
        "robot_id": profile.get("robot_id"),
        "online": online,
        "cmd_vel_topic": "/cmd_vel",
        "cmd_vel_subscribers": cmd_vel_subscriber_count(),
        "cmd_vel_subscriber_nodes": cmd_vel_subscribers(),
        "state": state,
        "current_command_id": command_id,
        "battery": runtime.navigator.battery_level if runtime.navigator else 0.0,
        "pose": pose,
        "localized": health["localized"],
        "localization": health,
        "simulation_mode": is_simulation_mode(),
        "reported_at": _utc_now(),
        "ros_domain_id": current_ros_domain_id(),
        "namespace": profile.get("namespace"),
        "capabilities": profile_capabilities(profile),
        "lift": active_lift_status(profile),
    }
