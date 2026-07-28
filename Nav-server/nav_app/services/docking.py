"""ArUco docking and leave-dock sequences."""
import math
import os
import shlex
import subprocess
import time
from typing import Any, Dict, Optional, Tuple

from nav_app.errors import CommandAborted, StageError
from nav_app.models import MovementStep
from nav_app.runtime import runtime
from nav_app.settings import (
    ARUCO_DETECTION_MAX_AGE_SEC,
    ARUCO_DETECTION_TIMEOUT_SEC,
    ARUCO_DOCK_ANGULAR_GAIN,
    ARUCO_APPROACH_SKIP_MAP_YAW_MARKER_ERR,
    ARUCO_DOCK_CENTER_GOOD_ENOUGH_NORM,
    ARUCO_DOCK_ALIGN_SETTLE_FRAMES,
    ARUCO_DOCK_CENTER_TOLERANCE_NORM,
    ARUCO_DOCK_MIN_ANGULAR_RAD,
    ARUCO_DOCK_CONTROL_PERIOD_SEC,
    ARUCO_DOCK_LINEAR_SPEED,
    ARUCO_DOCK_LOST_ACCEPT_WIDTH_RATIO,
    ARUCO_DOCK_LOST_GRACE_SEC,
    ARUCO_DOCK_MAX_ANGULAR_SPEED,
    ARUCO_DOCK_MIN_LINEAR_SPEED,
    ARUCO_DOCK_TARGET_DISTANCE_M,
    ARUCO_DOCK_TARGET_WIDTH_PX,
    ARUCO_DOCKING_TIMEOUT_SEC,
    ARUCO_MARKER_SEARCH_ANGULAR_SPEED,
    ARUCO_MARKER_CENTERING_ANGULAR_SPEED,
    PRE_INSERT_CENTER_CYCLES,
    PRE_INSERT_CREEP_SEC,
    PRE_INSERT_CREEP_SPEED_MPS,
    ARUCO_MARKER_SEARCH_BURST_SEC,
    ARUCO_MARKER_SEARCH_BURSTS_PER_DIR,
    ARUCO_MARKER_SEEK_MAX_ROTATION_RAD,
    ARUCO_MARKER_SEARCH_TIMEOUT_SEC,
    DOCK_REVERSE_SPEED,
    DOCK_REVERSE_EXTRA_M,
    DOCK_FORWARD_CLEARANCE_MARGIN_M,
    FORK_INSERT_DISTANCE_M,
    FORK_INSERT_ENABLED,
    FORK_INSERT_MAX_DURATION_SEC,
    FORK_INSERT_SPEED_MPS,
    NAV_APPROACH_ROTATE_MAX_SEC,
    NAV_APPROACH_ROTATE_SPEED_RAD,
    NAV_APPROACH_ROTATE_YAW_THRESHOLD_RAD,
    LEAVE_DOCK_CLEARANCE_MARGIN_M,
    LEAVE_DOCK_MAX_DURATION_SEC,
    LEAVE_DOCK_REAR_ARC_DEG,
    LEAVE_DOCK_REAR_SCAN_MAX_AGE_SEC,
    LEAVE_DOCK_REVERSE_DISTANCE_M,
    LEAVE_DOCK_REVERSE_SPEED,
    DOCK_POST_INSERT_DWELL_SEC,
    FORK_INSERT_SLIP_COMPENSATION_M,
    INSERT_VISION_STOP_ENABLED,
    INSERT_CREEP_SPEED_MPS,
    INSERT_VISION_SNAPSHOT_ENABLED,
    INSERT_VISION_SNAPSHOT_DIR,
    INSERT_STOP_WIDTH_PX,
    INSERT_EXTRA_AFTER_VISION_M,
    SIMULATED_DOCK_STAGE_DELAY_SEC,
    is_simulation_mode,
)
from nav_app.services.robot_commands import (
    apply_slot_aruco_defaults,
    apply_slot_lift_defaults,
    approach_waypoint_id_for_marker,
    fork_insert_distance_for_marker,
    goal_from_waypoint_id,
    load_waypoint_goals,
)
from nav_app.services.robot_context import aruco_detection_topic as _aruco_detection_topic
from nav_app.config import active_robot_profile
from nav_app.services.status_helpers import clamp as _clamp


def _accumulate_dock_forward_m(payload: Dict[str, Any], linear_x: float, duration_sec: float) -> None:
    """full align 등 dock 중 전진 거리를 누적해 후진 거리 계산에 반영한다."""
    if linear_x <= 0.0 or duration_sec <= 0.0:
        return
    payload["_align_forward_net_m"] = float(payload.get("_align_forward_net_m", 0.0)) + linear_x * duration_sec


def marker_close_enough(detection: Dict[str, Any], payload: Dict[str, Any]):
    target_width_px = float(payload.get("target_marker_width_px", ARUCO_DOCK_TARGET_WIDTH_PX))
    try:
        width_px = float(detection.get("marker_width_px", 0.0))
    except (TypeError, ValueError):
        width_px = 0.0
    if payload.get("close_from_marker_width_only", False):
        return width_px >= target_width_px
    target_distance_m = float(payload.get("target_distance_m", ARUCO_DOCK_TARGET_DISTANCE_M))
    estimated_distance = detection.get("estimated_distance_m")
    if estimated_distance is not None:
        try:
            distance_m = float(estimated_distance)
            if math.isfinite(distance_m) and distance_m >= 0.0:
                return distance_m <= target_distance_m
        except (TypeError, ValueError):
            pass
    if payload.get("metric_distance_only", False):
        return False
    try:
        return width_px >= target_width_px
    except (TypeError, ValueError):
        return False


def marker_near_insert_start(detection: Dict[str, Any], payload: Dict[str, Any]):
    center_tolerance = float(payload.get("center_tolerance_norm", ARUCO_DOCK_CENTER_TOLERANCE_NORM))
    try:
        if abs(float(detection.get("center_error_norm", 0.0))) > center_tolerance:
            return False
    except (TypeError, ValueError):
        return False
    target_distance_m = float(payload.get("target_distance_m", ARUCO_DOCK_TARGET_DISTANCE_M))
    estimated_distance = detection.get("estimated_distance_m")
    if estimated_distance is not None:
        try:
            return float(estimated_distance) <= target_distance_m / max(0.01, ARUCO_DOCK_LOST_ACCEPT_WIDTH_RATIO)
        except (TypeError, ValueError):
            pass
    if payload.get("metric_distance_only", False):
        return False
    target_width_px = float(payload.get("target_marker_width_px", ARUCO_DOCK_TARGET_WIDTH_PX))
    min_width_px = target_width_px * max(0.0, ARUCO_DOCK_LOST_ACCEPT_WIDTH_RATIO)
    try:
        return float(detection.get("marker_width_px", 0.0)) >= min_width_px
    except (TypeError, ValueError):
        return False


def _dock_forward_margin_m(payload: Dict[str, Any]) -> float:
    value = payload.get("dock_forward_clearance_margin_m")
    if value is not None:
        return abs(float(value))
    # 벽 슬롯 ArUco 전진: 라이다 전방 차단 완전 생략 (publish_velocity margin<0)
    if payload.get("wall_adjacent_approach") or payload.get("relax_forward_clearance"):
        return -1.0
    return DOCK_FORWARD_CLEARANCE_MARGIN_M


def _normalize_angle(delta: float) -> float:
    while delta > math.pi:
        delta -= 2.0 * math.pi
    while delta < -math.pi:
        delta += 2.0 * math.pi
    return delta


def _marker_center_error_norm(detection: Optional[Dict[str, Any]]) -> Optional[float]:
    if not detection:
        return None
    try:
        return float(detection.get("center_error_norm", 0.0))
    except (TypeError, ValueError):
        return None


def _marker_yaw_error_rad(detection: Optional[Dict[str, Any]]) -> Optional[float]:
    if not detection or detection.get("marker_yaw_error_rad") is None:
        return None
    try:
        value = _normalize_angle(float(detection["marker_yaw_error_rad"]))
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def _marker_pose_yaw_tolerance_rad(payload: Dict[str, Any]) -> float:
    if payload.get("marker_yaw_tolerance_rad") is not None:
        return abs(float(payload["marker_yaw_tolerance_rad"]))
    configured_deg = payload.get("marker_yaw_tolerance_deg")
    if configured_deg is None:
        configured_deg = active_robot_profile().get("aruco_marker_yaw_tolerance_deg", 4.0)
    return math.radians(abs(float(configured_deg)))


def _marker_pose_aligned(detection: Optional[Dict[str, Any]], payload: Dict[str, Any]) -> bool:
    """Require marker-face yaw when calibrated pose is available; preserve fallback cameras."""
    yaw_error = _marker_yaw_error_rad(detection)
    if yaw_error is None:
        return not bool(payload.get("require_marker_pose_yaw", True))
    return abs(yaw_error) <= _marker_pose_yaw_tolerance_rad(payload)


def _center_angular_sign(payload: Optional[Dict[str, Any]] = None) -> float:
    """Resolve the image-center steering sign for the active robot camera orientation."""
    payload = payload or {}
    configured = payload.get("center_angular_sign")
    if configured is None:
        configured = active_robot_profile().get("aruco_center_angular_sign", -1.0)
    return 1.0 if float(configured) >= 0.0 else -1.0


def _marker_yaw_angular_sign(payload: Optional[Dict[str, Any]] = None) -> float:
    """Resolve marker-face yaw steering sign for the active robot camera orientation."""
    payload = payload or {}
    configured = payload.get("marker_yaw_angular_sign")
    if configured is None:
        configured = active_robot_profile().get("aruco_marker_yaw_angular_sign", -1.0)
    return 1.0 if float(configured) >= 0.0 else -1.0


def _pose_aware_docking_angular_z(
    detection: Dict[str, Any], payload: Dict[str, Any], *, wall_mode: bool, max_angular: float
) -> float:
    """Blend image bearing and marker-face yaw so every zone approaches perpendicular."""
    center_error = float(detection.get("center_error_norm", 0.0))
    yaw_error = _marker_yaw_error_rad(detection)
    center_gain = float(payload.get("dock_angular_gain", ARUCO_DOCK_ANGULAR_GAIN))
    if wall_mode:
        center_gain *= 0.45
    command = _center_angular_sign(payload) * center_gain * center_error
    if yaw_error is not None and payload.get("marker_pose_yaw_enabled", True):
        yaw_gain = float(payload.get("marker_yaw_gain", 0.55))
        yaw_sign = _marker_yaw_angular_sign(payload)
        command += yaw_sign * yaw_gain * yaw_error
    return _clamp(command, -max_angular, max_angular)


def _pose_reposition_command(
    detection: Dict[str, Any],
    payload: Dict[str, Any],
    *,
    distance_m: Optional[float],
    target_distance_m: float,
    linear_speed: float,
    min_linear_speed: float,
    max_angular: float,
) -> Tuple[float, float, bool]:
    """Return a bounded robot-specific arc/yaw command from fresh marker pose."""
    profile_enabled = bool(active_robot_profile().get("aruco_pose_reposition_enabled", False))
    if not bool(payload.get("pose_reposition_enabled", profile_enabled)) or distance_m is None:
        return 0.0, 0.0, False

    center_error = float(detection.get("center_error_norm", 0.0))
    yaw_error = _marker_yaw_error_rad(detection)
    remaining_m = distance_m - target_distance_m
    min_remaining_m = max(0.0, float(payload.get("pose_reposition_min_remaining_m", 0.025)))
    center_done = abs(float(payload.get("pose_reposition_center_done_norm", 0.06)))
    center_limit = abs(float(payload.get("pose_reposition_center_limit_norm", 0.30)))
    yaw_limit = math.radians(abs(float(payload.get("pose_reposition_yaw_limit_deg", 25.0))))

    if remaining_m <= min_remaining_m or abs(center_error) > center_limit:
        return 0.0, 0.0, False

    if yaw_error is not None and abs(yaw_error) > yaw_limit:
        yaw_gain = abs(float(payload.get("pose_reposition_yaw_gain", 0.55)))
        angular = _clamp(_marker_yaw_angular_sign(payload) * yaw_gain * yaw_error, -max_angular, max_angular)
        return 0.0, _apply_angular_deadband(angular, payload), True

    if abs(center_error) > center_done:
        speed = min(linear_speed, max(min_linear_speed, float(payload.get("pose_reposition_linear_speed_mps", 0.012))))
        center_gain = abs(float(payload.get("pose_reposition_center_gain", 0.45)))
        angular = _clamp(_center_angular_sign(payload) * center_gain * center_error, -max_angular, max_angular)
        return speed, _apply_angular_deadband(angular, payload), True

    if yaw_error is not None and abs(yaw_error) > _marker_pose_yaw_tolerance_rad(payload):
        yaw_gain = abs(float(payload.get("pose_reposition_yaw_gain", 0.55)))
        angular = _clamp(_marker_yaw_angular_sign(payload) * yaw_gain * yaw_error, -max_angular, max_angular)
        return 0.0, _apply_angular_deadband(angular, payload), True

    return min(linear_speed, max(min_linear_speed, linear_speed)), 0.0, True


def _acquire_center_tolerance(payload: Dict[str, Any]) -> float:
    base = float(payload.get("center_tolerance_norm", ARUCO_DOCK_CENTER_TOLERANCE_NORM))
    if resolve_align_mode(payload) == "skip":
        relaxed = payload.get("marker_acquire_center_tolerance_norm", max(base * 2.5, 0.08))
        return float(relaxed)
    return base


