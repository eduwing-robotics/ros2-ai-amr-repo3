"""Robot connectivity and localization payload helpers."""
import os
import time
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from nav_app.config import active_robot_profile, current_ros_domain_id
from nav_app.runtime import runtime
from nav_app.settings import (
    ACTIVE_ROBOT_ID,
    BATTERY_CRITICAL_PERCENT,
    BATTERY_STALE_SEC,
    BATTERY_WARNING_PERCENT,
    is_simulation_mode,
)
from nav_app.util.time import utc_now as _utc_now
from nav_app.adapters.callbacks import post_main_callback as _post_main_callback
from nav_app.services.status_helpers import robot_state_from_mission_status

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


def hardware_topic_publishers():
    if not runtime.navigator:
        return {"odom": [], "scan": []}
    getter = getattr(runtime.navigator, "topic_publishers", None)
    if not callable(getter):
        return {"odom": [], "scan": []}
    return {"odom": getter("/odom"), "scan": getter("/scan")}


def active_robot_online():
    if not runtime.navigator:
        return False
    if is_simulation_mode():
        return True
    if runtime.mission_manager and runtime.mission_manager.dry_run:
        return True
    publishers = hardware_topic_publishers()
    return bool(publishers["odom"] and publishers["scan"])


def command_accepting(is_emergency: bool = False):
    if not runtime.navigator:
        return False
    return bool(not is_emergency and active_robot_online())


def current_battery_percent():
    """Return the latest fresh battery percentage as an integer, or None."""
    if not runtime.navigator:
        return None
    getter = getattr(runtime.navigator, "get_battery_snapshot", None)
    if not callable(getter):
        return None
    snapshot = getter() or {}
    received_monotonic = snapshot.get("battery_received_monotonic")
    if received_monotonic is None:
        return None
    try:
        age_sec = max(0.0, time.monotonic() - float(received_monotonic))
        battery = float(snapshot.get("battery"))
    except (TypeError, ValueError, OverflowError):
        return None
    if age_sec > BATTERY_STALE_SEC or not (battery == battery) or battery in (float("inf"), float("-inf")):
        return None
    return max(0, min(100, int(battery + 0.5)))


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
    if pose is None:
        return "amcl_pose_not_received"
    return "ok"


def localization_payload(robot_name: str):
    pose = runtime.navigator.get_current_pose() if runtime.navigator else None
    online = active_robot_online()
    amcl_pose_received = bool(runtime.navigator and runtime.navigator.has_amcl_pose())
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
        "hardware_topic_publishers": hardware_topic_publishers(),
        "localized": pose is not None,
        "localization_required": not (runtime.mission_manager.dry_run if runtime.mission_manager else False) and not is_simulation_mode(),
        "pose": pose,
        "pose_source": pose.get("source") if pose else None,
        "last_pose_age_sec": pose_age,
        "pose_age_sec": pose_age,
        "amcl_pose_received": amcl_pose_received,
        "initial_pose_required": pose is None and online,
        "reason": reason,
        "action_required": reason != "ok",
        "reported_at": _utc_now(),
    }


def movement_robot_status_payload(robot_name=None, command_id=None, state=None):
    pose = None
    online = active_robot_online()
    if not runtime.navigator or not runtime.mission_manager:
        battery = None
        battery_snapshot = {}
        state = state or "offline"
    else:
        snapshot = runtime.mission_manager.get_status_snapshot()
        battery = snapshot["battery"]
        getter = getattr(runtime.navigator, "get_battery_snapshot", None)
        battery_snapshot = getter() if callable(getter) else {"battery": battery}
        battery = battery_snapshot.get("battery", battery)
        pose = snapshot.get("pose")
        state = state or robot_state_from_mission_status(runtime.mission_manager.mission_status)
    received_monotonic = battery_snapshot.get("battery_received_monotonic")
    battery_age_sec = None if received_monotonic is None else max(0.0, time.monotonic() - float(received_monotonic))
    battery_stale = battery_age_sec is None or battery_age_sec > BATTERY_STALE_SEC
    if battery is None or battery_stale:
        battery_status = "unknown"
    elif battery < BATTERY_CRITICAL_PERCENT:
        battery_status = "critical"
    elif battery < BATTERY_WARNING_PERCENT:
        battery_status = "warning"
    else:
        battery_status = "normal"
    if not online:
        state = "offline"
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
        "battery": current_battery_percent(),
        "battery_voltage": battery_snapshot.get("battery_voltage"),
        "battery_status": battery_status,
        "battery_sampled_at": battery_snapshot.get("battery_sampled_at"),
        "battery_age_sec": battery_age_sec,
        "battery_stale": battery_stale,
        "pose": pose,
        "localized": pose is not None,
        "simulation_mode": is_simulation_mode(),
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
    return {
        "robot_name": profile.get("bridge_robot_id"),
        "robot_id": profile.get("robot_id"),
        "online": online,
        "cmd_vel_topic": "/cmd_vel",
        "cmd_vel_subscribers": cmd_vel_subscriber_count(),
        "cmd_vel_subscriber_nodes": cmd_vel_subscribers(),
        "state": state,
        "current_command_id": command_id,
        "battery": current_battery_percent(),
        "pose": pose,
        "localized": pose is not None,
        "simulation_mode": is_simulation_mode(),
        "reported_at": _utc_now(),
        "ros_domain_id": current_ros_domain_id(),
        "namespace": profile.get("namespace"),
    }
