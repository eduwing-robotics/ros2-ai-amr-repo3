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


def persist_command(command: Dict[str, Any]):
    if runtime.state_store:
        runtime.state_store.save_command(command)


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


def _reason_code(command: Dict[str, Any], event: str):
    if command.get("reason_code"):
        return command["reason_code"]
    if event not in ("COMMAND_FAILED", "COMMAND_ABORTED", "COMMAND_STOPPED", "COMMAND_CANCELLED"):
        return None
    if command.get("reason") == "estop":
        return "ESTOP"
    if command.get("reason") == "safe_stop":
        return "OPERATOR_REQUESTED"
    return {"nav": "NAVIGATION_FAILED", "aruco": "ALIGNMENT_FAILED", "lift": "LIFT_FAILED"}.get(command.get("stage"), "EXECUTION_FAILED")


def command_callback_payload(command: Dict[str, Any], event: str, message: Optional[str] = None):
    pose = runtime.navigator.get_current_pose() if runtime.navigator else None
    state = command.get("state")
    with runtime.command_state_lock:
        sequence = int(command.get("callback_sequence", -1)) + 1
        command["callback_sequence"] = sequence
    event_id = f"{command.get('robot_name')}:{command.get('command_id')}:{sequence}"
    payload = {
        "contract_version": command.get("contract_version"),
        "event": event,
        "command_id": command.get("command_id"),
        "task_id": command.get("task_id"),
        "execution_id": command.get("execution_id"),
        "scenario_id": command.get("scenario_id"),
        "scenario_version": command.get("scenario_version"),
        "source_command_id": command.get("source_command_id"),
        "parent_execution_id": command.get("parent_execution_id"),
        "resume_from_step_index": command.get("resume_from_step_index"),
        "robot_name": command.get("robot_name"),
        "robot_id": ACTIVE_ROBOT_ID,
        "state": state,
        "result": _movement_result_from_state(state) if state in ("DONE", "ARRIVED", "FAILED", "CANCELED", "CANCELLED", "ABORTED") else None,
        "stage": command.get("stage"),
        "reason": command.get("reason"),
        "reason_code": _reason_code(command, event),
        "robot_at": command.get("robot_at"),
        "resumable": command.get("resumable"),
        "failure_diagnostics": command.get("failure_diagnostics"),
        "message": message if message is not None else command.get("message"),
        "current_step_index": command.get("current_step_index"),
        "current_step_code": command.get("current_step_code"),
        "current_step_action": command.get("current_step_action"),
        "last_completed_step_index": command.get("last_completed_step_index"),
        "cargo_state": command.get("cargo_state"),
        "business_completed": command.get("business_completed"),
        "park_status": command.get("park_status"),
        "authority_owner": command.get("authority_owner"),
        "authority_released": command.get("authority_released"),
        "route_type": command.get("route_type"),
        "item": command.get("item"),
        "waypoints": command.get("waypoints"),
        "input_mode": command.get("input_mode"),
        "pose": pose,
        "localized": pose is not None,
        "simulation_mode": is_simulation_mode(),
        "navigator_status": ("IDLE" if state in ("DONE", "FAILED", "ABORTED", "STOPPED", "CANCELLED") and command.get("authority_released") else getattr(runtime.navigator, "status", None)) if runtime.navigator else None,
        "is_emergency": bool(runtime.navigator and runtime.navigator.safety.estop),
        "reported_at": _utc_now(),
        "event_id": event_id,
        "sequence": sequence,
    }
    terminal = event in ("COMMAND_FAILED", "COMMAND_ABORTED", "COMMAND_STOPPED", "COMMAND_CANCELLED")
    if terminal:
        required = {
            "contract_version", "event_id", "sequence", "command_id", "task_id", "robot_name", "event",
            "current_step_index", "current_step_code", "current_step_action", "last_completed_step_index",
            "cargo_state", "business_completed", "reason_code", "message", "navigator_status",
            "is_emergency", "authority_owner", "authority_released", "reported_at",
        }
        return {key: value for key, value in payload.items() if value is not None or key in required}
    return {key: value for key, value in payload.items() if value is not None}


def report_command_callback(command: Dict[str, Any], event: str, message: Optional[str] = None):
    callback_url = command.get("callback_url")
    if not callback_url:
        return True
    payload = command_callback_payload(command, event=event, message=message)
    persist_command(command)
    if runtime.state_store:
        runtime.state_store.enqueue_callback(callback_url, payload)
    delivered = _post_json_callback(
        callback_url, payload, label="CommandCallback",
        on_failure=(lambda outcome: runtime.state_store.record_callback_failure(payload["event_id"], outcome))
        if runtime.state_store else None,
    )
    if delivered and runtime.state_store:
        runtime.state_store.mark_callback_delivered(payload["event_id"])
    return delivered


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
        command["authority_owner"] = "MAIN"
        command["authority_released"] = True
        persist_command(command)
    report_movement_result(command.get("command_id"), command.get("task_id"), command.get("robot_name"), "ABORTED", command["message"])
    if reason == "estop":
        report_command_callback(command, "ESTOP_LATCHED", command["message"])
    report_command_callback(command, "COMMAND_ABORTED", command["message"])
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
        "metric_insert_distance_m": command.get("metric_insert_distance_m"),
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