def _centered_enough(error_norm: Optional[float], tolerance: float, settle_count: int, settle_need: int) -> bool:
    if error_norm is None:
        return False
    if abs(error_norm) > tolerance:
        return False
    return settle_count >= settle_need


def _center_settle_need(payload: Dict[str, Any]) -> int:
    raw = payload.get("center_settle_frames", payload.get("align_settle_frames"))
    if raw is not None:
        return max(1, int(raw))
    return max(1, int(ARUCO_DOCK_ALIGN_SETTLE_FRAMES))


def _good_enough_center_tolerance(payload: Dict[str, Any]) -> float:
    return float(
        payload.get(
            "marker_good_enough_tolerance_norm",
            payload.get("center_good_enough_norm", ARUCO_DOCK_CENTER_GOOD_ENOUGH_NORM),
        )
    )


def _good_enough_allowed(payload: Dict[str, Any]) -> bool:
    if payload.get("use_good_enough") is False:
        return False
    if payload.get("use_good_enough") is True:
        return True
    return str(payload.get("final", "")).lower() == "return_approach"


def _center_error_accepted(error_norm: Optional[float], payload: Dict[str, Any]) -> bool:
    if error_norm is None:
        return False
    tight = float(payload.get("center_tolerance_norm", ARUCO_DOCK_CENTER_TOLERANCE_NORM))
    if abs(error_norm) <= tight:
        return True
    if _good_enough_allowed(payload):
        return abs(error_norm) <= _good_enough_center_tolerance(payload)
    return False


def _marker_seek_monotonic(payload: Dict[str, Any]) -> bool:
    mode = str(payload.get("marker_seek_mode", "monotonic")).lower()
    return mode in ("monotonic", "mono", "one_way")


def _marker_seek_sweep_enabled(payload: Dict[str, Any]) -> bool:
    return str(payload.get("marker_seek_mode", "monotonic")).lower() in (
        "sweep",
        "ping_pong",
        "bidirectional",
    )


def _try_align_settled(
    error_norm: Optional[float],
    payload: Dict[str, Any],
    settle_count: int,
    settle_need: int,
) -> tuple[bool, int, str]:
    """tight 또는 good_enough 안에서 연속 settle_need 프레임이면 완료."""
    if error_norm is None:
        return False, 0, ""
    tight = float(payload.get("center_tolerance_norm", ARUCO_DOCK_CENTER_TOLERANCE_NORM))
    good = _good_enough_center_tolerance(payload)
    allow_good = _good_enough_allowed(payload)
    if abs(error_norm) <= tight:
        settle_count += 1
        if settle_count >= settle_need:
            return True, settle_count, "centered"
        return False, settle_count, ""
    if allow_good and abs(error_norm) <= good:
        settle_count += 1
        if settle_count >= settle_need:
            return True, settle_count, "good-enough"
        return False, settle_count, ""
    return False, 0, ""


def _apply_angular_deadband(angular_z: float, payload: Optional[Dict[str, Any]] = None) -> float:
    payload = payload or {}
    floor = abs(float(payload.get("dock_min_angular_rad", ARUCO_DOCK_MIN_ANGULAR_RAD)))
    if angular_z != 0.0 and abs(angular_z) < floor:
        return math.copysign(floor, angular_z)
    return angular_z


def skip_approach_yaw_if_marker_visible(marker_id: int, payload: Dict[str, Any]) -> bool:
    """마커가 이미 보이면 map yaw 회전을 건너뛴다 (ArUco center 정렬이 이어짐)."""
    if payload.get("force_approach_yaw_rotate"):
        return False
    if not runtime.navigator:
        return False
    max_age_sec = float(payload.get("marker_search_max_age_sec", ARUCO_DETECTION_MAX_AGE_SEC))
    detection = runtime.navigator.get_latest_aruco_detection(marker_id, max_age_sec=max_age_sec)
    error_norm = _marker_center_error_norm(detection)
    threshold = float(
        payload.get("skip_map_yaw_marker_err_norm", ARUCO_APPROACH_SKIP_MAP_YAW_MARKER_ERR)
    )
    if detection and error_norm is not None and abs(error_norm) <= threshold:
        print(
            f"[approach] skip map yaw — marker={marker_id} visible "
            f"(center_error_norm={error_norm:.3f} <= {threshold:.3f})"
        )
        return True
    return False


def rotate_to_approach_yaw_if_needed(target_yaw: float, payload: Optional[Dict[str, Any]] = None) -> bool:
    """Nav2 xy-only 도착 후 approach yaw로 제자리 회전(closed-loop). 미수렴 시 ArUco가 보정."""
    if not runtime.navigator:
        return True
    payload = payload or {}
    if payload.get("skip_approach_yaw_rotate"):
        return True
    threshold = float(payload.get("approach_yaw_threshold_rad", NAV_APPROACH_ROTATE_YAW_THRESHOLD_RAD))
    angular_speed = abs(float(payload.get("approach_rotate_speed_rad", NAV_APPROACH_ROTATE_SPEED_RAD)))
    max_sec = abs(float(payload.get("approach_rotate_max_sec", NAV_APPROACH_ROTATE_MAX_SEC)))
    control_period = max(0.08, float(payload.get("control_period_sec", ARUCO_DOCK_CONTROL_PERIOD_SEC)))
    deadline = time.monotonic() + max_sec
    target_yaw = float(target_yaw)

    current = runtime.navigator.get_current_pose()
    if current is None:
        return True
    current_yaw = float(current.get("yaw", current.get("theta", 0.0)))
    delta = _normalize_angle(target_yaw - current_yaw)
    if abs(delta) <= threshold:
        print(
            f"[approach] yaw already aligned: current={math.degrees(current_yaw):.1f}° "
            f"target={math.degrees(target_yaw):.1f}°"
        )
        return True
    print(
        f"[approach] rotate to approach yaw (closed-loop): current={math.degrees(current_yaw):.1f}° "
        f"target={math.degrees(target_yaw):.1f}° delta={math.degrees(delta):.1f}° max={max_sec:.1f}s"
    )
    while time.monotonic() < deadline:
        if runtime.navigator.safety.estop:
            return False
        current = runtime.navigator.get_current_pose()
        if current is None:
            break
        current_yaw = float(current.get("yaw", current.get("theta", 0.0)))
        delta = _normalize_angle(target_yaw - current_yaw)
        if abs(delta) <= threshold:
            runtime.navigator.publish_stop_velocity()
            print(f"[approach] yaw aligned: {math.degrees(current_yaw):.1f}°")
            return True
        sign = 1.0 if delta > 0.0 else -1.0
        burst = min(control_period, abs(delta) / max(angular_speed, 0.05))
        runtime.navigator.publish_velocity_for_duration(
            linear_x=0.0,
            angular_z=sign * angular_speed,
            duration_sec=burst,
        )
    runtime.navigator.publish_stop_velocity()
    current = runtime.navigator.get_current_pose()
    residual = None
    if current is not None:
        residual = math.degrees(
            abs(_normalize_angle(target_yaw - float(current.get("yaw", current.get("theta", 0.0)))))
        )
    print(
        f"[approach] yaw rotate incomplete (residual={residual}°); "
        "ArUco seek will continue centering"
    )
    return True


def execute_aruco_yaw_seek(marker_id: int, payload: Dict[str, Any]):
    """마커 미검출·큰 center 오차 시 천천히 제자리 회전하며 탐색+중앙 정렬."""
    if not runtime.navigator:
        raise RuntimeError("runtime.navigator is not initialized")

    deadline = time.monotonic() + float(
        payload.get("marker_search_timeout_sec", ARUCO_MARKER_SEARCH_TIMEOUT_SEC)
    )
    max_age_sec = float(payload.get("marker_search_max_age_sec", ARUCO_DETECTION_MAX_AGE_SEC))
    center_tolerance = float(payload.get("center_tolerance_norm", ARUCO_DOCK_CENTER_TOLERANCE_NORM))
    acquire_tolerance = float(
        payload.get(
            "marker_acquire_center_tolerance_norm",
            max(center_tolerance * 4.0, 0.12),
        )
    )
    search_speed = abs(float(payload.get("marker_search_angular_speed", ARUCO_MARKER_SEARCH_ANGULAR_SPEED)))
    centering_speed = abs(
        float(payload.get("marker_centering_angular_speed", ARUCO_MARKER_CENTERING_ANGULAR_SPEED))
    )
    angular_gain = float(payload.get("dock_angular_gain", ARUCO_DOCK_ANGULAR_GAIN))
    control_period = max(0.08, float(payload.get("control_period_sec", ARUCO_DOCK_CONTROL_PERIOD_SEC)))
    burst_sec = max(0.12, float(payload.get("marker_search_burst_sec", ARUCO_MARKER_SEARCH_BURST_SEC)))
    monotonic = _marker_seek_monotonic(payload)
    sweep_enabled = _marker_seek_sweep_enabled(payload)
    monotonic_dir = float(payload.get("marker_seek_monotonic_dir", 1.0))
    if monotonic_dir == 0.0:
        monotonic_dir = 1.0
    sweep_dir = monotonic_dir
    last_error = None
    settle_count = 0
    settle_need = _center_settle_need(payload)
    miss_streak = 0
    good_enough = _good_enough_center_tolerance(payload)
    max_seek_rad = abs(
        float(payload.get("marker_seek_max_rotation_rad", ARUCO_MARKER_SEEK_MAX_ROTATION_RAD))
    )
    seek_turned_rad = 0.0

    mode_label = "monotonic seek+center" if monotonic else "slow seek+center"
    print(
        f"[aruco_seek] marker={marker_id} {mode_label} "
        f"(tol={center_tolerance:.3f} good={good_enough:.3f} settle={settle_need} "
        f"timeout={deadline - time.monotonic():.0f}s)"
    )
    while time.monotonic() < deadline:
        if runtime.navigator.safety.estop:
            raise RuntimeError("aruco yaw seek aborted by estop")
        detection = runtime.navigator.get_latest_aruco_detection(marker_id, max_age_sec=max_age_sec)
        error_norm = _marker_center_error_norm(detection)
        if detection and error_norm is not None:
            miss_streak = 0
            done, settle_count, label = _try_align_settled(error_norm, payload, settle_count, settle_need)
            if done:
                runtime.navigator.publish_stop_velocity()
                print(f"[aruco_seek] marker={marker_id} {label} err={error_norm:.4f}")
                return detection
            if settle_count > 0:
                runtime.navigator.publish_stop_velocity()
                time.sleep(control_period)
                continue
            settle_count = 0
            speed = min(
                search_speed,
                max(centering_speed, abs(angular_gain * error_norm)),
            )
            angular_z = _apply_angular_deadband(
                _clamp(_center_angular_sign(payload) * angular_gain * error_norm, -speed, speed),
                payload,
            )
            runtime.navigator.publish_velocity_for_duration(
                linear_x=0.0,
                angular_z=angular_z,
                duration_sec=control_period,
            )
            last_error = error_norm
            continue

        miss_streak += 1
        if last_error is not None and _good_enough_allowed(payload) and abs(last_error) <= good_enough:
            runtime.navigator.publish_stop_velocity()
            time.sleep(0.08)
            continue
        if max_seek_rad > 0.0 and seek_turned_rad >= max_seek_rad:
            runtime.navigator.publish_stop_velocity()
            raise RuntimeError(
                f"ArUco marker {marker_id} not found after "
                f"{math.degrees(seek_turned_rad):.0f}° monotonic seek"
            )
        seek_dir = monotonic_dir if monotonic else sweep_dir
        runtime.navigator.publish_velocity_for_duration(
            linear_x=0.0,
            angular_z=seek_dir * centering_speed,
            duration_sec=burst_sec,
        )
        seek_turned_rad += abs(seek_dir * centering_speed * burst_sec)
        runtime.navigator.publish_stop_velocity()
        if not monotonic and sweep_enabled:
            if last_error is not None and miss_streak >= 2:
                sweep_dir = _center_angular_sign(payload) if last_error > 0.0 else -_center_angular_sign(payload)
            elif miss_streak >= 3:
                sweep_dir *= -1.0
        time.sleep(0.05)

    detection = runtime.navigator.get_latest_aruco_detection(marker_id, max_age_sec=max_age_sec)
    error_norm = _marker_center_error_norm(detection)
    if detection and error_norm is not None and abs(error_norm) <= acquire_tolerance:
        return detection
    last_err = error_norm if error_norm is not None else "n/a"
    raise RuntimeError(
        f"ArUco marker {marker_id} not acquired/centered after yaw seek; last_center_error_norm={last_err}"
    )


