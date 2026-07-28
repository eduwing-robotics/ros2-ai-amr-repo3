"""Movement step and command execution."""
import math
import time
from typing import Any, Dict, List, Optional

from nav_app.errors import CommandAborted, StageError
from nav_app.models import MovementCommandRequest, MovementStep
from nav_app.runtime import runtime
from nav_app.settings import SIMULATED_STEP_DELAY_SEC, is_simulation_mode
from nav_app.util.time import utc_now as _utc_now
from nav_app.services.command_state import (
    mark_command_aborted as _mark_command_aborted,
    record_arrived_gate as _record_arrived_gate,
    release_traffic_locks_for_command as _release_traffic_locks_for_command,
    report_command_callback as _report_command_callback,
    report_movement_result as _report_movement_result,
    persist_command as _persist_command,
)
from nav_app.services.docking import (
    execute_aruco_align_step as _execute_aruco_align_step,
    execute_dock_transfer_step as _execute_dock_transfer_step,
    execute_leave_dock_step as _execute_leave_dock_step,
    execute_lift_move_step as _execute_lift_move_step,
    execute_slot_reverse_out_step as _execute_slot_reverse_out_step,
    rotate_to_approach_yaw_if_needed as _rotate_to_approach_yaw_if_needed,
    skip_approach_yaw_if_marker_visible as _skip_approach_yaw_if_marker_visible,
)
from nav_app.services.robot_commands import approach_yaw_for_waypoint
from nav_app.services.robot_context import (
    report_movement_robot_status as _report_movement_robot_status,
)
from nav_app.services.status_helpers import stage_for_step_action as _stage_for_step_action
from nav_app.services.traffic_coordination import (
    release_held_segments as _release_held_segments,
    require_nav_handoff_after_leave_dock as _require_nav_handoff_after_leave_dock,
    segment_mode_enabled as _segment_mode_enabled,
    wait_for_departure_slot as _wait_for_departure_slot,
    wait_for_step_segments as _wait_for_step_segments,
)

def _approach_goal_for_nav_step(step: MovementStep) -> Optional[Dict[str, Any]]:
    """Return the final position-only goal that hands off to ArUco alignment."""
    if step.action == "nav2_pose":
        goal = step.payload.get("goal")
        return goal if isinstance(goal, dict) and goal.get("nav_position_only") else None
    if step.action == "nav2_waypoints":
        goals = step.payload.get("goals")
        if isinstance(goals, list) and goals:
            goal = goals[-1]
            return goal if isinstance(goal, dict) and goal.get("nav_position_only") else None
    return None


def _pre_rotate_for_aruco(step: MovementStep, next_step: MovementStep) -> None:
    """Apply the canonical approach yaw after an xy-only Nav2 arrival."""
    if next_step.action != "aruco_align":
        return
    goal = _approach_goal_for_nav_step(step)
    if goal is None:
        return
    target_yaw = goal.get("yaw")
    if target_yaw is None:
        target_yaw = approach_yaw_for_waypoint(goal.get("waypoint"))
    marker_id = next_step.payload.get("aruco_marker_id")
    if next_step.payload.get("skip_approach_yaw_rotate"):
        next_step.payload["approach_yaw_pre_rotated"] = True
        return
    skip_yaw = marker_id is not None and _skip_approach_yaw_if_marker_visible(
        int(marker_id), next_step.payload
    )
    if target_yaw is not None and not skip_yaw:
        if _rotate_to_approach_yaw_if_needed(float(target_yaw), next_step.payload) is not True:
            raise RuntimeError("approach yaw rotate failed before aruco_align")
        next_step.payload["approach_yaw_pre_rotated"] = True
    elif skip_yaw:
        next_step.payload["approach_yaw_pre_rotated"] = True


