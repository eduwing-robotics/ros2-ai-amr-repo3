"""Movement step and command execution."""
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
)
from nav_app.services.docking import (
    execute_aruco_align_step as _execute_aruco_align_step,
    execute_dock_transfer_step as _execute_dock_transfer_step,
    execute_leave_dock_step as _execute_leave_dock_step,
    execute_slot_reverse_out_step as _execute_slot_reverse_out_step,
    rotate_to_approach_yaw_if_needed as _rotate_to_approach_yaw_if_needed,
    skip_approach_yaw_if_marker_visible as _skip_approach_yaw_if_marker_visible,
)
from nav_app.services.robot_commands import approach_yaw_for_waypoint
from nav_app.services.robot_context import (
    report_movement_robot_status as _report_movement_robot_status,
)
from nav_app.services.status_helpers import stage_for_step_action as _stage_for_step_action

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
    _report_movement_robot_status(req.robot_name, req.command_id, "busy")
    _report_command_callback(command, "RUNNING", "running")

    try:
        terminal_state = "DONE"
        terminal_message = "completed"
        post_align_done = False
        for index, step in enumerate(req.steps):
            if runtime.navigator and runtime.navigator.safety.estop and step.action != "estop":
                raise CommandAborted("estop", stage=_stage_for_step_action(step.action))
            command["current_step_index"] = index
            command["current_step_action"] = step.action
            command["stage"] = _stage_for_step_action(step.action)
            command["updated_at"] = _utc_now()
            step_dry_run = bool(step.payload.get("dry_run"))
            if is_simulation_mode():
                result = execute_simulated_step(step)
            else:
                result = execute_dry_step(step) if (step_dry_run or runtime.mission_manager.dry_run) and step.action not in ("dock_transfer", "aruco_align", "estop") else execute_real_step(step)
            if result is not True:
                detail = result
                if runtime.navigator and getattr(runtime.navigator, "last_nav_failure", None):
                    detail = runtime.navigator.last_nav_failure
                raise RuntimeError(f"step {index} {step.action} failed: {detail}")
            if step.action == "nav2_pose" and index + 1 < len(req.steps):
                next_step = req.steps[index + 1]
                if next_step.action == "aruco_align":
                    goal = step.payload.get("goal") or {}
                    if goal.get("nav_position_only"):
                        target_yaw = goal.get("yaw")
                        if target_yaw is None:
                            target_yaw = approach_yaw_for_waypoint(goal.get("waypoint"))
                        marker_id = next_step.payload.get("aruco_marker_id")
                        if next_step.payload.get("skip_approach_yaw_rotate"):
                            next_step.payload["approach_yaw_pre_rotated"] = True
                        else:
                            skip_yaw = marker_id is not None and _skip_approach_yaw_if_marker_visible(
                                int(marker_id), next_step.payload
                            )
                            if target_yaw is not None and not skip_yaw:
                                if _rotate_to_approach_yaw_if_needed(float(target_yaw), next_step.payload) is not True:
                                    raise RuntimeError("approach yaw rotate failed before aruco_align")
                                next_step.payload["approach_yaw_pre_rotated"] = True
                            elif skip_yaw:
                                next_step.payload["approach_yaw_pre_rotated"] = True
            if step.action == "nav2_pose":
                goal = step.payload.get("goal") or {}
                if goal.get("nav_position_only"):
                    command["nav_position_only_approach"] = True
            if step.action == "aruco_align":
                mode = str(step.payload.get("align_mode", "center_only")).lower()
                if mode in ("full", "precision", "full_center", "full_rotate", "full_no_forward"):
                    post_align_done = True
            requested_terminal = step.payload.get("terminal_state")
            if requested_terminal in ("ARRIVED", "DONE"):
                terminal_state = requested_terminal
                terminal_message = "arrived" if requested_terminal == "ARRIVED" else "completed"
        command["state"] = terminal_state
        command["message"] = terminal_message
        command["post_align_done"] = post_align_done
        command["updated_at"] = _utc_now()
        if terminal_state == "ARRIVED":
            _record_arrived_gate(command)
        _report_movement_result(req.command_id, req.task_id, req.robot_name, terminal_state, terminal_message)
        _report_command_callback(command, terminal_state, terminal_message)
        _report_movement_robot_status(req.robot_name, None, "idle")
    except CommandAborted as exc:
        command["state"] = "ABORTED"
        command["stage"] = exc.stage
        command["reason"] = exc.reason
        command["robot_at"] = exc.robot_at
        command["resumable"] = exc.resumable
        command["message"] = str(exc)
        command["updated_at"] = _utc_now()
        _report_movement_result(req.command_id, req.task_id, req.robot_name, "ABORTED", str(exc))
        _report_command_callback(command, "ABORTED", str(exc))
        _report_movement_robot_status(req.robot_name, None, "estop")
    except Exception as exc:
        failed_step = command.get("current_step_action")
        stage = exc.stage if isinstance(exc, StageError) else _stage_for_step_action(failed_step)
        reason = exc.reason if isinstance(exc, StageError) else str(exc)
        command["state"] = "FAILED"
        command["stage"] = stage
        command["reason"] = reason
        command["message"] = reason
        command["updated_at"] = _utc_now()
        if runtime.navigator:
            runtime.navigator.publish_stop_velocity()
        _report_movement_result(req.command_id, req.task_id, req.robot_name, "FAILED", reason)
        _report_command_callback(command, "FAILED", reason)
        _report_movement_robot_status(req.robot_name, None, "error")
    finally:
        if command.get("state") != "ARRIVED":
            _release_traffic_locks_for_command(command)
        command["updated_at"] = _utc_now()
        runtime.movement_execution_lock.release()