def execute_marker_search_rotate(marker_id: int, payload: Dict[str, Any]):
    """카메라에 마커가 안 잡히면 제자리 회전으로 탐색한다 (파렛트 도킹 전 acquire)."""
    if not runtime.navigator:
        raise RuntimeError("runtime.navigator is not initialized")

    max_age_sec = float(payload.get("marker_search_max_age_sec", ARUCO_DETECTION_MAX_AGE_SEC))
    detection = runtime.navigator.get_latest_aruco_detection(marker_id, max_age_sec=max_age_sec)
    if detection:
        return detection

    deadline = time.monotonic() + float(payload.get("marker_search_timeout_sec", ARUCO_MARKER_SEARCH_TIMEOUT_SEC))
    angular_speed = abs(float(payload.get("marker_search_angular_speed", ARUCO_MARKER_SEARCH_ANGULAR_SPEED)))
    burst_sec = max(0.1, float(payload.get("marker_search_burst_sec", ARUCO_MARKER_SEARCH_BURST_SEC)))
    bursts_per_dir = max(1, int(payload.get("marker_search_bursts_per_dir", ARUCO_MARKER_SEARCH_BURSTS_PER_DIR)))

    print(
        f"[aruco_search] marker={marker_id} rotate acquire "
        f"(±{bursts_per_dir} bursts @ {angular_speed:.2f} rad/s)"
    )
    for direction in (1.0, -1.0):
        label = "left" if direction > 0 else "right"
        for burst in range(bursts_per_dir):
            if time.monotonic() >= deadline:
                break
            if runtime.navigator.safety.estop:
                raise RuntimeError("marker search aborted by estop")
            detection = runtime.navigator.get_latest_aruco_detection(marker_id, max_age_sec=max_age_sec)
            if detection:
                runtime.navigator.publish_stop_velocity()
                print(f"[aruco_search] marker={marker_id} found during {label} scan (burst {burst + 1})")
                return detection
            runtime.navigator.publish_velocity_for_duration(
                linear_x=0.0,
                angular_z=direction * angular_speed,
                duration_sec=burst_sec,
            )
        runtime.navigator.publish_stop_velocity()
        time.sleep(0.08)

    detection = runtime.navigator.get_latest_aruco_detection(marker_id, max_age_sec=max_age_sec)
    if detection:
        return detection
    raise RuntimeError(f"ArUco marker {marker_id} not found after in-place search rotate")


def acquire_dock_marker(marker_id: int, payload: Dict[str, Any]):
    """마커 탐색+중앙 정렬. approach 정렬 직후(skip)면 느슨한 허용치·회전 seek 생략."""
    if not runtime.navigator:
        raise RuntimeError("runtime.navigator is not initialized")
    max_age_sec = float(payload.get("marker_search_max_age_sec", ARUCO_DETECTION_MAX_AGE_SEC))
    center_tolerance = _acquire_center_tolerance(payload)
    detection = runtime.navigator.get_latest_aruco_detection(marker_id, max_age_sec=max_age_sec)
    error_norm = _marker_center_error_norm(detection)
    if detection and error_norm is not None:
        if _center_error_accepted(error_norm, payload):
            print(
                f"[dock] marker={marker_id} acquired "
                f"(err={error_norm:.3f} tol={center_tolerance:.3f})"
            )
            return detection
        pending_mode = resolve_align_mode(payload)
        if pending_mode == "skip" and detection:
            print(
                f"[dock] marker={marker_id} visible (err={error_norm:.3f}) "
                f"→ align skip, defer dock_transfer"
            )
            return detection

    if resolve_align_mode(payload) == "skip" and detection:
        print(
            f"[dock_transfer] marker={marker_id} acquired (align skip, err={error_norm:.3f} "
            f"tol={center_tolerance:.3f})"
        )
        return detection

    search_enabled = payload.get("marker_search_on_miss", True)
    if isinstance(search_enabled, str):
        search_enabled = search_enabled.strip().lower() not in ("0", "false", "no", "off")
    if search_enabled:
        if detection and error_norm is not None:
            pending_mode = resolve_align_mode(payload)
            if pending_mode == "full":
                print(
                    f"[aruco_seek] marker={marker_id} visible off-center "
                    f"(err={error_norm:.3f}) → defer to full align+insert"
                )
                return detection
            print(
                f"[aruco_seek] marker={marker_id} visible off-center "
                f"(err={error_norm:.3f}) → center-only align (no sweep)"
            )
            return execute_center_align_only(
                marker_id,
                {
                    **payload,
                    "marker_seek_mode": payload.get("marker_seek_mode", "monotonic"),
                    "docking_timeout_sec": min(
                        15.0,
                        float(payload.get("docking_timeout_sec", ARUCO_DOCKING_TIMEOUT_SEC)),
                    ),
                },
            )
        print(
            f"[aruco_seek] marker={marker_id} not visible "
            f"→ {payload.get('marker_seek_mode', 'monotonic')} slow seek (timeout={payload.get('marker_search_timeout_sec', ARUCO_MARKER_SEARCH_TIMEOUT_SEC)}s)"
        )
        seek_payload = {**payload}
        seek_payload.setdefault("marker_seek_mode", "monotonic")
        if payload.get("wall_adjacent_approach"):
            seek_payload["marker_search_angular_speed"] = min(
                0.08,
                float(payload.get("marker_search_angular_speed", ARUCO_MARKER_SEARCH_ANGULAR_SPEED)),
            )
            seek_payload["marker_centering_angular_speed"] = min(
                0.08,
                float(payload.get("marker_centering_angular_speed", ARUCO_MARKER_CENTERING_ANGULAR_SPEED)),
            )
        return execute_aruco_yaw_seek(marker_id, seek_payload)

    timeout_sec = float(payload.get("aruco_timeout_sec", ARUCO_DETECTION_TIMEOUT_SEC))
    detection = runtime.navigator.wait_for_aruco_marker(
        marker_id,
        timeout_sec=timeout_sec,
        max_age_sec=max_age_sec,
    )
    if not detection:
        raise RuntimeError(
            f"ArUco marker {marker_id} not detected within {timeout_sec:.1f}s "
            f"on {_aruco_detection_topic()}"
        )
    return detection


def wait_for_dock_marker(marker_id: int, payload: Dict[str, Any]):
    if not runtime.navigator:
        raise RuntimeError("runtime.navigator is not initialized")
    timeout_sec = float(payload.get("aruco_timeout_sec", ARUCO_DETECTION_TIMEOUT_SEC))
    detection = runtime.navigator.wait_for_aruco_marker(
        marker_id,
        timeout_sec=timeout_sec,
        max_age_sec=ARUCO_DETECTION_MAX_AGE_SEC,
    )
    if not detection:
        raise RuntimeError(
            f"ArUco marker {marker_id} not detected within {timeout_sec:.1f}s "
            f"on {_aruco_detection_topic()}"
        )
    return detection


def normalize_aruco_payload(payload: Dict[str, Any]):
    """Accept LMS/operator-friendly aliases and normalize to internal field names."""
    aliases = {
        "marker_id": "aruco_marker_id",
        "target_width_px": "target_marker_width_px",
        "linear_speed": "dock_linear_speed",
        "angular_gain": "dock_angular_gain",
        "max_angular_speed": "dock_max_angular_speed",
        "timeout_sec": "docking_timeout_sec",
    }
    for source, target in aliases.items():
        if source in payload and target not in payload:
            payload[target] = payload[source]
    return payload


def resolve_align_mode(payload: Dict[str, Any], default: str = "center_only") -> str:
    """center_only: 회전만. full_center: 회전+마커 seek(전진 없음). full: 65px까지 전진. skip: 생략."""
    explicit = payload.get("align_mode", payload.get("docking_align_mode"))
    if explicit is not None:
        mode = str(explicit).strip().lower()
        if mode in ("center_only", "center"):
            return "center_only"
        if mode in ("full_center", "full_rotate", "full_no_forward"):
            return "full_center"
        if mode in ("full", "precision"):
            return "full"
        if mode == "skip":
            return "skip"
    return default


def execute_docking_align(marker_id: int, payload: Dict[str, Any]):
    mode = resolve_align_mode(payload)
    if mode == "skip":
        print(f"[dock] align skipped for marker={marker_id}")
        return None
    if mode == "center_only":
        return execute_center_align_only(marker_id, payload)
    # full / full_center: phase1 회전·중앙 맞춤 (full_center는 phase2 전진 생략)
    center_timeout = float(
        payload.get(
            "center_align_timeout_sec",
            min(25.0, float(payload.get("docking_timeout_sec", ARUCO_DOCKING_TIMEOUT_SEC)) * 0.45),
        )
    )
    center_tol = float(payload.get("center_tolerance_norm", ARUCO_DOCK_CENTER_TOLERANCE_NORM))
    detection = None
    if runtime.navigator:
        detection = runtime.navigator.get_latest_aruco_detection(
            marker_id, max_age_sec=ARUCO_DETECTION_MAX_AGE_SEC
        )
    err = _marker_center_error_norm(detection)
    if err is None or abs(err) > center_tol:
        print(
            f"[dock] full align phase1: center marker={marker_id} "
            f"(rotate only, err={err if err is not None else 'n/a'} tol={center_tol:.3f})"
        )
        phase1 = dict(payload)
        phase1["docking_timeout_sec"] = center_timeout
        detection = execute_center_align_only(marker_id, phase1)
    else:
        print(
            f"[dock] full align phase1: already centered "
            f"(err={err:.3f} tol={center_tol:.3f})"
        )
    if mode == "full_center":
        print(
            f"[dock] full_center: skip phase2 forward — fork_insert is the only insert advance"
        )
        return detection
    print(f"[dock] full align phase2: forward marker={marker_id} (keep center, then width target)")
    return execute_precision_docking(marker_id, payload)


def execute_center_align_only(marker_id: int, payload: Dict[str, Any]):
    """마커 중앙에 맞출 때까지 제자리 회전만 한다. approach 캘리브 기준과 동일."""
    if not runtime.navigator:
        raise RuntimeError("runtime.navigator is not initialized")
    deadline = time.monotonic() + float(payload.get("docking_timeout_sec", ARUCO_DOCKING_TIMEOUT_SEC))
    center_tolerance = float(payload.get("center_tolerance_norm", ARUCO_DOCK_CENTER_TOLERANCE_NORM))
    control_period = max(0.05, float(payload.get("control_period_sec", ARUCO_DOCK_CONTROL_PERIOD_SEC)))
    angular_gain = float(payload.get("dock_angular_gain", ARUCO_DOCK_ANGULAR_GAIN))
    max_angular = abs(float(payload.get("dock_max_angular_speed", ARUCO_DOCK_MAX_ANGULAR_SPEED)))
    search_speed = abs(float(payload.get("marker_search_angular_speed", ARUCO_MARKER_SEARCH_ANGULAR_SPEED)))
    centering_speed = abs(
        float(payload.get("marker_centering_angular_speed", ARUCO_MARKER_CENTERING_ANGULAR_SPEED))
    )
    burst_sec = max(0.12, float(payload.get("marker_search_burst_sec", ARUCO_MARKER_SEARCH_BURST_SEC)))
    monotonic = _marker_seek_monotonic(payload)
    monotonic_dir = float(payload.get("marker_seek_monotonic_dir", 1.0))
    if monotonic_dir == 0.0:
        monotonic_dir = 1.0
    sweep_dir = monotonic_dir
    last_detection = None
    settle_count = 0
    settle_need = _center_settle_need(payload)
    miss_streak = 0
    good_enough = _good_enough_center_tolerance(payload)

    while time.monotonic() < deadline:
        if runtime.navigator.safety.estop:
            raise RuntimeError("center align aborted by estop")
        detection = runtime.navigator.get_latest_aruco_detection(marker_id, max_age_sec=ARUCO_DETECTION_MAX_AGE_SEC)
        if not detection:
            miss_streak += 1
            last_err = _marker_center_error_norm(last_detection) if last_detection else None
            if last_err is not None and _good_enough_allowed(payload) and abs(last_err) <= good_enough:
                runtime.navigator.publish_stop_velocity()
                time.sleep(0.08)
                continue
            seek_dir = monotonic_dir if monotonic else sweep_dir
            runtime.navigator.publish_velocity_for_duration(
                linear_x=0.0,
                angular_z=seek_dir * centering_speed,
                duration_sec=burst_sec,
            )
            runtime.navigator.publish_stop_velocity()
            if not monotonic and last_detection is not None and miss_streak >= 2:
                err = _marker_center_error_norm(last_detection)
                sweep_dir = _center_angular_sign(payload) if err is not None and err > 0.0 else -_center_angular_sign(payload)
            elif not monotonic and miss_streak >= 3:
                sweep_dir *= -1.0
            time.sleep(0.05)
            continue
        miss_streak = 0
        last_detection = detection
        error_norm = float(detection.get("center_error_norm", 0.0))
        done, settle_count, label = _try_align_settled(error_norm, payload, settle_count, settle_need)
        pose_yaw_required = bool(payload.get("align_marker_pose_yaw", False))
        pose_yaw_aligned = _marker_pose_aligned(detection, payload)
        if done and (not pose_yaw_required or pose_yaw_aligned):
            runtime.navigator.publish_stop_velocity()
            if label == "good-enough":
                print(f"[center_align] marker={marker_id} good-enough err={error_norm:.4f}")
            return detection
        if settle_count > 0 and not (pose_yaw_required and not pose_yaw_aligned):
            runtime.navigator.publish_stop_velocity()
            time.sleep(control_period)
            continue
        settle_count = 0
        speed = min(max_angular, search_speed, max(centering_speed, abs(angular_gain * error_norm)))
        raw_angular = (
            _pose_aware_docking_angular_z(
                detection, payload, wall_mode=False, max_angular=speed
            )
            if pose_yaw_required
            else _clamp(_center_angular_sign(payload) * angular_gain * error_norm, -speed, speed)
        )
        angular_z = _apply_angular_deadband(raw_angular, payload)
        runtime.navigator.publish_velocity_for_duration(
            linear_x=0.0,
            angular_z=angular_z,
            duration_sec=control_period,
        )

    if last_detection is not None:
        raise RuntimeError(
            f"center align timed out for ArUco marker {marker_id}; "
            f"last center_error_norm={last_detection.get('center_error_norm')}"
        )
    raise RuntimeError(f"center align timed out for ArUco marker {marker_id}")


