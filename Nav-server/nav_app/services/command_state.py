"""Command gate, abort, and callback reporting."""
import threading
import time
from typing import Any, Dict, Optional

from fastapi import HTTPException

from nav_app.adapters.callbacks import post_json_callback as _post_json_callback
from nav_app.adapters.callbacks import post_main_callback as _post_main_callback
from nav_app.runtime import runtime
from nav_app.settings import ACTIVE_ROBOT_ID, GATE_TIMEOUT_SEC, is_simulation_mode
from nav_app.util.time import utc_now as _utc_now
from nav_app.services.robot_context import (
    movement_robot_status_payload as _movement_robot_status_payload,
    report_movement_robot_status as _report_movement_robot_status,
)
from nav_app.services.status_helpers import (
    movement_result_from_state as _movement_result_from_state,
    stage_for_step_action as _stage_for_step_action,
)

def release_traffic_locks_for_command(command: Dict[str, Any]):
    if not runtime.traffic_manager:
        return
    segments = command.get("traffic_segments") or []
    if not segments:
        return
    runtime.traffic_manager.release_many(
        segments,
        robot_id=command.get("robot_name"),
        command_id=command.get("command_id"),
        force=True,
    )


def report_movement_result(command_id: str, task_id: Optional[int], robot_name: str, state: str, message: str):
    return _post_main_callback(
        "/movement/results",
        {
            "command_id": command_id,
            "task_id": task_id,
            "robot_name": robot_name,
            "result": _movement_result_from_state(state),
            "message": message,
            "reported_at": _utc_now(),
        },
    )


def command_callback_payload(command: Dict[str, Any], event: str, message: Optional[str] = None):
    pose = runtime.navigator.get_current_pose() if runtime.navigator else None
    state = command.get("state")
    payload = {
        "event": event,
        "command_id": command.get("command_id"),
        "task_id": command.get("task_id"),
        "robot_name": command.get("robot_name"),
        "robot_id": ACTIVE_ROBOT_ID,
        "state": state,
        "result": _movement_result_from_state(state) if state in ("DONE", "ARRIVED", "FAILED", "CANCELED", "CANCELLED", "ABORTED") else None,
        "stage": command.get("stage"),
        "reason": command.get("reason"),
        "robot_at": command.get("robot_at"),
        "resumable": command.get("resumable"),
        "failure_diagnostics": command.get("failure_diagnostics"),
        "message": message if message is not None else command.get("message"),
        "current_step_index": command.get("current_step_index"),
        "current_step_action": command.get("current_step_action"),
        "route_type": command.get("route_type"),
        "item": command.get("item"),
        "waypoints": command.get("waypoints"),
        "input_mode": command.get("input_mode"),
        "pose": pose,
        "localized": pose is not None,
        "simulation_mode": is_simulation_mode(),
        "reported_at": _utc_now(),
    }
    return {key: value for key, value in payload.items() if value is not None}


def report_command_callback(command: Dict[str, Any], event: str, message: Optional[str] = None):
    callback_url = command.get("callback_url")
    if not callback_url:
        return True
    payload = command_callback_payload(command, event=event, message=message)
    return _post_json_callback(callback_url, payload, label="CommandCallback")


def mark_command_aborted(command: Dict[str, Any], reason: str, stage: str, robot_at: Optional[str] = None, resumable: bool = False, message: Optional[str] = None):
    with runtime.command_state_lock:
        if command.get("state") in ("DONE", "FAILED", "ABORTED", "CANCELED", "CANCELLED"):
            return False
        command["state"] = "ABORTED"
        command["reason"] = reason
        command["stage"] = stage
        command["message"] = message or reason
        command["robot_at"] = robot_at
        command["resumable"] = resumable
        command["updated_at"] = _utc_now()
    report_movement_result(command.get("command_id"), command.get("task_id"), command.get("robot_name"), "ABORTED", command["message"])
    report_command_callback(command, "ABORTED", command["message"])
    _report_movement_robot_status(command.get("robot_name"), None, "idle" if reason == "timeout" else "estop")
    release_traffic_locks_for_command(command)
    return True


def schedule_gate_timeout(command: Dict[str, Any], timeout_sec: float):
    if timeout_sec <= 0:
        return

    def expire_gate():
        time.sleep(timeout_sec)
        current = runtime.movement_commands.get(command.get("command_id"))
        if not current or current.get("state") != "ARRIVED":
            return
        gate = runtime.last_arrived_gate_by_robot.get(current.get("robot_name"))
        if not gate or gate.get("command_id") != current.get("command_id"):
            return
        if mark_command_aborted(current, "timeout", "gate", robot_at="approach", resumable=True, message="gate timeout waiting for dock_transfer/aruco_align"):
            runtime.last_arrived_gate_by_robot.pop(current.get("robot_name"), None)

    threading.Thread(target=expire_gate, name=f"gate-timeout-{command.get('command_id')}", daemon=True).start()


def record_arrived_gate(command: Dict[str, Any]):
    gate_timeout_sec = float(command.get("gate_timeout_sec") or GATE_TIMEOUT_SEC)
    gate = {
        "command_id": command.get("command_id"),
        "robot_name": command.get("robot_name"),
        "task_id": command.get("task_id"),
        "arrived_at": _utc_now(),
        "robot_at": "approach",
        "resumable": True,
        "gate_timeout_sec": gate_timeout_sec,
        "post_align_done": bool(command.get("post_align_done")),
        "nav_position_only": bool(command.get("nav_position_only_approach")),
        "metric_approach_travel_m": command.get("metric_approach_travel_m"),
        "metric_approach_start_pose": command.get("metric_approach_start_pose"),
    }
    runtime.last_arrived_gate_by_robot[command.get("robot_name")] = gate
    command["robot_at"] = "approach"
    command["resumable"] = True
    command["gate_timeout_sec"] = gate_timeout_sec
    schedule_gate_timeout(command, gate_timeout_sec)


def consume_arrived_gate(robot_name: str):
    gate = runtime.last_arrived_gate_by_robot.get(robot_name)
    if not gate:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "dock_transfer/aruco_align requires a prior move_to_point command that is still ARRIVED at approach",
                "required_previous_state": "ARRIVED",
                "robot_at": "approach",
            },
        )
    source = runtime.movement_commands.get(gate.get("command_id"))
    if not source or source.get("state") != "ARRIVED":
        runtime.last_arrived_gate_by_robot.pop(robot_name, None)
        raise HTTPException(
            status_code=409,
            detail={
                "message": "prior ARRIVED gate is no longer valid",
                "required_previous_state": "ARRIVED",
            },
        )
    gate = runtime.last_arrived_gate_by_robot.pop(robot_name)
    gate["traffic_segments"] = source.get("traffic_segments", [])
    return gate


def abort_active_commands_for_estop():
    aborted = []
    for command in list(runtime.movement_commands.values()):
        if command.get("state") in ("ACCEPTED", "RUNNING"):
            stage = _stage_for_step_action(command.get("current_step_action"))
            if mark_command_aborted(command, "estop", stage, robot_at=command.get("robot_at"), resumable=False, message="aborted by estop"):
                aborted.append(command.get("command_id"))
    return aborted