def _aruco_failure_diagnostics(command: Dict[str, Any], req: MovementCommandRequest) -> Optional[Dict[str, Any]]:
    """Capture enough state to decide whether marker_not_found is detector, pose, or FOV."""
    if not runtime.navigator:
        return None
    current_index = command.get("current_step_index")
    step = None
    if isinstance(current_index, int) and 0 <= current_index < len(req.steps):
        step = req.steps[current_index]
    if not step or step.action not in ("aruco_align", "dock_transfer"):
        return None
    payload = step.payload or {}
    target_marker = payload.get("aruco_marker_id") or payload.get("marker_id")
    detections = runtime.navigator.get_latest_aruco_detection(max_age_sec=2.0) or []
    seen_markers = []
    for detection in detections:
        if not isinstance(detection, dict):
            continue
        marker_id = detection.get("marker_id")
        if marker_id is None:
            continue
        seen_markers.append(
            {
                "marker_id": marker_id,
                "center_error_norm": detection.get("center_error_norm"),
                "marker_width_px": detection.get("marker_width_px"),
                "received_at": detection.get("received_at"),
            }
        )
    return {
        "type": "aruco_marker_not_found",
        "target_marker_id": int(target_marker) if target_marker is not None else None,
        "seen_markers": seen_markers,
        "detector_active": bool(seen_markers),
        "pose": runtime.navigator.get_current_pose(),
        "failed_step_index": current_index,
        "failed_step_action": step.action,
        "resume_hint": (
            "target marker is not in current camera FOV; verify robot pose/FOV, "
            "then retry aruco_align/dock_transfer from this approach instead of restarting full scenario"
        ),
    }

def execute_dry_step(step: MovementStep):
    delay = step.duration if step.duration is not None and step.duration > 0 else runtime.mission_manager.dry_run_step_delay_sec
    time.sleep(min(delay, 1.0))
    return True


def simulate_delay(duration=None):
    delay = SIMULATED_STEP_DELAY_SEC if duration is None else float(duration)
    time.sleep(max(0.0, min(delay, 2.0)))


def simulate_nav_goal(goal, frame_id="map"):
    if not runtime.navigator:
        raise RuntimeError("runtime.navigator is not initialized")
    x = float(goal["x"])
    y = float(goal["y"])
    yaw = float(goal.get("yaw", goal.get("theta", 0.0)) or 0.0)
    simulate_delay(goal.get("duration"))
    runtime.navigator.set_simulated_pose(x, y, yaw, frame_id=frame_id)
    return True


def execute_simulated_step(step: MovementStep):
    if step.action == "wait":
        simulate_delay(step.duration or step.payload.get("duration", SIMULATED_STEP_DELAY_SEC))
        return True
    if step.action == "nav2_pose":
        goal = step.payload.get("goal")
        if not isinstance(goal, dict):
            raise ValueError("nav2_pose step requires payload.goal")
        return simulate_nav_goal(goal, frame_id=step.payload.get("frame_id", "map"))
    if step.action == "nav2_waypoints":
        goals = step.payload.get("goals")
        if not isinstance(goals, list) or not goals:
            raise ValueError("nav2_waypoints step requires non-empty payload.goals")
        frame_id = step.payload.get("frame_id", "map")
        for goal in goals:
            if not isinstance(goal, dict):
                raise ValueError("nav2_waypoints goals must be dict objects")
            simulate_nav_goal(goal, frame_id=frame_id)
        return True
    if step.action == "dock_transfer":
        return _execute_dock_transfer_step(step)
    if step.action == "aruco_align":
        return _execute_aruco_align_step(step)
    if step.action == "leave_dock":
        simulate_delay(step.duration or step.payload.get("duration_sec", SIMULATED_STEP_DELAY_SEC))
        return True
    if step.action == "lift_move":
        simulate_delay(step.duration or step.payload.get("duration_sec", SIMULATED_STEP_DELAY_SEC))
        return True
    if step.action == "slot_reverse_out":
        simulate_delay(step.payload.get("duration_sec", SIMULATED_STEP_DELAY_SEC))
        return True
    if step.action == "manual_drive":
        simulate_delay(step.duration or step.payload.get("timeout_sec", SIMULATED_STEP_DELAY_SEC))
        return True
    if step.action == "estop":
        op = (step.command or step.payload.get("op") or "stop").strip().lower()
        if op == "stop":
            runtime.navigator.safety.enable_estop()
        elif op == "clear":
            runtime.navigator.safety.clear_estop()
        else:
            raise ValueError("estop op must be stop or clear")
        return True
    raise ValueError(f"unsupported movement step action: {step.action}")