def _precision_dock_linear_command(
    *,
    payload: Dict[str, Any],
    straight_insert: bool,
    close_enough: bool,
    near_pose_align_zone: bool,
    abs_error: float,
    yaw_error: Optional[float],
    forward_tol: float,
    forward_yaw_tolerance: float,
    center_tolerance: float,
    coarse_center_tolerance: float,
    linear_speed: float,
    min_linear_speed: float,
) -> Tuple[float, bool]:
    """Choose forward speed and report whether far-pose arc recovery is active."""
    yaw_blocks_forward = yaw_error is not None and abs(yaw_error) > forward_yaw_tolerance
    misaligned = abs_error > forward_tol or yaw_blocks_forward

    recovery_enabled = bool(payload.get("far_pose_arc_recovery", True))
    recovery_center_limit = abs(float(payload.get("far_pose_recovery_center_norm", 0.30)))
    recovery_yaw_limit = math.radians(abs(float(payload.get("far_pose_recovery_yaw_deg", 45.0))))
    recovery_yaw_ok = yaw_error is None or abs(yaw_error) <= recovery_yaw_limit
    recovery_active = (
        recovery_enabled
        and not straight_insert
        and not close_enough
        and not near_pose_align_zone
        and misaligned
        and abs_error <= recovery_center_limit
        and recovery_yaw_ok
    )

    if recovery_active:
        recovery_speed = abs(float(payload.get("far_pose_recovery_linear_speed_mps", 0.012)))
        return min(linear_speed, max(min_linear_speed, recovery_speed)), True
    if not straight_insert and misaligned:
        return 0.0, False
    if close_enough and not straight_insert:
        return 0.0, False
    if not close_enough:
        return linear_speed, False
    if abs_error > center_tolerance:
        error_span = max(0.001, coarse_center_tolerance - center_tolerance)
        scale = 1.0 - min(1.0, max(0.0, (abs_error - center_tolerance) / error_span))
        return max(min_linear_speed, linear_speed * scale), False
    return linear_speed, False


def execute_precision_docking(marker_id: int, payload: Dict[str, Any]):
    if not runtime.navigator:
        raise RuntimeError("runtime.navigator is not initialized")
    deadline = time.monotonic() + float(payload.get("docking_timeout_sec", ARUCO_DOCKING_TIMEOUT_SEC))
    center_tolerance = float(payload.get("center_tolerance_norm", ARUCO_DOCK_CENTER_TOLERANCE_NORM))
    coarse_center_tolerance = float(payload.get("coarse_center_tolerance_norm", max(center_tolerance * 3.0, 0.30)))
    control_period = max(0.05, float(payload.get("control_period_sec", ARUCO_DOCK_CONTROL_PERIOD_SEC)))
    linear_speed = abs(float(payload.get("dock_linear_speed", ARUCO_DOCK_LINEAR_SPEED)))
    min_linear_speed = max(
        abs(float(payload.get("dock_min_linear_speed", ARUCO_DOCK_MIN_LINEAR_SPEED))),
        abs(float(payload.get("dock_hardware_min_linear_speed", 0.012))),
    )
    angular_gain = float(payload.get("dock_angular_gain", ARUCO_DOCK_ANGULAR_GAIN))
    max_angular = abs(float(payload.get("dock_max_angular_speed", ARUCO_DOCK_MAX_ANGULAR_SPEED)))
    wall_mode = bool(payload.get("wall_adjacent_approach"))
    if wall_mode:
        coarse_center_tolerance = float(
            payload.get("coarse_center_tolerance_norm", max(center_tolerance * 2.0, 0.14))
        )
        max_angular = min(max_angular, 0.08)
        print(
            f"[dock] full align wall mode marker={marker_id} "
            f"(coarse_tol={coarse_center_tolerance:.3f} max_ω={max_angular:.2f})"
        )
    lost_grace_sec = max(0.0, float(payload.get("marker_lost_grace_sec", ARUCO_DOCK_LOST_GRACE_SEC)))
    last_detection = None
    last_seen_at = None
    settle_count = 0
    settle_need = _center_settle_need(payload)
    last_progress_log = 0.0
    filtered_yaw_error = None

    while time.monotonic() < deadline:
        if runtime.navigator.safety.estop:
            raise RuntimeError("precision docking aborted by estop")
        detection = runtime.navigator.get_latest_aruco_detection(marker_id, max_age_sec=ARUCO_DETECTION_MAX_AGE_SEC)
        if not detection:
            if (
                last_detection
                and marker_near_insert_start(last_detection, payload)
                and _marker_pose_aligned(last_detection, payload)
            ):
                runtime.navigator.publish_stop_velocity()
                last_detection = dict(last_detection)
                last_detection["marker_lost_at_insert_start"] = True
                return last_detection
            if (
                wall_mode
                and last_detection
                and not marker_close_enough(last_detection, payload)
                and last_seen_at is not None
                and time.monotonic() - last_seen_at < lost_grace_sec
            ):
                last_err = abs(float(last_detection.get("center_error_norm", 1.0)))
                forward_tol = float(
                    payload.get("forward_center_tolerance_norm", coarse_center_tolerance)
                )
                if last_err <= forward_tol and _marker_pose_aligned(last_detection, payload):
                    runtime.navigator.publish_velocity_for_duration(
                        linear_x=linear_speed,
                        angular_z=0.0,
                        duration_sec=control_period,
                        forward_margin_m=_dock_forward_margin_m(payload),
                    )
                    _accumulate_dock_forward_m(payload, linear_speed, control_period)
                continue
            if last_seen_at is not None and time.monotonic() - last_seen_at >= lost_grace_sec:
                runtime.navigator.publish_stop_velocity()
                raise RuntimeError(f"ArUco marker {marker_id} lost before insert start")
            time.sleep(0.05)
            continue
        raw_yaw_error = _marker_yaw_error_rad(detection)
        if raw_yaw_error is not None:
            alpha = _clamp(float(payload.get("marker_yaw_filter_alpha", 0.35)), 0.0, 1.0)
            if filtered_yaw_error is None:
                filtered_yaw_error = raw_yaw_error
            else:
                filtered_yaw_error = _normalize_angle(
                    filtered_yaw_error + alpha * _normalize_angle(raw_yaw_error - filtered_yaw_error)
                )
            detection = dict(detection)
            detection["marker_yaw_error_raw_rad"] = raw_yaw_error
            detection["marker_yaw_error_rad"] = filtered_yaw_error
            detection["marker_yaw_error_deg"] = math.degrees(filtered_yaw_error)
        last_detection = detection
        last_seen_at = time.monotonic()
        error_norm = float(detection.get("center_error_norm", 0.0))
        if marker_close_enough(detection, payload) and (bool(payload.get("straight_insert", False)) or (abs(error_norm) <= center_tolerance and _marker_pose_aligned(detection, payload))):
            settle_count += 1
            if _centered_enough(error_norm, center_tolerance, settle_count, settle_need) and _marker_pose_aligned(detection, payload):
                runtime.navigator.publish_stop_velocity()
                return detection
            runtime.navigator.publish_stop_velocity()
            time.sleep(control_period)
            continue
        settle_count = 0

        abs_error = abs(error_norm)
        width = _marker_width_px(detection)
        target_width = float(payload.get("target_marker_width_px", ARUCO_DOCK_TARGET_WIDTH_PX))
        angular_z = 0.0
        straight_insert = bool(payload.get("straight_insert", False))
        yaw_error = _marker_yaw_error_rad(detection)
        yaw_aligned = _marker_pose_aligned(detection, payload)
        estimated_distance = detection.get("estimated_distance_m")
        try:
            distance_m = float(estimated_distance) if estimated_distance is not None else None
        except (TypeError, ValueError):
            distance_m = None
        target_distance_m = float(payload.get("target_distance_m", ARUCO_DOCK_TARGET_DISTANCE_M))
        pose_align_buffer_m = max(0.0, float(payload.get("marker_pose_align_buffer_m", 0.10)))
        near_pose_align_zone = distance_m is not None and distance_m <= target_distance_m + pose_align_buffer_m
        if not straight_insert and (abs_error > center_tolerance or not yaw_aligned):
            cap = max_angular * (0.6 if wall_mode and width < target_width * 0.85 else 1.0)
            angular_z = _apply_angular_deadband(
                _pose_aware_docking_angular_z(
                    detection, payload, wall_mode=wall_mode, max_angular=cap
                ),
                payload,
            )

        close_enough = marker_close_enough(detection, payload)
        forward_tol = float(
            payload.get("forward_center_tolerance_norm", coarse_center_tolerance)
        )
        # 중심 또는 면 yaw가 크게 틀리면 먼저 제자리 보정한다. 이후에는
        # 중심+yaw 결합 조향으로 전진해 마커 면에 수직으로 수렴한다.
        forward_yaw_deg = float(payload.get("marker_forward_yaw_tolerance_deg", 12.0))
        if near_pose_align_zone:
            forward_yaw_deg = float(payload.get("marker_near_forward_yaw_tolerance_deg", 6.0))
        forward_yaw_tolerance = math.radians(abs(forward_yaw_deg))
        command_linear, recovery_active = _precision_dock_linear_command(
            payload=payload,
            straight_insert=straight_insert,
            close_enough=close_enough,
            near_pose_align_zone=near_pose_align_zone,
            abs_error=abs_error,
            yaw_error=yaw_error,
            forward_tol=forward_tol,
            forward_yaw_tolerance=forward_yaw_tolerance,
            center_tolerance=center_tolerance,
            coarse_center_tolerance=coarse_center_tolerance,
            linear_speed=linear_speed,
            min_linear_speed=min_linear_speed,
        )

        reposition_linear, reposition_angular, reposition_active = _pose_reposition_command(
            detection,
            payload,
            distance_m=distance_m,
            target_distance_m=target_distance_m,
            linear_speed=linear_speed,
            min_linear_speed=min_linear_speed,
            max_angular=max_angular,
        )
        if reposition_active:
            command_linear = reposition_linear
            angular_z = reposition_angular
            recovery_active = True

        if command_linear > 0.0 and distance_m is not None:
            remaining_m = max(0.0, distance_m - target_distance_m)
            slowdown_span_m = max(0.01, float(payload.get("dock_slowdown_span_m", 0.12)))
            speed_scale = _clamp(remaining_m / slowdown_span_m, min_linear_speed / max(linear_speed, 1e-6), 1.0)
            command_linear = min(command_linear, max(min_linear_speed, linear_speed * speed_scale))

        ok = runtime.navigator.publish_velocity_for_duration(
            linear_x=command_linear,
            angular_z=angular_z,
            duration_sec=control_period,
            forward_margin_m=_dock_forward_margin_m(payload),
        )
        if command_linear > 0.001:
            _accumulate_dock_forward_m(payload, command_linear, control_period)
        if not ok and command_linear > 0.001:
            print(
                f"[dock] full align forward blocked (linear={command_linear:.3f} "
                f"err={error_norm:.3f} width={width:.0f}/{target_width:.0f})"
            )
        now = time.monotonic()
        if now - last_progress_log >= 2.0:
            print(
                f"[dock] full align progress marker={marker_id} "
                f"err={error_norm:.3f} yaw={math.degrees(yaw_error) if yaw_error is not None else float('nan'):.1f}deg "
                f"width={width:.0f}/{target_width:.0f} linear={command_linear:.3f} angular={angular_z:.3f} "
                f"recovery_arc={recovery_active}"
            )
            last_progress_log = now

    raise RuntimeError(f"precision docking timed out for ArUco marker {marker_id}")


def fork_insert_enabled(payload: Dict[str, Any]):
    value = payload.get("fork_insert_enabled", payload.get("insert_enabled"))
    if value is None:
        return FORK_INSERT_ENABLED
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("0", "false", "no", "off")


def insert_vision_stop_enabled(payload: Dict[str, Any]) -> bool:
    """B안: 마커 width가 insert_stop_width_px에 도달하면 insert를 정지한다."""
    value = payload.get("insert_vision_stop")
    if value is not None:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() not in ("0", "false", "no", "off")
    return INSERT_VISION_STOP_ENABLED


def insert_odom_closed_loop_enabled(payload: Dict[str, Any]) -> bool:
    """Use odom/TF distance feedback instead of speed*time for blind insert."""
    value = payload.get("insert_odom_closed_loop", payload.get("fork_insert_odom_closed_loop"))
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("0", "false", "no", "off")


def resolve_insert_stop_width_px(payload: Dict[str, Any]) -> float:
    """payload/zones insert_stop_width_px → 전역 INSERT_STOP_WIDTH_PX(135). target_marker_width_px와 분리."""
    for key in ("insert_stop_width_px", "insert_stop_marker_width_px"):
        explicit = payload.get(key)
        if explicit is not None:
            return float(explicit)
    return INSERT_STOP_WIDTH_PX


def resolve_fork_insert_distance_m(payload: Dict[str, Any]) -> float:
    """payload 명시값 → zones.json 슬롯 실측값 → env 기본값 순으로 삽입 거리를 결정한다."""
    explicit = payload.get("fork_insert_distance_m", payload.get("insert_distance_m"))
    if explicit is not None:
        return abs(float(explicit))
    marker_id = payload.get("aruco_marker_id")
    if marker_id is not None:
        calibrated = fork_insert_distance_for_marker(int(marker_id))
        if calibrated is not None:
            print(
                f"[dock_transfer] using zones fork_insert_distance_m={calibrated:.3f} "
                f"for marker={int(marker_id)}"
            )
            return calibrated
    return FORK_INSERT_DISTANCE_M


