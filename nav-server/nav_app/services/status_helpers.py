"""Pure status/result mapping helpers."""
from typing import Optional

def robot_state_from_mission_status(status: str):
    mapping = {
        "IDLE": "idle",
        "ACCEPTED": "busy",
        "RUNNING": "busy",
        "SUCCEEDED": "idle",
        "FAILED": "error",
        "EMERGENCY": "estop",
        "CHARGING": "busy",
    }
    return mapping.get(status, "error")


def movement_result_from_state(state: str):
    if state in ("DONE", "ARRIVED"):
        return "DONE"
    if state in ("CANCELED", "CANCELLED"):
        return "CANCELED"
    if state == "ABORTED":
        return "ABORTED"
    return "FAILED"


def stage_for_step_action(action: Optional[str]):
    mapping = {
        "nav2_pose": "nav",
        "nav2_waypoints": "nav",
        "dock_transfer": "aruco",
        "aruco_align": "aruco",
        "leave_dock": "reverse",
        "slot_reverse_out": "reverse",
        "manual_drive": "manual",
        "estop": "estop",
        "wait": "wait",
    }
    return mapping.get(action or "", action or "unknown")


def clamp(value, low, high):
    return max(low, min(high, value))