def execute_real_step(step: MovementStep):
    if not runtime.navigator:
        raise RuntimeError("runtime.navigator is not initialized")
    if is_simulation_mode():
        return execute_simulated_step(step)

    if step.action == "wait":
        duration = float(step.duration or step.payload.get("duration", 0.0) or 0.0)
        time.sleep(max(duration, 0.0))
        return True

    if step.action == "nav2_pose":
        goal = step.payload.get("goal")
        if not isinstance(goal, dict):
            raise ValueError("nav2_pose step requires payload.goal")
        frame_id = step.payload.get("frame_id", "map")
        result = runtime.navigator.go_to_pose_goal(goal, frame_id=frame_id, label="nav2_pose")
        if result is True:
            runtime.set_standby_parked(False)
        return result

    if step.action == "nav2_waypoints":
        goals = step.payload.get("goals")
        if not isinstance(goals, list) or not goals:
            raise ValueError("nav2_waypoints step requires non-empty payload.goals")
        frame_id = step.payload.get("frame_id", "map")
        result = runtime.navigator.go_through_pose_goals(goals, frame_id=frame_id)
        if result is True:
            runtime.set_standby_parked(False)
        return result

    if step.action == "dock_transfer":
        return _execute_dock_transfer_step(step)

    if step.action == "aruco_align":
        return _execute_aruco_align_step(step)

    if step.action == "leave_dock":
        return _execute_leave_dock_step(step)

    if step.action == "lift_move":
        return _execute_lift_move_step(step)

    if step.action == "slot_reverse_out":
        return _execute_slot_reverse_out_step(step)

    if step.action == "manual_drive":
        command = (step.command or step.payload.get("command") or "stop").strip().lower()
        if command == "stop":
            return runtime.navigator.publish_stop_velocity()
        linear_x = float(step.payload.get("linear_x", 0.1))
        angular_z = float(step.payload.get("angular_z", 0.5))
        duration = float(step.duration or step.payload.get("timeout_sec", 1.0) or 1.0)
        if command == "forward":
            return runtime.navigator.publish_velocity_for_duration(linear_x=abs(linear_x), angular_z=0.0, duration_sec=duration)
        if command == "backward":
            return runtime.navigator.publish_velocity_for_duration(linear_x=-abs(linear_x), angular_z=0.0, duration_sec=duration)
        if command == "left":
            return runtime.navigator.publish_velocity_for_duration(linear_x=0.0, angular_z=abs(angular_z), duration_sec=duration)
        if command == "right":
            return runtime.navigator.publish_velocity_for_duration(linear_x=0.0, angular_z=-abs(angular_z), duration_sec=duration)
        raise ValueError(f"unsupported manual_drive command: {command}")

    if step.action == "estop":
        op = (step.command or step.payload.get("op") or "stop").strip().lower()
        if op == "stop":
            runtime.navigator.safety.enable_estop()
            runtime.navigator.nav.cancelTask()
            runtime.navigator.publish_stop_velocity()
            return True
        if op == "clear":
            runtime.navigator.safety.clear_estop()
            return True
        raise ValueError("estop op must be stop or clear")

    raise ValueError(f"unsupported movement step action: {step.action}")


def _capture_leave_dock_telemetry(command: Dict[str, Any], step: MovementStep) -> None:
    telemetry = step.payload.get("leave_dock_telemetry")
    if not isinstance(telemetry, dict):
        return
    snapshot = dict(telemetry)
    snapshot["held_traffic_segments"] = list(command.get("traffic_segments_held") or [])
    command["leave_dock_telemetry"] = snapshot
    _persist_command(command)