def apply_slot_fork_defaults(payload: Dict[str, Any], marker_id: int):
    """dock_transfer payload에 슬롯별 삽입/후진 여유를 zones.json에서 주입한다."""
    if "fork_insert_distance_m" not in payload and "insert_distance_m" not in payload:
        calibrated = fork_insert_distance_for_marker(marker_id)
        if calibrated is not None:
            payload["fork_insert_distance_m"] = calibrated
    # 슬롯별 후진 여유 — 입고 안쪽에서 회전하지 않도록 approach 밖으로 더 뺌
    if payload.get("reverse_extra_m") is None:
        waypoint_id = approach_waypoint_id_for_marker(marker_id)
        waypoint = load_waypoint_goals().get(waypoint_id or "") or {}
        extra = waypoint.get("reverse_extra_m")
        if extra is None:
            align = waypoint.get("aruco_align")
            if isinstance(align, dict):
                extra = align.get("reverse_extra_m")
        if extra is not None:
            try:
                payload["reverse_extra_m"] = max(0.0, float(extra))
            except (TypeError, ValueError):
                pass


def compute_fork_insert_motion(payload: Dict[str, Any]):
    """삽입 속도·시간·실제 이동거리를 계산한다. max_duration cap 후 실제 거리를 반환."""
    vision_stop = insert_vision_stop_enabled(payload) and payload.get("aruco_marker_id") is not None
    if vision_stop:
        speed = abs(
            float(
                payload.get(
                    "insert_creep_speed_mps",
                    payload.get("fork_insert_speed_mps", payload.get("insert_speed_mps", INSERT_CREEP_SPEED_MPS)),
                )
            )
        )
    else:
        speed = abs(float(payload.get("fork_insert_speed_mps", payload.get("insert_speed_mps", FORK_INSERT_SPEED_MPS))))
    if speed <= 0.0:
        raise ValueError("fork_insert_speed_mps must be greater than 0")
    duration_value = payload.get("fork_insert_duration_sec", payload.get("insert_duration_sec"))
    if duration_value is not None:
        duration = float(duration_value)
        requested_distance = speed * duration
    else:
        requested_distance = resolve_fork_insert_distance_m(payload)
        if vision_stop:
            slip = 0.0
        else:
            slip = float(payload.get("fork_insert_slip_compensation_m", FORK_INSERT_SLIP_COMPENSATION_M))
            if slip > 0.0:
                requested_distance += slip
        duration = requested_distance / speed if requested_distance > 0.0 else 0.0
    max_duration = abs(float(payload.get("fork_insert_max_duration_sec", FORK_INSERT_MAX_DURATION_SEC)))
    # 설정 거리를 다 못 가는 cap 방지: 필요 시간+여유가 기본 max보다 길면 자동 확장
    needed = duration + 1.0
    if max_duration > 0.0 and needed > max_duration:
        print(
            f"[dock_transfer] fork insert max_duration {max_duration:.1f}s → {needed:.1f}s "
            f"(requested={requested_distance:.3f}m @ {speed:.3f}m/s)"
        )
        max_duration = needed
    if max_duration > 0.0:
        duration = min(duration, max_duration)
    actual_distance = speed * duration
    if duration <= 0.0:
        raise ValueError("fork_insert_distance_m or fork_insert_duration_sec must be greater than 0")
    return speed, duration, actual_distance, requested_distance


def lift_action_enabled(payload: Dict[str, Any]) -> bool:
    lift_client = getattr(runtime, "lift_client", None)
    if lift_client and getattr(lift_client, "enabled", False):
        return True
    env_name = "LIFT_UP_COMMAND" if str(payload.get("action", "load")) == "load" else "LIFT_DOWN_COMMAND"
    return bool(os.getenv(env_name, "").strip())


def resolve_post_insert_dwell_sec(payload: Dict[str, Any]) -> float:
    """insert 후 lift 동작 시간. 리프트 미연동이면 기본 4s 대기 후 후진."""
    explicit = payload.get("post_insert_dwell_sec", payload.get("lift_dwell_sec"))
    if explicit is not None:
        return max(0.0, float(explicit))
    if lift_action_enabled(payload):
        return 0.0
    return max(0.0, float(DOCK_POST_INSERT_DWELL_SEC))


def resolve_pre_insert_settle_sec(payload: Dict[str, Any]) -> float:
    """ArUco 정렬 정지 후 바퀴·캐스터가 안정될 때까지 기다리는 시간."""
    return max(0.0, float(payload.get("pre_insert_settle_sec", 0.0)))


def _marker_width_px(detection: Optional[Dict[str, Any]]) -> float:
    if not detection:
        return 0.0
    try:
        return float(detection.get("marker_width_px", 0.0))
    except (TypeError, ValueError):
        return 0.0


def _save_insert_vision_snapshot(
    payload: Dict[str, Any],
    marker_id: int,
    detection: Optional[Dict[str, Any]],
    phase: str,
    *,
    start_width: float = 0.0,
    stop_width: Optional[float] = None,
    moved_m: float = 0.0,
    reason: str = "",
) -> Optional[str]:
    """insert vision 시작/정지 시 카메라 프레임을 worklog/insert_snapshots에 저장한다."""
    if not INSERT_VISION_SNAPSHOT_ENABLED or not runtime.navigator:
        return None
    slot = payload.get("waypoint_id") or payload.get("slot") or f"marker{marker_id}"
    ts = time.strftime("%Y%m%d_%H%M%S")
    width = _marker_width_px(detection)
    fname = f"insert_{slot}_m{marker_id}_{phase}_{ts}_w{int(width)}.jpg"
    path = INSERT_VISION_SNAPSHOT_DIR / fname
    ref_start = payload.get("insert_reference_start_width_px")
    caption = [
        f"phase={phase} reason={reason or phase}",
        f"marker={marker_id} width={width:.0f}px start={start_width:.0f}px stop_at={stop_width or 0:.0f}px",
        f"moved={moved_m:.3f}m ref_start={ref_start or '-'}",
    ]
    det = dict(detection) if detection else None
    if det is not None:
        det.setdefault("marker_id", marker_id)
    if runtime.navigator.save_camera_snapshot(str(path), detection=det, caption_lines=caption):
        paths = payload.setdefault("_insert_snapshot_paths", [])
        paths.append(str(path))
        print(f"[dock_transfer] insert snapshot saved: {path}")
        return str(path)
    print(f"[dock_transfer] insert snapshot failed: {path}")
    return None


def _require_center_before_insert(payload: Dict[str, Any]) -> bool:
    value = payload.get("require_center_before_insert", payload.get("insert_requires_center"))
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("0", "false", "no", "off")


def ensure_marker_centered_for_insert(marker_id: int, payload: Dict[str, Any]):
    """insert 직전: 마커 중앙 정렬될 때까지 회전·소폭 전후진 반복. 미정렬 시 insert 금지."""
    if not runtime.navigator:
        raise RuntimeError("runtime.navigator is not initialized")

    deadline = time.monotonic() + float(
        payload.get(
            "pre_insert_center_timeout_sec",
            payload.get("docking_timeout_sec", ARUCO_DOCKING_TIMEOUT_SEC),
        )
    )
    center_tolerance = float(payload.get("center_tolerance_norm", ARUCO_DOCK_CENTER_TOLERANCE_NORM))
    target_width = float(payload.get("target_marker_width_px", ARUCO_DOCK_TARGET_WIDTH_PX))
    max_cycles = int(payload.get("pre_insert_center_cycles", PRE_INSERT_CENTER_CYCLES))
    creep_speed = abs(float(payload.get("pre_insert_creep_speed_mps", PRE_INSERT_CREEP_SPEED_MPS)))
    creep_sec = abs(float(payload.get("pre_insert_creep_sec", PRE_INSERT_CREEP_SEC)))
    max_age_sec = float(payload.get("marker_search_max_age_sec", ARUCO_DETECTION_MAX_AGE_SEC))

    print(
        f"[dock] pre-insert centering marker={marker_id} "
        f"(tol={center_tolerance:.3f} cycles={max_cycles})"
    )
    last_error = None
    for cycle in range(max_cycles):
        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            break

        cycle_payload = {
            **payload,
            "docking_timeout_sec": max(4.0, min(remaining, 18.0)),
            "use_good_enough": False,
            "align_marker_pose_yaw": True,
            "require_marker_pose_yaw": True,
        }
        try:
            detection = execute_center_align_only(marker_id, cycle_payload)
            error_norm = _marker_center_error_norm(detection)
            if detection and error_norm is not None and abs(error_norm) <= center_tolerance and _marker_pose_aligned(detection, payload):
                runtime.navigator.publish_stop_velocity()
                print(
                    f"[dock] pre-insert centered marker={marker_id} "
                    f"err={error_norm:.4f} cycle={cycle + 1}"
                )
                return detection
        except RuntimeError:
            detection = runtime.navigator.get_latest_aruco_detection(marker_id, max_age_sec=max_age_sec)

        remaining = deadline - time.monotonic()
        if remaining <= 0.0:
            break

        detection = runtime.navigator.get_latest_aruco_detection(marker_id, max_age_sec=max_age_sec)
        error_norm = _marker_center_error_norm(detection)
        if detection and error_norm is not None and abs(error_norm) <= center_tolerance and _marker_pose_aligned(detection, payload):
            runtime.navigator.publish_stop_velocity()
            return detection

        if not detection:
            print(f"[dock] pre-insert cycle {cycle + 1}: marker lost → rotate seek")
            execute_aruco_yaw_seek(
                marker_id,
                {**payload, "marker_search_timeout_sec": min(15.0, remaining)},
            )
            continue

        last_error = error_norm
        width = _marker_width_px(detection)
        if width >= target_width * 0.92:
            print(
                f"[dock] pre-insert cycle {cycle + 1}: marker large ({width:.0f}px) "
                f"err={error_norm:.3f} → creep back + re-center"
            )
            runtime.navigator.publish_velocity_for_duration(
                linear_x=-creep_speed,
                angular_z=0.0,
                duration_sec=creep_sec,
                forward_margin_m=0.0,
            )
            payload["_pre_insert_creep_net_m"] = float(payload.get("_pre_insert_creep_net_m", 0.0)) - creep_speed * creep_sec
        elif width < target_width * 0.50 and abs(error_norm or 0.0) < 0.25:
            print(
                f"[dock] pre-insert cycle {cycle + 1}: marker small ({width:.0f}px) "
                f"err={error_norm:.3f} → creep forward + re-center"
            )
            runtime.navigator.publish_velocity_for_duration(
                linear_x=creep_speed,
                angular_z=0.0,
                duration_sec=creep_sec,
                forward_margin_m=0.0,
            )
            payload["_pre_insert_creep_net_m"] = float(payload.get("_pre_insert_creep_net_m", 0.0)) + creep_speed * creep_sec
        else:
            print(
                f"[dock] pre-insert cycle {cycle + 1}: off-center err={error_norm:.3f} "
                f"→ rotate seek"
            )
            execute_aruco_yaw_seek(
                marker_id,
                {**payload, "marker_search_timeout_sec": min(12.0, remaining)},
            )
        runtime.navigator.publish_stop_velocity()
        time.sleep(0.08)

    detection = runtime.navigator.get_latest_aruco_detection(marker_id, max_age_sec=max_age_sec)
    error_norm = _marker_center_error_norm(detection)
    if detection and error_norm is not None and abs(error_norm) <= center_tolerance and _marker_pose_aligned(detection, payload):
        runtime.navigator.publish_stop_velocity()
        return detection
    raise RuntimeError(
        f"pre-insert center failed for ArUco marker {marker_id}; "
        f"last_center_error_norm={last_error if last_error is not None else error_norm}"
    )


def execute_post_insert_dwell(payload: Dict[str, Any]):
    dwell = resolve_post_insert_dwell_sec(payload)
    if dwell <= 0.0:
        return
    print(f"[dock_transfer] post-insert dwell {dwell:.1f}s (lift disabled / test hold)")
    time.sleep(dwell)


def resolve_insert_extra_after_vision_m(payload: Dict[str, Any]) -> float:
    """픽셀 vision stop 이후 추가로 더 들어갈 거리(m). zones/payload 우선, 기본 0.11."""
    for key in ("insert_extra_after_vision_m", "insert_extra_m", "fork_insert_extra_after_vision_m"):
        if payload.get(key) is not None:
            return max(0.0, float(payload[key]))
    return max(0.0, float(INSERT_EXTRA_AFTER_VISION_M))


def execute_fork_insert(payload: Dict[str, Any]):
    if not runtime.navigator:
        raise RuntimeError("runtime.navigator is not initialized")
    if not fork_insert_enabled(payload):
        print("[dock_transfer] fork insert skipped by configuration")
        return True
    marker_value = payload.get("aruco_marker_id")
    if marker_value is not None and _require_center_before_insert(payload):
        max_cycles = int(payload.get("pre_insert_center_cycles", PRE_INSERT_CENTER_CYCLES))
        if max_cycles > 0:
            ensure_marker_centered_for_insert(int(marker_value), payload)
        else:
            print("[dock_transfer] pre-insert centering skipped (pre_insert_center_cycles=0)")
    speed, duration, actual_distance, requested_distance = compute_fork_insert_motion(payload)
    payload["_actual_insert_distance_m"] = actual_distance
    payload["_requested_insert_distance_m"] = requested_distance
    if actual_distance + 1e-6 < requested_distance:
        print(
            f"[dock_transfer] fork insert capped: requested={requested_distance:.3f}m "
            f"actual={actual_distance:.3f}m (max_duration)"
        )
    marker_id = payload.get("aruco_marker_id")
    vision_stop = insert_vision_stop_enabled(payload) and marker_id is not None
    stop_width = resolve_insert_stop_width_px(payload) if vision_stop else None
    target_width = float(payload.get("target_marker_width_px", ARUCO_DOCK_TARGET_WIDTH_PX))
    max_width = float(payload.get("fork_insert_max_marker_width_px", max(target_width * 1.65, target_width + 30.0)))
    insert_margin = float(payload.get("fork_insert_forward_margin_m", payload.get("insert_forward_margin_m", 0.0)))
    # insert는 파레트/벽으로 의도적 접근 — margin>=0 이면 전방 라이다가 추가 11cm를 거부할 수 있음.
    # 명시값이 없으면 검사 생략(음수). payload로 양수 margin을 주면 그 기준 유지.
    if (
        "fork_insert_forward_margin_m" not in payload
        and "insert_forward_margin_m" not in payload
    ):
        insert_margin = -1.0
    extra_after_vision_m = resolve_insert_extra_after_vision_m(payload) if vision_stop else 0.0
    start_width = 0.0
    if vision_stop:
        start_detection = runtime.navigator.get_latest_aruco_detection(
            int(marker_id), max_age_sec=ARUCO_DETECTION_MAX_AGE_SEC
        )
        start_width = _marker_width_px(start_detection)
        print(
            f"[dock_transfer] fork insert vision: speed={speed:.3f}m/s "
            f"cap={requested_distance:.3f}m start_width={start_width:.0f}px "
            f"stop_at={stop_width:.0f}px extra_after={extra_after_vision_m:.3f}m "
            f"safety_max={max_width:.0f}px duration_cap={duration:.2f}s"
        )
        _save_insert_vision_snapshot(
            payload,
            int(marker_id),
            start_detection,
            "start",
            start_width=start_width,
            stop_width=stop_width,
            moved_m=0.0,
            reason="insert_begin",
        )
    else:
        print(
            f"[dock_transfer] fork insert speed={speed:.3f}m/s "
            f"requested={requested_distance:.3f}m actual={actual_distance:.3f}m duration={duration:.2f}s"
        )
        if insert_odom_closed_loop_enabled(payload):
            max_duration = max(
                duration + 1.0,
                float(payload.get("fork_insert_odom_max_duration_sec", duration * 2.0 + 0.5)),
            )

            tolerance = float(payload.get("fork_insert_odom_tolerance_m", 0.003))
            print(
                f"[dock_transfer] fork insert odom closed-loop: "
                f"target={actual_distance:.3f}m tolerance={tolerance:.3f}m"
            )
            distance_drive = runtime.navigator.publish_velocity_for_distance(
                linear_x=speed,
                distance_m=actual_distance,
                rate_hz=float(payload.get("fork_insert_odom_rate_hz", 15.0)),
                forward_margin_m=insert_margin,
                max_duration_sec=max_duration,
                tolerance_m=tolerance,
                stop_condition=None,
            )
            measured = float(distance_drive.get("distance_m", 0.0) or 0.0)
            payload["_actual_insert_distance_m"] = measured
            payload["_insert_odom_feedback"] = bool(distance_drive.get("feedback"))
            payload["_insert_odom_feedback_source"] = distance_drive.get("feedback_source")
            payload["_insert_odom_reason"] = distance_drive.get("reason")
            runtime.navigator.publish_stop_velocity()
            if not distance_drive.get("ok"):
                print(
                    f"[dock_transfer] fork insert odom closed-loop failed/interrupted: "
                    f"reason={distance_drive.get('reason')} measured={measured:.3f}m "
                    f"target={actual_distance:.3f}m"
                )
                return False
            print(
                f"[dock_transfer] fork insert odom closed-loop complete: "
                f"measured={measured:.3f}m target={actual_distance:.3f}m"
            )
            return True
    result = True
    moved_duration = 0.0
    segment_sec = max(0.08, min(0.25, float(payload.get("fork_insert_segment_sec", 0.12))))
    stop_width_px = float(stop_width) if stop_width is not None else None
    vision_hit = False
    while moved_duration < duration:
        if runtime.navigator.safety.estop:
            result = False
            break
        if marker_id is not None:
            detection = runtime.navigator.get_latest_aruco_detection(
                int(marker_id), max_age_sec=ARUCO_DETECTION_MAX_AGE_SEC
            )
            width = _marker_width_px(detection)
            if detection and vision_stop and stop_width_px is not None:
                if width >= max_width:
                    print(
                        f"[dock_transfer] fork insert safety stop: "
                        f"width={width:.0f}px >= max={max_width:.0f}px"
                    )
                    _save_insert_vision_snapshot(
                        payload,
                        int(marker_id),
                        detection,
                        "stop_safety",
                        start_width=start_width,
                        stop_width=stop_width_px,
                        moved_m=speed * moved_duration,
                        reason="safety_max",
                    )
                    break
                if width >= stop_width_px:
                    print(
                        f"[dock_transfer] fork insert vision stop: "
                        f"width={width:.0f}px >= stop={stop_width_px:.0f}px "
                        f"(start={start_width:.0f}px moved={speed * moved_duration:.3f}m)"
                    )
                    _save_insert_vision_snapshot(
                        payload,
                        int(marker_id),
                        detection,
                        "stop_target",
                        start_width=start_width,
                        stop_width=stop_width_px,
                        moved_m=speed * moved_duration,
                        reason="vision_target",
                    )
                    vision_hit = True
                    break
            elif detection and not vision_stop and width >= max_width:
                print(
                    f"[dock_transfer] fork insert vision stop: "
                    f"width={width:.0f}px >= {max_width:.0f}px"
                )
                break
        step = min(segment_sec, duration - moved_duration)
        ok = runtime.navigator.publish_velocity_for_duration(
            linear_x=speed,
            angular_z=0.0,
            duration_sec=step,
            forward_margin_m=insert_margin,
        )
        if not ok:
            result = False
            break
        moved_duration += step

    # 픽셀 목표 도달 후 파레트 깊이만큼 추가 전진 (기본 11cm).
    # 이 구간은 시간 추정이 아니라 pose/odom 변화량으로 닫힌 루프 제어한다.
    measured_extra_m = 0.0
    if result and vision_hit and extra_after_vision_m > 1e-4 and not runtime.navigator.safety.estop:
        extra_duration_cap = extra_after_vision_m / max(0.01, speed) * 2.0 + 0.5

        def _insert_extra_stop_condition():
            detection = runtime.navigator.get_latest_aruco_detection(
                int(marker_id), max_age_sec=ARUCO_DETECTION_MAX_AGE_SEC
            )
            width = _marker_width_px(detection)
            if detection and width >= max_width:
                print(
                    f"[dock_transfer] fork insert extra safety stop: "
                    f"width={width:.0f}px >= max={max_width:.0f}px"
                )
                return "marker_width_safety"
            return None

        print(
            f"[dock_transfer] fork insert extra after vision: "
            f"target=+{extra_after_vision_m:.3f}m odom_closed_loop "
            f"cap={extra_duration_cap:.2f}s @ {speed:.3f}m/s"
        )
        distance_drive = runtime.navigator.publish_velocity_for_distance(
            linear_x=speed,
            distance_m=extra_after_vision_m,
            rate_hz=12.0,
            forward_margin_m=insert_margin,
            max_duration_sec=extra_duration_cap,
            tolerance_m=float(payload.get("insert_extra_tolerance_m", 0.005)),
            stop_condition=_insert_extra_stop_condition,
        )
        ok_extra = bool(distance_drive.get("ok"))
        measured_extra_m = float(distance_drive.get("distance_m", 0.0) or 0.0)
        payload["_insert_extra_after_vision_m"] = extra_after_vision_m
        payload["_insert_extra_after_vision_odom_m"] = measured_extra_m
        payload["_insert_extra_after_vision_feedback"] = bool(distance_drive.get("feedback"))
        payload["_insert_extra_after_vision_reason"] = distance_drive.get("reason")
        moved_duration += measured_extra_m / max(0.01, speed)
        if ok_extra:
            _save_insert_vision_snapshot(
                payload,
                int(marker_id),
                runtime.navigator.get_latest_aruco_detection(
                    int(marker_id), max_age_sec=ARUCO_DETECTION_MAX_AGE_SEC
                ),
                "after_extra",
                start_width=start_width,
                stop_width=stop_width_px,
                moved_m=(speed * moved_duration),
                reason=f"extra_target={extra_after_vision_m:.3f}m odom={measured_extra_m:.3f}m",
            )
        else:
            print(
                f"[dock_transfer] fork insert extra after vision failed/interrupted: "
                f"reason={distance_drive.get('reason')} odom={measured_extra_m:.3f}m "
                f"target={extra_after_vision_m:.3f}m"
            )
            result = False

    payload["_actual_insert_distance_m"] = speed * moved_duration
    runtime.navigator.publish_stop_velocity()
    return result


def execute_lift_action(action: str, level: int, payload: Dict[str, Any]):
    if payload.get("skip_lift"):
        print(f"[dock_transfer] lift {action} level={level} skipped (skip_lift=true)")
        return True
    lift_client = getattr(runtime, "lift_client", None)
    if lift_client and getattr(lift_client, "enabled", False):
        result = lift_client.execute_transfer(action, level, payload)
        print(f"[dock_transfer] lift {action} level={level} complete: {result}")
        return True

    env_name = "LIFT_UP_COMMAND" if action == "load" else "LIFT_DOWN_COMMAND"
    command = os.getenv(env_name, "").strip()
    if not command:
        print(f"[dock_transfer] lift client disabled and {env_name} not configured; lift {action} level={level} treated as external/no-op")
        return True
    completed = subprocess.run(shlex.split(command), check=False, timeout=float(os.getenv("LIFT_COMMAND_TIMEOUT_SEC", "5.0")))
    if completed.returncode != 0:
        raise RuntimeError(f"{env_name} failed with exit code {completed.returncode}")
    return True


def execute_lift_move_step(step: MovementStep):
    """Move the lift to an explicit safe height and wait for position feedback."""
    payload = step.payload
    if payload.get("skip_lift"):
        print("[lift_move] skipped (skip_lift=true)")
        return True
    if payload.get("target_height_mm") is None:
        raise ValueError("lift_move step requires payload.target_height_mm")
    lift_client = getattr(runtime, "lift_client", None)
    if not lift_client or not getattr(lift_client, "enabled", False):
        raise RuntimeError("lift_move requires an enabled lift client")
    target = float(payload["target_height_mm"])
    tolerance = float(payload.get("lift_position_tolerance_mm", lift_client.config.get("position_tolerance_mm", 2.0)))
    print(f"[lift_move] target={target:.1f}mm tolerance={tolerance:.1f}mm")
    result = lift_client.move_to_if_needed(target, timeout_sec=payload.get("lift_timeout_sec"), tolerance_mm=tolerance, force=bool(payload.get("force_move", False)))
    reported = (result or {}).get("position_mm")
    if reported is None:
        raise RuntimeError(f"lift_move target={target:.1f}mm completed without position feedback")
    if not lift_client._at_target_mm(target, tolerance):
        raise RuntimeError(f"lift_move target={target:.1f}mm reported={float(reported):.1f}mm")
    print(f"[lift_move] complete: {result}")
    return True


def execute_pre_insert_lift(action: str, level: int, payload: Dict[str, Any]):
    """insert 전 선반 높이 맞춤 (level 2 등). lift 미연동이면 skip."""
    if payload.get("skip_lift"):
        print(f"[dock_transfer] pre-insert lift skipped (skip_lift=true)")
        return
    lift_client = getattr(runtime, "lift_client", None)
    if not lift_client or not getattr(lift_client, "enabled", False):
        return
    from nav_app.services.lift_phases import resolve_pre_insert_height_mm

    target = resolve_pre_insert_height_mm(action, level, payload, lift_client.config)
    if target is None:
        print(f"[dock_transfer] pre-insert lift skipped action={action} level={level}")
        return
    before = lift_client.position_mm
    print(
        f"[dock_transfer] pre-insert lift → {target:.1f}mm action={action} level={level} "
        f"(before={before})"
    )
    result = lift_client.execute_pre_insert(action, level, payload)
    after = (result or {}).get("position_mm")
    tol = float(payload.get("lift_position_tolerance_mm", lift_client.config.get("position_tolerance_mm", 2.0)))
    if after is not None and abs(float(after) - float(target)) > tol:
        print(
            f"[dock_transfer] WARN pre-insert short: target={target:.1f}mm "
            f"reported={float(after):.1f}mm (delta={float(after) - float(target):+.1f})"
        )
    print(f"[dock_transfer] pre-insert lift complete: {result}")


def execute_carry_after_load(action: str, level: int, payload: Dict[str, Any]):
    """load 후 이동 전 carry 높이까지 올림 (level 1 → 6mm 등)."""
    if payload.get("skip_lift"):
        print("[dock_transfer] carry lift skipped (skip_lift=true)")
        return
    if str(action).lower() != "load":
        return
    lift_client = getattr(runtime, "lift_client", None)
    if not lift_client or not getattr(lift_client, "enabled", False):
        return
    from nav_app.services.lift_phases import resolve_carry_height_mm

    target = resolve_carry_height_mm(action, level, payload, lift_client.config)
    if target is None:
        return
    print(f"[dock_transfer] carry lift → {target:.1f}mm after load level={level}")
    result = lift_client.execute_carry_after_load(action, level, payload)
    print(f"[dock_transfer] carry lift complete: {result}")