def execute_movement_command(req: MovementCommandRequest):
    """Movement API command를 실행하고 Main callback으로 최종 결과를 보고합니다."""
    if not runtime.mission_manager:
        return

    command = runtime.movement_commands.get(req.command_id)
    if not command:
        return

    runtime.movement_execution_lock.acquire()

    command["state"] = "RUNNING"
    command["message"] = "running"
    command["updated_at"] = _utc_now()
    _persist_command(command)
    _report_movement_robot_status(req.robot_name, req.command_id, "busy")
    _report_command_callback(command, "COMMAND_RUNNING", "running")

    try:
        terminal_state = "DONE"
        terminal_message = "completed"
        post_align_done = False
        for index, step in enumerate(req.steps):
            if command.get("safe_stop_requested"):
                raise CommandAborted("safe_stop", stage=_stage_for_step_action(step.action), resumable=True)
            if command.get("cancel_requested") or command.get("state") == "CANCELLED":
                raise CommandAborted("cancelled", stage=_stage_for_step_action(step.action))
            if runtime.navigator and runtime.navigator.safety.estop and step.action != "estop":
                raise CommandAborted("estop", stage=_stage_for_step_action(step.action))
            business_index = step.payload.get("business_step_index")
            if business_index is not None:
                command["current_step_index"] = int(business_index)
                command["current_step_code"] = step.payload.get("business_step_code")
                command["current_step_action"] = step.payload.get("business_step_action")
                if step.payload.get("business_step_start", True):
                    _report_command_callback(command, "STEP_STARTED", command["current_step_code"])
            else:
                command["current_step_index"] = index
                command["current_step_action"] = step.action
            command["stage"] = _stage_for_step_action(step.action)
            command["updated_at"] = _utc_now()
            _persist_command(command)
            if _segment_mode_enabled() and step.action == "leave_dock":
                _require_nav_handoff_after_leave_dock(req.steps, index)
            if _segment_mode_enabled() and step.action in ("leave_dock", "nav2_pose", "nav2_waypoints"):
                _wait_for_departure_slot(command, _persist_command)
            if _segment_mode_enabled() and step.action == "leave_dock" and index + 1 < len(req.steps):
                next_step = req.steps[index + 1]
                if next_step.action in ("nav2_pose", "nav2_waypoints"):
                    # Reserve the first corridor before either robot backs out.
                    _wait_for_step_segments(command, next_step, _persist_command)
            if _segment_mode_enabled() and step.action in ("nav2_pose", "nav2_waypoints"):
                _wait_for_step_segments(command, step, _persist_command)
            step_dry_run = bool(step.payload.get("dry_run"))
            if step.action == "aruco_align" and step.payload.get("metric_distance_only") and command.get("metric_approach_start_pose") is None:
                pose = runtime.navigator.get_current_pose() if runtime.navigator else None
                if pose is not None:
                    command["metric_approach_start_pose"] = {"x": float(pose["x"]), "y": float(pose["y"])}
            return_pose_key = step.payload.get("capture_return_pose_key")
            if return_pose_key:
                pose = runtime.navigator.get_current_pose() if runtime.navigator else None
                if pose is None:
                    raise RuntimeError(f"cannot capture approach pose for {return_pose_key}")
                command.setdefault("return_poses", {})[str(return_pose_key)] = {
                    "x": float(pose["x"]),
                    "y": float(pose["y"]),
                }
            use_return_pose_key = step.payload.get("use_return_pose_key")
            if use_return_pose_key:
                target = (command.get("return_poses") or {}).get(str(use_return_pose_key))
                current_pose = runtime.navigator.get_current_pose() if runtime.navigator else None
                if not target or current_pose is None:
                    raise RuntimeError(f"approach return pose unavailable for {use_return_pose_key}")
                step.payload["return_target_pose"] = dict(target)
                step.payload["metric_return_to_approach"] = True
                step.payload["reverse_distance_m"] = math.hypot(
                    float(current_pose["x"]) - float(target["x"]),
                    float(current_pose["y"]) - float(target["y"]),
                ) + float(step.payload.get("fork_insert_distance_m", 0.0))
            if is_simulation_mode():
                result = execute_simulated_step(step)
            else:
                result = execute_dry_step(step) if (step_dry_run or runtime.mission_manager.dry_run) and step.action not in ("dock_transfer", "aruco_align", "estop") else execute_real_step(step)
            if result is True and step.action == "aruco_align" and step.payload.get("metric_distance_only"):
                start_pose = command.get("metric_approach_start_pose")
                current_pose = runtime.navigator.get_current_pose() if runtime.navigator else None
                if start_pose and current_pose:
                    command["metric_approach_travel_m"] = math.hypot(
                        float(current_pose["x"]) - float(start_pose["x"]),
                        float(current_pose["y"]) - float(start_pose["y"]),
                    )
                if step.payload.get("metric_insert_distance_m") is not None:
                    command["metric_insert_distance_m"] = float(step.payload["metric_insert_distance_m"])
            if step.action == "leave_dock":
                _capture_leave_dock_telemetry(command, step)
            if result is not True:
                detail = result
                if runtime.navigator and getattr(runtime.navigator, "last_nav_failure", None):
                    detail = runtime.navigator.last_nav_failure
                raise RuntimeError(f"step {index} {step.action} failed: {detail}")
            if _segment_mode_enabled() and step.action == "dock_transfer":
                # dock_transfer returns to the captured approach pose before release.
                _release_held_segments(command)
                command["traffic_state"] = "RELEASED"
                _persist_command(command)
            if business_index is not None and step.payload.get("business_step_complete", True):
                command["last_completed_step_index"] = int(business_index)
                if command.get("current_step_code") in ("LOAD", "INBOUND_LOAD_COMPLETE"):
                    command["cargo_state"] = "LOADED"
                if command.get("current_step_code") in ("UNLOAD", "STORAGE_UNLOAD_COMPLETE"):
                    command["cargo_state"] = "EMPTY"
                    command["business_completed"] = True
                _report_command_callback(command, "STEP_COMPLETED", command["current_step_code"])
                if command.get("current_step_code") in ("UNLOAD", "STORAGE_UNLOAD_COMPLETE"):
                    _report_command_callback(command, "BUSINESS_COMPLETED", "storage unload complete")
                _persist_command(command)
            if step.action in ("nav2_pose", "nav2_waypoints") and index + 1 < len(req.steps):
                _pre_rotate_for_aruco(step, req.steps[index + 1])
            if _approach_goal_for_nav_step(step) is not None:
                command["nav_position_only_approach"] = True
            if step.action == "aruco_align":
                mode = str(step.payload.get("align_mode", "center_only")).lower()
                if mode in ("full", "precision", "full_center", "full_rotate", "full_no_forward"):
                    post_align_done = True
            requested_terminal = step.payload.get("terminal_state")
            if requested_terminal in ("ARRIVED", "DONE"):
                terminal_state = requested_terminal
                terminal_message = "arrived" if requested_terminal == "ARRIVED" else "completed"
        if command.get("safe_stop_requested"):
            raise CommandAborted("safe_stop", stage=command.get("stage"), resumable=True)
        if command.get("cancel_requested") or command.get("state") == "CANCELLED":
            return
        command["state"] = terminal_state
        command["message"] = terminal_message
        command["post_align_done"] = post_align_done
        command["updated_at"] = _utc_now()
        command["authority_owner"] = "MAIN"
        command["authority_released"] = True
        _persist_command(command)
        if terminal_state == "ARRIVED":
            _record_arrived_gate(command)
        if not command.get("scenario_contract"):
            _report_movement_result(req.command_id, req.task_id, req.robot_name, terminal_state, terminal_message)
        terminal_event = "COMMAND_DONE" if terminal_state == "DONE" else "COMMAND_ARRIVED"
        _report_command_callback(command, terminal_event, terminal_message)
        _report_movement_robot_status(req.robot_name, None, "idle")
    except CommandAborted as exc:
        if command.get("safe_stop_requested") or exc.reason == "safe_stop":
            command["state"] = "STOPPED"
            command["reason"] = "safe_stop"
            command["message"] = "safe stop confirmed"
            command["resumable"] = True
            command["authority_owner"] = "MAIN"
            command["authority_released"] = True
            command["updated_at"] = _utc_now()
            _persist_command(command)
            _report_command_callback(command, "COMMAND_STOPPED", command["message"])
            _report_movement_robot_status(req.robot_name, None, "idle")
            return
        if command.get("cancel_requested") or command.get("state") == "CANCELLED":
            command["state"] = "CANCELLED"
            command["reason"] = "cancelled"
            command["message"] = "cancelled by Main"
            command["updated_at"] = _utc_now()
            _report_movement_robot_status(req.robot_name, None, "idle")
            return
        command["state"] = "ABORTED"
        command["stage"] = exc.stage
        command["reason"] = exc.reason
        command["robot_at"] = exc.robot_at
        command["resumable"] = exc.resumable
        command["message"] = str(exc)
        command["updated_at"] = _utc_now()
        command["authority_owner"] = "MAIN"
        command["authority_released"] = True
        _persist_command(command)
        if not command.get("scenario_contract"):
            _report_movement_result(req.command_id, req.task_id, req.robot_name, "ABORTED", str(exc))
        _report_command_callback(command, "COMMAND_ABORTED", str(exc))
        _report_movement_robot_status(req.robot_name, None, "estop")
    except Exception as exc:
        if command.get("safe_stop_requested"):
            command["state"] = "STOPPED"
            command["reason"] = "safe_stop"
            command["message"] = "safe stop confirmed"
            command["resumable"] = True
            command["authority_owner"] = "MAIN"
            command["authority_released"] = True
            command["updated_at"] = _utc_now()
            _persist_command(command)
            _report_command_callback(command, "COMMAND_STOPPED", command["message"])
            _report_movement_robot_status(req.robot_name, None, "idle")
            return
        if command.get("cancel_requested") or command.get("state") == "CANCELLED":
            command["state"] = "CANCELLED"
            command["updated_at"] = _utc_now()
            _report_movement_robot_status(req.robot_name, None, "idle")
            return
        failed_step = command.get("current_step_action")
        stage = exc.stage if isinstance(exc, StageError) else _stage_for_step_action(failed_step)
        reason = exc.reason if isinstance(exc, StageError) else str(exc)
        command["state"] = "FAILED"
        command["stage"] = stage
        command["reason"] = reason
        command["message"] = reason
        if command.get("business_completed") and command.get("current_step_code") in ("PARK", "PARK_COMPLETE"):
            command["park_status"] = "PARK_FAILED"
        if stage == "aruco" and reason == "marker_not_found":
            diagnostics = _aruco_failure_diagnostics(command, req)
            if diagnostics:
                command["failure_diagnostics"] = diagnostics
                command["resumable"] = True
                command["robot_at"] = "approach"
        command["updated_at"] = _utc_now()
        command["authority_owner"] = "MAIN"
        command["authority_released"] = True
        _persist_command(command)
        if runtime.navigator:
            runtime.navigator.publish_stop_velocity()
        if not command.get("scenario_contract"):
            _report_movement_result(req.command_id, req.task_id, req.robot_name, "FAILED", reason)
        _report_command_callback(command, "COMMAND_FAILED", reason)
        _report_movement_robot_status(req.robot_name, None, "error")
    finally:
        # Stop every motion source before relinquishing traffic ownership.
        if runtime.navigator:
            runtime.navigator.publish_stop_velocity()
        _release_held_segments(command)
        if not _segment_mode_enabled() and command.get("state") != "ARRIVED":
            _release_traffic_locks_for_command(command)
        command["updated_at"] = _utc_now()
        _persist_command(command)
        runtime.movement_execution_lock.release()