def resolve_dock_reverse_distance_m(payload: Dict[str, Any]) -> float:
    """dock_transfer 후진 거리: insert 실측(또는 설정 insert 거리)만큼."""
    if payload.get("reverse_duration_sec") is not None:
        speed = abs(float(payload.get("reverse_speed", DOCK_REVERSE_SPEED)))
        return speed * float(payload["reverse_duration_sec"])
    explicit = payload.get("reverse_distance_m")
    if explicit is not None:
        return abs(float(explicit))

    insert = payload.get("_actual_insert_distance_m")
    if insert is None:
        insert = resolve_fork_insert_distance_m(payload)
        slip = float(payload.get("fork_insert_slip_compensation_m", FORK_INSERT_SLIP_COMPENSATION_M))
        if slip > 0.0:
            insert = float(insert) + slip
    base = max(0.05, abs(float(insert)))
    creep = max(0.0, float(payload.get("_pre_insert_creep_net_m", 0.0)))
    align_fwd = max(0.0, float(payload.get("_align_forward_net_m", 0.0)))
    extra = max(0.0, float(payload.get("reverse_extra_m", DOCK_REVERSE_EXTRA_M)))
    total = base + creep + align_fwd + extra
    if creep > 0.0 or align_fwd > 0.0 or extra > 0.0:
        print(
            f"[dock_transfer] reverse distance base={base:.3f}m "
            f"creep={creep:.3f} align_fwd={align_fwd:.3f} extra={extra:.3f} → {total:.3f}m"
        )
    return total


def execute_dock_reverse(payload: Dict[str, Any]):
    """Back straight to a marker-safe clearance, then hand control to Nav2."""
    if not runtime.navigator:
        raise RuntimeError("runtime.navigator is not initialized")
    configured_speed = abs(float(payload.get("reverse_speed", DOCK_REVERSE_SPEED)))
    if configured_speed <= 0.0:
        raise ValueError("reverse_speed must be greater than 0")
    speed = min(configured_speed, abs(float(payload.get("approach_reverse_speed", 0.03))))
    clearance_m = max(0.05, float(payload.get("reverse_clearance_marker_distance_m", 0.40)))
    fallback_m = max(0.05, float(payload.get("reverse_clearance_fallback_m", 0.22)))
    distance = fallback_m
    distance_source = "fallback"
    marker_id = payload.get("aruco_marker_id")
    if marker_id is not None:
        detection = runtime.navigator.get_latest_aruco_detection(
            int(marker_id), max_age_sec=float(payload.get("reverse_marker_max_age_sec", 2.0))
        )
        if detection and detection.get("estimated_distance_m") is not None:
            try:
                current_marker_distance = float(detection["estimated_distance_m"])
                if math.isfinite(current_marker_distance) and current_marker_distance >= 0.0:
                    distance = max(0.0, clearance_m - current_marker_distance)
                    distance_source = f"marker:{current_marker_distance:.3f}m->clearance:{clearance_m:.3f}m"
            except (TypeError, ValueError):
                pass
    if distance <= 0.005:
        print(f"[dock_transfer] straight clearance already satisfied ({distance_source})")
        runtime.navigator.publish_stop_velocity()
        return True
    duration = distance / speed
    print(
        f"[dock_transfer] straight clearance reverse speed={speed:.3f}m/s "
        f"distance={distance:.3f}m source={distance_source} angular_z=0"
    )
    result = runtime.navigator.publish_velocity_for_distance(
        linear_x=-speed,
        distance_m=distance,
        max_duration_sec=duration * 2.5 + 0.5,
        tolerance_m=float(payload.get("reverse_tolerance_m", 0.005)),
    )
    runtime.navigator.publish_stop_velocity()
    print(f"[dock_transfer] reverse result={result}; handoff=Nav2")
    return bool(result.get("ok"))


def execute_slot_reverse_out_step(step: MovementStep):
    """슬롯 insert 후 빠져나올 때 dock_transfer와 동일한 거리로 후진 (standby_parked 무관)."""
    payload = dict(step.payload or {})
    marker_id = payload.get("aruco_marker_id")
    if marker_id is not None:
        apply_slot_fork_defaults(payload, int(marker_id))
        apply_slot_aruco_defaults(payload, int(marker_id))
    if payload.get("reverse_distance_m") is None and payload.get("distance_m") is None:
        if payload.get("_actual_insert_distance_m") is None and marker_id is not None:
            calibrated = fork_insert_distance_for_marker(int(marker_id))
            if calibrated is not None:
                payload["_actual_insert_distance_m"] = calibrated
    distance = resolve_dock_reverse_distance_m(payload)
    print(
        f"[slot_reverse_out] insert escape reverse marker={marker_id} "
        f"distance={distance:.3f}m (standby_parked ignored)"
    )
    result = execute_dock_reverse(payload)
    runtime.set_standby_parked(False)
    return result


def hold_fork_insert_enabled(payload: Dict[str, Any]) -> bool:
    """final=hold 대기 주차 시 정렬 후 전진 삽입 여부 (기본 True)."""
    value = payload.get("fork_insert_on_hold", payload.get("park_fork_insert"))
    if value is None:
        return True
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("0", "false", "no", "off")


def resolve_leave_dock_distance_m(payload: Dict[str, Any]) -> float:
    """leave_dock 후진 거리: 명시값 → 지정 마커 40cm 이격 → 저장값 → 20cm fallback."""
    for key in ("distance_m", "reverse_distance_m"):
        if payload.get(key) is not None:
            return abs(float(payload[key]))

    marker_id = payload.get("aruco_marker_id")
    current_marker_distance = leave_dock_marker_distance_m(payload, marker_id)
    if current_marker_distance is not None:
        clearance_m = max(
            0.05, float(payload.get("reverse_clearance_marker_distance_m", 0.40))
        )
        distance = max(0.0, clearance_m - current_marker_distance)
        print(
            f"[leave_dock] marker={int(marker_id)} current={current_marker_distance:.3f}m "
            f"clearance={clearance_m:.3f}m reverse={distance:.3f}m"
        )
        return distance

    stored = runtime.get_standby_park_reverse_distance_m()
    if stored is not None and stored > 0.0:
        return stored
    fallback_m = max(0.05, float(payload.get("reverse_clearance_fallback_m", 0.20)))
    print(f"[leave_dock] marker unavailable; calibrated fallback={fallback_m:.3f}m")
    return fallback_m


def normalize_leave_dock_marker(payload: Dict[str, Any]) -> Optional[int]:
    """Use the active robot standby marker even if Main sends another robot marker."""
    profile = active_robot_profile()
    configured = profile.get("standby_aruco_marker_id")
    approach_waypoint = profile.get("standby_approach_waypoint")
    if approach_waypoint:
        payload["standby_approach_waypoint"] = str(approach_waypoint)
    requested = payload.get("aruco_marker_id")
    if configured is None:
        return int(requested) if requested is not None else None
    marker_id = int(configured)
    if requested is not None and int(requested) != marker_id:
        print(
            f"[leave_dock] marker mismatch requested={int(requested)} "
            f"active_robot_standby={marker_id}; using configured marker"
        )
    payload["aruco_marker_id"] = marker_id
    return marker_id


def leave_dock_marker_distance_m(
    payload: Dict[str, Any],
    marker_id: Optional[int],
    telemetry: Optional[Dict[str, Any]] = None,
) -> Optional[float]:
    """Return a fresh, finite standby-marker distance suitable for motion control."""
    if marker_id is None or not runtime.navigator:
        return None
    detection = runtime.navigator.get_latest_aruco_detection(
        int(marker_id), max_age_sec=float(payload.get("reverse_marker_max_age_sec", 5.0))
    )
    if not detection or detection.get("estimated_distance_m") is None:
        return None
    if telemetry is not None and detection.get("max_abs_angular_z_rps") is not None:
        try:
            telemetry["max_abs_angular_z_rps"] = abs(
                float(detection["max_abs_angular_z_rps"])
            )
        except (TypeError, ValueError):
            pass
    try:
        distance_m = float(detection["estimated_distance_m"])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(distance_m) or distance_m < 0.0:
        return None
    return distance_m


def leave_dock_marker_clearance_satisfied(payload: Dict[str, Any], marker_id: Optional[int]) -> bool:
    """Require fresh vision to prove the robot reached standby-marker clearance."""
    distance_m = leave_dock_marker_distance_m(payload, marker_id)
    if distance_m is None:
        return False
    try:
        clearance_m = max(0.05, float(payload.get("reverse_clearance_marker_distance_m", 0.40)))
    except (TypeError, ValueError):
        return False
    return distance_m >= clearance_m - 0.005


def update_leave_dock_approach_telemetry(payload: Dict[str, Any], telemetry: Dict[str, Any]) -> None:
    waypoint_id = payload.get("standby_approach_waypoint")
    if not waypoint_id:
        return
    try:
        target = goal_from_waypoint_id(str(waypoint_id))
    except Exception:
        return
    target_pose = {"x": float(target["x"]), "y": float(target["y"])}
    telemetry["approach_target_pose"] = target_pose
    current = runtime.navigator.get_current_pose() if runtime.navigator else None
    if not current:
        return
    try:
        telemetry["approach_pose_error_m"] = math.hypot(
            float(current["x"]) - target_pose["x"],
            float(current["y"]) - target_pose["y"],
        )
    except (KeyError, TypeError, ValueError):
        return


def leave_dock_motion_params(payload: Dict[str, Any]):
    speed = abs(float(payload.get("speed_mps", payload.get("reverse_speed", LEAVE_DOCK_REVERSE_SPEED))))
    if speed <= 0.0:
        raise ValueError("leave_dock speed_mps must be greater than 0")

    duration_value = payload.get("duration_sec", payload.get("reverse_duration_sec"))
    if duration_value is not None:
        duration = float(duration_value)
    else:
        distance = resolve_leave_dock_distance_m(payload)
        duration = distance / speed if distance > 0.0 else 0.0

    max_duration = abs(float(payload.get("max_duration_sec", LEAVE_DOCK_MAX_DURATION_SEC)))
    if max_duration > 0.0:
        duration = min(duration, max_duration)
    if duration <= 0.0:
        raise ValueError("leave_dock duration_sec or distance_m must be greater than 0")
    return speed, duration


def leave_dock_skip_on_rear_blocked(payload: Dict[str, Any]) -> bool:
    """뒤 막힘 시 후진 생략하고 Nav2로 진행할지 (기본 True)."""
    value = payload.get("skip_on_rear_blocked")
    if value is None:
        value = payload.get("on_rear_blocked")
        if value in ("fail", "error"):
            return False
        if value in ("skip", "noop", "continue"):
            return True
        return True
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("0", "false", "no", "off", "fail")


def execute_leave_dock_step(step: MovementStep):
    if not runtime.navigator:
        raise RuntimeError("runtime.navigator is not initialized")
    payload = step.payload
    marker_id = normalize_leave_dock_marker(payload)
    force = bool(payload.get("force", False))
    parked = runtime.get_standby_parked()

    # Runtime state can be stale after a previous leave/recovery command while the
    # robot has since been physically parked again. A fresh, close standby marker
    # is stronger evidence than the in-memory flag and must restore reverse-out.
    marker_distance = leave_dock_marker_distance_m(payload, marker_id)
    clearance_m = max(
        0.05, float(payload.get("reverse_clearance_marker_distance_m", 0.40))
    )
    telemetry = {
        "standby_marker_id": marker_id,
        "standby_approach_waypoint": payload.get("standby_approach_waypoint"),
        "start_marker_distance_m": marker_distance,
        "target_marker_distance_m": clearance_m,
    }
    payload["leave_dock_telemetry"] = telemetry
    marker_requires_reverse = (
        parked is False
        and marker_distance is not None
        and marker_distance < clearance_m - 0.005
    )
    if marker_requires_reverse:
        print(
            f"[leave_dock] stale standby_parked=False overridden by fresh "
            f"marker={int(marker_id)} distance={marker_distance:.3f}m"
        )

    # 상태 게이트: '대기 도킹이 아님(False)'을 확실히 아는 경우에만 후진을 건너뛴다.
    # None(기동 직후 등 미상)은 대기 상태일 수 있으므로 후방 안전체크를 거쳐 후진한다.
    if parked is False and not force and not marker_requires_reverse:
        print("[leave_dock] 대기-도킹 상태가 아님(standby_parked=False) → 후진 생략(no-op). "
              "강제하려면 params.force=true")
        return True

    explicit_distance = any(
        payload.get(key) is not None for key in ("distance_m", "reverse_distance_m")
    )
    if not explicit_distance and (
        marker_id is None
        or not payload.get("standby_approach_waypoint")
        or marker_distance is None
    ):
        print(
            "[leave_dock] automatic reverse refused: fresh standby marker and "
            "configured approach waypoint are required"
        )
        telemetry["reverse_stop_reason"] = "automatic_reference_unavailable"
        update_leave_dock_approach_telemetry(payload, telemetry)
        runtime.navigator.publish_stop_velocity()
        return False
    marker_controlled = not explicit_distance and marker_distance is not None
    if marker_controlled:
        requested_distance = max(0.0, clearance_m - marker_distance)
        print(
            f"[leave_dock] marker={int(marker_id)} current={marker_distance:.3f}m "
            f"clearance={clearance_m:.3f}m reverse={requested_distance:.3f}m"
        )
    else:
        requested_distance = resolve_leave_dock_distance_m(payload)
    telemetry["requested_reverse_distance_m"] = requested_distance
    if requested_distance <= 0.005:
        print("[leave_dock] marker clearance already satisfied; handoff=Nav2")
        telemetry["end_marker_distance_m"] = marker_distance
        telemetry["measured_reverse_distance_m"] = 0.0
        telemetry["reverse_stop_reason"] = "marker_clearance_already_satisfied"
        update_leave_dock_approach_telemetry(payload, telemetry)
        runtime.navigator.publish_stop_velocity()
        runtime.set_standby_parked(False)
        return True

    # Fresh marker feedback is the success criterion. Odom remains a bounded
    # overrun guard so calibration drift cannot stop the robot short at ~20 cm.
    drive_distance = requested_distance
    if marker_controlled:
        odom_guard_m = max(0.01, float(payload.get("reverse_marker_odom_guard_m", 0.05)))
        drive_distance += odom_guard_m

    speed, duration = leave_dock_motion_params({**payload, "distance_m": drive_distance})
    stored = runtime.get_standby_park_reverse_distance_m()
    if stored is not None and payload.get("distance_m") is None and payload.get("reverse_distance_m") is None:
        print(f"[leave_dock] using hold-park insert distance {stored:.3f}m for reverse")

    # 후방 라이다 클리어런스 안전체크 (params.ignore_clearance=true 로 생략 가능)
    if not bool(payload.get("ignore_clearance", False)):
        margin = abs(float(payload.get("clearance_margin_m", LEAVE_DOCK_CLEARANCE_MARGIN_M)))
        arc_deg = abs(float(payload.get("rear_arc_deg", LEAVE_DOCK_REAR_ARC_DEG)))
        rear = runtime.navigator.rear_min_range(
            half_angle_deg=arc_deg / 2.0,
            max_age_sec=LEAVE_DOCK_REAR_SCAN_MAX_AGE_SEC,
        )
        telemetry["rear_clearance_m"] = rear
        if rear is None:
            print("[leave_dock] /scan 후방 데이터 없음 → 클리어런스 체크 생략하고 진행")
        else:
            allowed = rear - margin
            if allowed <= 0.02:
                if leave_dock_skip_on_rear_blocked(payload) and not force:
                    print(
                        f"[leave_dock] rear_blocked rear={rear:.2f}m margin={margin:.2f}m "
                        f"→ 후진 생략(no-op), 다음 move_to_point로 진행"
                    )
                    runtime.set_standby_parked(False)
                    return True
                raise StageError(
                    "leave_dock",
                    f"rear_blocked rear={rear:.2f}m margin={margin:.2f}m; "
                    f"뒤 공간 부족으로 후진 중단",
                )
            if allowed < drive_distance:
                drive_distance = allowed
                duration = allowed / speed
                print(f"[leave_dock] 후방 여유 {rear:.2f}m → 후진거리 {allowed:.2f}m 로 제한")

    def _marker_clearance_stop():
        if leave_dock_marker_clearance_satisfied(payload, marker_id):
            return "marker_clearance"
        return None

    print(
        f"[leave_dock] reversing out speed={speed:.3f}m/s target={requested_distance:.3f}m "
        f"odom_cap={drive_distance:.3f}m marker_controlled={marker_controlled} "
        f"(parked={parked}, force={force})"
    )
    # 대기 슬롯을 벗어날 때는 현재 자세 그대로 직선 후진한다. 지도상의 approach
    # 좌표는 Nav2가 이어서 처리하며, 여기서 횡오차를 실패로 판정하지 않는다.
    distance_drive = runtime.navigator.publish_velocity_for_distance(
        linear_x=-speed, distance_m=drive_distance, max_duration_sec=duration * 2.0 + 0.5,
        tolerance_m=float(payload.get("reverse_tolerance_m", 0.005)),
        stop_condition=_marker_clearance_stop if marker_controlled else None,
    )
    runtime.navigator.publish_stop_velocity()
    print(f"[leave_dock] reverse result={distance_drive}; handoff=Nav2")
    end_marker_distance = leave_dock_marker_distance_m(
        payload, marker_id, telemetry=telemetry
    )
    telemetry.update(
        end_marker_distance_m=end_marker_distance,
        measured_reverse_distance_m=float(distance_drive.get("distance_m", 0.0) or 0.0),
        feedback_source=distance_drive.get("feedback_source"),
        reverse_stop_reason=distance_drive.get("reason"),
    )
    update_leave_dock_approach_telemetry(payload, telemetry)
    if marker_controlled:
        succeeded = (
            end_marker_distance is not None
            and end_marker_distance >= clearance_m - 0.005
        )
    else:
        succeeded = bool(distance_drive.get("ok"))
    if marker_controlled and succeeded and not distance_drive.get("ok"):
        print(
            f"[leave_dock] odom result={distance_drive.get('reason', 'unknown')} but fresh "
            f"marker={marker_id} proves clearance; treating reverse as complete"
        )
    elif marker_controlled and not succeeded:
        print(
            f"[leave_dock] reverse stopped reason={distance_drive.get('reason', 'unknown')} but "
            f"fresh marker={marker_id} has not proved {clearance_m:.3f}m clearance"
        )
    if succeeded:
        runtime.set_standby_parked(False)
    return succeeded


def raise_if_estop(stage: str):
    if runtime.navigator and runtime.navigator.safety.estop:
        raise CommandAborted("estop", stage=stage)


def execute_aruco_align_step(step: MovementStep):
    payload = step.payload
    normalize_aruco_payload(payload)
    if "aruco_marker_id" not in payload:
        raise ValueError("aruco_align step requires payload.aruco_marker_id")
    marker_id = int(payload["aruco_marker_id"])
    final = str(payload.get("final", "hold"))
    if final == "park":
        final = "hold"
    if final not in ("hold", "return_approach"):
        raise ValueError("aruco_align final must be hold or return_approach")
    tolerance = payload.get("tolerance")
    if isinstance(tolerance, dict):
        if "yaw_deg" in tolerance:
            payload.setdefault("center_tolerance_norm", max(0.005, float(tolerance["yaw_deg"]) / 30.0))
        if "xy_m" in tolerance:
            payload.setdefault("target_distance_m", max(0.01, float(tolerance["xy_m"])))

    if payload.get("dry_run") or is_simulation_mode() or (runtime.mission_manager and runtime.mission_manager.dry_run):
        stages = ["aruco", "align"]
        if final == "hold" and hold_fork_insert_enabled(payload):
            stages.append("insert")
        for stage in stages:
            raise_if_estop(stage)
            print(f"[simulation] aruco_align stage={stage} marker={marker_id} final={final}")
            time.sleep(max(0.0, min(SIMULATED_DOCK_STAGE_DELAY_SEC, 2.0)))
        if final == "hold":
            runtime.set_standby_parked(True)
        return True

    try:
        from nav_app.services.robot_commands import (
            align_mode_for_approach_waypoint,
            align_mode_for_hold_park,
            approach_waypoint_id_for_marker,
        )

        if final == "hold":
            align_default = align_mode_for_hold_park(marker_id)
        else:
            wp = approach_waypoint_id_for_marker(marker_id)
            align_default = align_mode_for_approach_waypoint(wp)
        align_mode = resolve_align_mode(payload, default=align_default)
        pre_rotated = bool(payload.get("approach_yaw_pre_rotated"))
        if not payload.get("skip_approach_yaw_rotate") and not pre_rotated:
            target_yaw = payload.get("approach_yaw")
            if target_yaw is None:
                from nav_app.services.robot_commands import approach_yaw_for_marker

                target_yaw = approach_yaw_for_marker(marker_id)
            if target_yaw is not None and not skip_approach_yaw_if_marker_visible(marker_id, payload):
                if rotate_to_approach_yaw_if_needed(float(target_yaw), payload) is not True:
                    raise RuntimeError("approach yaw rotate failed before aruco_align")
            elif target_yaw is not None:
                payload["approach_yaw_pre_rotated"] = True
        elif pre_rotated:
            print(f"[aruco_align] approach map yaw already applied before marker seek (marker={marker_id})")
        print(f"[aruco_align] acquiring ArUco marker={marker_id} topic={_aruco_detection_topic()}")
        first_detection = acquire_dock_marker(marker_id, payload)
        print(f"[aruco_align] marker acquired: id={first_detection.get('marker_id')} center_error_norm={first_detection.get('center_error_norm')}")
    except CommandAborted:
        raise
    except Exception as exc:
        raise StageError("aruco", "marker_not_found") from exc
    try:
        if align_mode != "skip":
            final_detection = execute_docking_align(marker_id, payload)
            print(f"[aruco_align] alignment complete: {final_detection}; final={final}")
        else:
            print("[aruco_align] alignment skipped (already aligned at approach)")
    except CommandAborted:
        raise
    except Exception as exc:
        raise StageError("align", str(exc)) from exc
    if final == "hold":
        apply_slot_fork_defaults(payload, marker_id)
        apply_slot_aruco_defaults(payload, marker_id)
        if hold_fork_insert_enabled(payload):
            try:
                settle_sec = resolve_pre_insert_settle_sec(payload)
                if settle_sec > 0.0:
                    runtime.navigator.publish_stop_velocity()
                    print(
                        f"[aruco_align] pre-insert settle: {settle_sec:.2f}s "
                        f"(marker={marker_id})"
                    )
                    time.sleep(settle_sec)
                if not execute_fork_insert(payload):
                    raise RuntimeError("fork insert failed")
            except Exception as exc:
                raise StageError("insert", str(exc)) from exc
            actual = payload.get("_actual_insert_distance_m")
            if actual is not None:
                runtime.set_standby_park_reverse_distance_m(float(actual))
                print(
                    f"[aruco_align] hold park: insert actual={float(actual):.3f}m "
                    f"(leave_dock will reverse same distance)"
                )
        runtime.set_standby_parked(True)
        return True
    return True


def execute_dock_transfer_step(step: MovementStep):
    payload = step.payload
    normalize_aruco_payload(payload)
    if payload.get("metric_return_to_approach"):
        target = payload.get("return_target_pose")
        if not target or target.get("x") is None or target.get("y") is None:
            raise ValueError("metric return requires payload.return_target_pose")
    for field in ("aruco_marker_id", "action", "level"):
        if field not in payload:
            raise ValueError(f"dock_transfer step requires payload.{field}")
    marker_id = int(payload["aruco_marker_id"])
    action = str(payload["action"])
    if action not in ("load", "unload"):
        raise ValueError("dock_transfer action must be load or unload")
    level = int(payload["level"])
    if level not in (1, 2):
        raise ValueError("dock_transfer level must be 1 or 2")
    apply_slot_fork_defaults(payload, marker_id)
    apply_slot_lift_defaults(payload, marker_id)
    apply_slot_aruco_defaults(payload, marker_id)
    if payload.get("dry_run") or is_simulation_mode() or (runtime.mission_manager and runtime.mission_manager.dry_run):
        stages = ("aruco", "align", "pre_insert_lift", "insert", "lift", "carry", "reverse")
        for stage in stages:
            raise_if_estop(stage)
            print(f"[simulation] dock_transfer stage={stage} marker={marker_id} action={action} level={level}")
            time.sleep(max(0.0, min(SIMULATED_DOCK_STAGE_DELAY_SEC, 2.0)))
        return True

    try:
        from nav_app.services.robot_commands import align_mode_for_dock_marker

        align_mode = resolve_align_mode(
            payload,
            default=align_mode_for_dock_marker(marker_id),
        )
        if not payload.get("skip_approach_yaw_rotate"):
            target_yaw = payload.get("approach_yaw")
            if target_yaw is None:
                from nav_app.services.robot_commands import approach_yaw_for_marker

                target_yaw = approach_yaw_for_marker(marker_id)
            if target_yaw is not None:
                if rotate_to_approach_yaw_if_needed(float(target_yaw), payload) is not True:
                    raise RuntimeError("approach yaw rotate failed before dock_transfer")
        print(f"[dock_transfer] acquiring ArUco marker={marker_id} topic={_aruco_detection_topic()}")
        first_detection = acquire_dock_marker(marker_id, payload)
        print(f"[dock_transfer] marker acquired: {first_detection}")
    except CommandAborted:
        raise
    except Exception as exc:
        raise StageError("aruco", "marker_not_found") from exc
    try:
        if align_mode != "skip":
            final_detection = execute_docking_align(marker_id, payload)
            print(f"[dock_transfer] alignment ({align_mode}) complete: {final_detection}")
        else:
            print("[dock_transfer] alignment skipped (already aligned at approach)")
    except CommandAborted:
        raise
    except Exception as exc:
        raise StageError("align", str(exc)) from exc
    try:
        execute_pre_insert_lift(action, level, payload)
    except Exception as exc:
        raise StageError("pre_insert_lift", str(exc)) from exc
    try:
        if not execute_fork_insert(payload):
            raise RuntimeError("fork insert failed")
    except Exception as exc:
        raise StageError("insert", str(exc)) from exc
    try:
        execute_post_insert_dwell(payload)
    except Exception as exc:
        raise StageError("lift", str(exc)) from exc
    try:
        execute_lift_action(action, level, payload)
    except Exception as exc:
        raise StageError("lift", str(exc)) from exc
    try:
        execute_carry_after_load(action, level, payload)
    except Exception as exc:
        raise StageError("carry", str(exc)) from exc
    try:
        if not execute_dock_reverse(payload):
            raise RuntimeError("dock reverse failed")
    except Exception as exc:
        raise StageError("reverse", str(exc)) from exc
    # dock_transfer 는 마지막에 후진으로 빠져나오므로 대기-도킹 상태가 아니다.
    runtime.set_standby_parked(False)
    return True
