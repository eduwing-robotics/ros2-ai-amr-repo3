"""ArUco docking and leave-dock sequences."""
import math
import time
from typing import Any, Dict, Optional

from nav_app.errors import CommandAborted, StageError
from nav_app.models import MovementStep
from nav_app.runtime import runtime
from nav_app.services import robot_context
from nav_app.services.capabilities import (
    ensure_lift_ready_for_dock_transfer,
    has_capability,
)
from nav_app.services.robot_commands import (
    apply_slot_aruco_defaults,
    apply_slot_lift_defaults,
    approach_waypoint_id_for_marker,
    fork_insert_distance_for_marker,
    load_waypoint_goals,
)
from nav_app.services.robot_context import (
    aruco_detection_topic as _aruco_detection_topic,
)
from nav_app.services.status_helpers import clamp as _clamp
from nav_app.settings import (
    ARUCO_APPROACH_SKIP_MAP_YAW_MARKER_ERR,
    ARUCO_DETECTION_MAX_AGE_SEC,
    ARUCO_DETECTION_TIMEOUT_SEC,
    ARUCO_DOCK_ALIGN_SETTLE_FRAMES,
    ARUCO_DOCK_ANGULAR_GAIN,
    ARUCO_DOCK_CENTER_GOOD_ENOUGH_NORM,
    ARUCO_DOCK_CENTER_TOLERANCE_NORM,
    ARUCO_DOCK_CONTROL_PERIOD_SEC,
    ARUCO_DOCK_LINEAR_SPEED,
    ARUCO_DOCK_LOST_ACCEPT_WIDTH_RATIO,
    ARUCO_DOCK_LOST_GRACE_SEC,
    ARUCO_DOCK_MAX_ANGULAR_SPEED,
    ARUCO_DOCK_MIN_ANGULAR_RAD,
    ARUCO_DOCK_MIN_LINEAR_SPEED,
    ARUCO_DOCK_TARGET_DISTANCE_M,
    ARUCO_DOCK_TARGET_WIDTH_PX,
    ARUCO_DOCKING_TIMEOUT_SEC,
    ARUCO_MARKER_CENTERING_ANGULAR_SPEED,
    ARUCO_MARKER_SEARCH_ANGULAR_SPEED,
    ARUCO_MARKER_SEARCH_BURST_SEC,
    ARUCO_MARKER_SEARCH_BURSTS_PER_DIR,
    ARUCO_MARKER_SEARCH_TIMEOUT_SEC,
    ARUCO_MARKER_SEEK_MAX_ROTATION_RAD,
    DOCK_FORWARD_CLEARANCE_MARGIN_M,
    DOCK_POST_INSERT_DWELL_SEC,
    DOCK_REVERSE_EXTRA_M,
    DOCK_REVERSE_SPEED,
    FORK_INSERT_DISTANCE_M,
    FORK_INSERT_ENABLED,
    FORK_INSERT_MAX_DURATION_SEC,
    FORK_INSERT_SLIP_COMPENSATION_M,
    FORK_INSERT_SPEED_MPS,
    INSERT_CREEP_SPEED_MPS,
    INSERT_STOP_WIDTH_PX,
    INSERT_VISION_SNAPSHOT_DIR,
    INSERT_VISION_SNAPSHOT_ENABLED,
    INSERT_VISION_STOP_ENABLED,
    LEAVE_DOCK_CLEARANCE_MARGIN_M,
    LEAVE_DOCK_MAX_DURATION_SEC,
    LEAVE_DOCK_REAR_ARC_DEG,
    LEAVE_DOCK_REAR_SCAN_MAX_AGE_SEC,
    LEAVE_DOCK_REVERSE_SPEED,
    METRIC_DOCK_REVERSE_MAX_DURATION_SEC,
    METRIC_DOCK_REVERSE_MAX_SPEED_MPS,
    NAV_APPROACH_ROTATE_MAX_SEC,
    NAV_APPROACH_ROTATE_SPEED_RAD,
    NAV_APPROACH_ROTATE_YAW_THRESHOLD_RAD,
    PRE_INSERT_CENTER_CYCLES,
    PRE_INSERT_CREEP_SEC,
    PRE_INSERT_CREEP_SPEED_MPS,
    SIMULATED_DOCK_STAGE_DELAY_SEC,
    is_simulation_mode,
)


def _physical_motion_bypassed(payload: Dict[str, Any]) -> bool:
    """Only explicit simulation/dry-run may bypass docking sensor fail-close gates."""
    return bool(
        payload.get("dry_run")
        or is_simulation_mode()
        or (runtime.mission_manager and runtime.mission_manager.dry_run)
    )


def require_docking_motion_freshness(
    payload: Dict[str, Any], stage: str, *, require_aruco: bool = False, require_lift: Optional[bool] = None
) -> None:
    """Fail closed before every physical insert/reverse segment.

    Receipt time is intentionally evaluated in the navigator process; producer wall
    clocks are only source-timestamp evidence and cannot make stale data fresh.
    """
    if _physical_motion_bypassed(payload):
        return
    metric_motion = bool(
        payload.get("metric_precision_insert") or payload.get("metric_distance_only")
    )
    if metric_motion:
        scan_max_age_sec = _bounded_metric_motion_value(
            payload, "scan_max_age_sec", 1.0, minimum=0.05, maximum=1.0
        )
        tf_max_age_sec = _bounded_metric_motion_value(
            payload, "tf_max_age_sec", 1.0, minimum=0.05, maximum=1.0
        )
        aruco_max_age_sec = _bounded_metric_motion_value(
            payload, "aruco_max_age_sec", 1.0, minimum=0.05, maximum=1.0
        )
    else:
        scan_max_age_sec = payload.get("scan_max_age_sec")
        tf_max_age_sec = payload.get("tf_max_age_sec")
        aruco_max_age_sec = payload.get("aruco_max_age_sec")
    navigator = runtime.navigator
    if not navigator or not hasattr(navigator, "docking_sensor_freshness"):
        raise RuntimeError(f"{stage}: docking_sensor_freshness_unavailable")
    health = navigator.docking_sensor_freshness(
        require_aruco=require_aruco,
        max_scan_age_sec=scan_max_age_sec,
        max_tf_age_sec=tf_max_age_sec,
        max_aruco_age_sec=aruco_max_age_sec,
    )
    if not isinstance(health, dict) or not health.get("ok"):
        reason = health.get("reason", "sensor_freshness_invalid") if isinstance(health, dict) else "sensor_freshness_invalid"
        raise RuntimeError(f"{stage}: {reason}")
    lift_client = getattr(runtime, "lift_client", None)
    # Lift-less robots retain their existing docking path.  A lift-equipped
    # robot, however, must not move its base while lift telemetry is stale.
    if require_lift is None:
        require_lift = bool(lift_client and getattr(lift_client, "enabled", False))
    if require_lift:
        health = lift_client.telemetry_health() if lift_client and getattr(lift_client, "enabled", False) else None
        if not isinstance(health, dict) or not health.get("ready"):
            reason = health.get("reason", "lift_telemetry_unavailable") if isinstance(health, dict) else "lift_telemetry_unavailable"
            raise RuntimeError(f"{stage}: lift_{reason}")


def _publish_docking_velocity(
    payload: Dict[str, Any],
    stage: str,
    *,
    require_aruco: bool = True,
    require_lift: Optional[bool] = None,
    **velocity: Any,
) -> bool:
    """Continuously gate docking velocity and force a zero on every failure.

    ``publish_velocity_for_duration`` owns a blocking velocity loop.  Calling it
    once for a long reverse would otherwise leave a stale scan/TF/ArUco/lift
    stream undetected until the base had already moved for the full duration.
    Keep bursts short and re-admit each one locally.
    """
    duration_sec = max(0.0, float(velocity.get("duration_sec", 0.0)))
    if payload.get("metric_precision_insert") or payload.get("metric_distance_only"):
        segment_sec = _bounded_metric_motion_value(
            payload,
            "docking_freshness_segment_sec",
            0.10,
            minimum=0.02,
            maximum=0.20,
        )
    else:
        segment_sec = max(
            0.02,
            min(0.25, float(payload.get("docking_freshness_segment_sec", 0.10))),
        )
    remaining = duration_sec
    while remaining > 1e-9:
        _require_docking_motion_or_abort(
            payload, stage, require_aruco=require_aruco, require_lift=require_lift,
        )
        burst = min(segment_sec, remaining)
        try:
            result = runtime.navigator.publish_velocity_for_duration(
                **{**velocity, "duration_sec": burst}
            )
        except Exception:
            _abort_docking_motion()
            raise
        if result is not True:
            _abort_docking_motion()
            return False
        remaining -= burst
    return True


def _abort_docking_motion() -> None:
    """Best-effort base/lift stop for every docking safety-gate failure."""
    if runtime.navigator:
        runtime.navigator.publish_stop_velocity()
    lift_client = getattr(runtime, "lift_client", None)
    if lift_client and getattr(lift_client, "enabled", False):
        try:
            lift_client.stop()
        except Exception:
            # Never let a lift bridge error suppress the base stop.
            pass


def _require_docking_motion_or_abort(
    payload: Dict[str, Any],
    stage: str,
    *,
    require_aruco: bool = False,
    require_lift: Optional[bool] = None,
) -> None:
    """Apply the admission gate and stop both physical actuators on failure."""
    try:
        raise_if_command_canceled(stage)
        require_docking_motion_freshness(
            payload, stage, require_aruco=require_aruco, require_lift=require_lift,
        )
    except Exception:
        _abort_docking_motion()
        raise


def _accumulate_dock_forward_m(payload: Dict[str, Any], linear_x: float, duration_sec: float) -> None:
    """full align 등 dock 중 전진 거리를 누적해 후진 거리 계산에 반영한다."""
    if linear_x <= 0.0 or duration_sec <= 0.0:
        return
    payload["_align_forward_net_m"] = float(payload.get("_align_forward_net_m", 0.0)) + linear_x * duration_sec


def _metric_forward_distance(detection: Optional[Dict[str, Any]]) -> Optional[float]:
    if not detection:
        return None
    value = detection.get("forward_distance_m", detection.get("estimated_distance_m"))
    try:
        distance = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(distance) or distance < 0.0:
        return None
    return distance


def _bounded_metric_motion_value(
    payload: Dict[str, Any],
    field: str,
    default: float,
    *,
    minimum: float,
    maximum: Optional[float],
) -> float:
    try:
        value = float(payload.get(field, default))
    except (TypeError, ValueError):
        value = math.nan
    if not math.isfinite(value) or value < minimum or (
        maximum is not None and value > maximum
    ):
        _abort_docking_motion()
        if maximum is None:
            raise ValueError(f"metric docking {field} must be finite and at least {minimum}")
        raise ValueError(f"metric docking {field} must be between {minimum} and {maximum}")
    return value


def metric_distance_state(detection: Optional[Dict[str, Any]], payload: Dict[str, Any]) -> str:
    """Classify metric distance as invalid, far, target-band, or overshot."""
    distance = _metric_forward_distance(detection)
    if distance is None:
        return "invalid"
    target = float(payload.get("target_distance_m", ARUCO_DOCK_TARGET_DISTANCE_M))
    tolerance = max(0.001, abs(float(payload.get("metric_distance_tolerance_m", 0.02))))
    if distance < target - tolerance:
        return "overshot"
    if distance <= target + tolerance:
        return "within"
    return "far"


def marker_close_enough(detection: Dict[str, Any], payload: Dict[str, Any]):
    target_width_px = float(payload.get("target_marker_width_px", ARUCO_DOCK_TARGET_WIDTH_PX))
    try:
        width_px = float(detection.get("marker_width_px", 0.0))
    except (TypeError, ValueError):
        width_px = 0.0
    metric_only = bool(payload.get("metric_distance_only", False))
    if payload.get("close_from_marker_width_only", False) and not metric_only:
        return width_px >= target_width_px
    if metric_only:
        return metric_distance_state(detection, payload) == "within"
    target_distance_m = float(payload.get("target_distance_m", ARUCO_DOCK_TARGET_DISTANCE_M))
    estimated_distance = detection.get("forward_distance_m", detection.get("estimated_distance_m"))
    if estimated_distance is not None:
        try:
            distance_m = float(estimated_distance)
            if math.isfinite(distance_m) and distance_m >= 0.0:
                return distance_m <= target_distance_m
        except (TypeError, ValueError):
            pass
    try:
        return width_px >= target_width_px
    except (TypeError, ValueError):
        return False


def marker_near_insert_start(detection: Dict[str, Any], payload: Dict[str, Any]):
    center_tolerance = _acquire_center_tolerance(payload)
    try:
        if abs(float(detection.get("center_error_norm", 0.0))) > center_tolerance:
            return False
    except (TypeError, ValueError):
        return False
    target_distance_m = float(payload.get("target_distance_m", ARUCO_DOCK_TARGET_DISTANCE_M))
    estimated_distance = detection.get("forward_distance_m", detection.get("estimated_distance_m"))
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


def marker_normal_errors(
    detection: Optional[Dict[str, Any]], payload: Optional[Dict[str, Any]] = None
) -> Optional[Dict[str, float]]:
    """Return camera-frame errors against the desired ArUco normal."""
    if not detection:
        return None
    payload = payload or {}
    if payload.get("require_pose_quality", False):
        try:
            reprojection_error = float(detection["reprojection_error_px"])
            max_reprojection_error = float(payload.get("max_reprojection_error_px", 2.0))
        except (KeyError, TypeError, ValueError):
            return None
        if (
            not math.isfinite(reprojection_error)
            or reprojection_error < 0.0
            or reprojection_error > max_reprojection_error
        ):
            return None
    lateral = detection.get("lateral_offset_m")
    yaw = detection.get("marker_yaw_rad")
    if lateral is None or yaw is None:
        return None
    try:
        lateral_error = float(lateral) - float(payload.get("target_lateral_offset_m", 0.0))
        yaw_error = float(yaw) - float(payload.get("target_marker_yaw_rad", 0.0))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(lateral_error) or not math.isfinite(yaw_error):
        return None
    return {"lateral_m": lateral_error, "yaw_rad": yaw_error}


def marker_normal_aligned(
    detection: Optional[Dict[str, Any]], payload: Optional[Dict[str, Any]] = None
) -> bool:
    payload = payload or {}
    errors = marker_normal_errors(detection, payload)
    if errors is None:
        return False
    lateral_tolerance = abs(float(payload.get("normal_lateral_tolerance_m", 0.04)))
    yaw_tolerance = abs(float(payload.get("normal_yaw_tolerance_rad", math.radians(5.0))))
    return bool(
        abs(errors["lateral_m"]) <= lateral_tolerance
        and abs(errors["yaw_rad"]) <= yaw_tolerance
    )


def normal_alignment_angular_command(
    detection: Optional[Dict[str, Any]],
    payload: Optional[Dict[str, Any]] = None,
    *,
    max_angular: float,
) -> Optional[float]:
    """Bounded differential-drive correction for marker lateral/yaw error."""
    payload = payload or {}
    errors = marker_normal_errors(detection, payload)
    if errors is None:
        return None
    lateral_gain = float(payload.get("normal_lateral_gain", 1.2))
    yaw_gain = float(payload.get("normal_yaw_gain", 0.8))
    command = -(lateral_gain * errors["lateral_m"] + yaw_gain * errors["yaw_rad"])
    return _apply_angular_deadband(
        _clamp(command, -abs(float(max_angular)), abs(float(max_angular))), payload
    )


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
        # This is a map-pose pre-rotation whose purpose is to bring the marker
        # into view. Requiring an already-fresh ArUco observation here makes
        # marker search impossible and duplicates the following acquire/align
        # stage. Scan/TF, E-stop, cancellation, and lift telemetry remain
        # checked by the shared motion gate.
        _publish_docking_velocity(payload, "approach_yaw", require_aruco=False,
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

    center_tolerance = _acquire_center_tolerance(payload)
    deadline = time.monotonic() + float(
        payload.get("marker_search_timeout_sec", ARUCO_MARKER_SEARCH_TIMEOUT_SEC)
    )
    max_age_sec = float(payload.get("marker_search_max_age_sec", ARUCO_DETECTION_MAX_AGE_SEC))
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
                _clamp(-angular_gain * error_norm, -speed, speed),
                payload,
            )
            _publish_docking_velocity(payload, "aruco_align", require_aruco=True,
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
        _publish_docking_velocity(payload, "aruco_search",
            linear_x=0.0,
            angular_z=seek_dir * centering_speed,
            duration_sec=burst_sec,
        )
        seek_turned_rad += abs(seek_dir * centering_speed * burst_sec)
        runtime.navigator.publish_stop_velocity()
        if not monotonic and sweep_enabled:
            if last_error is not None and miss_streak >= 2:
                sweep_dir = -1.0 if last_error > 0.0 else 1.0
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
            _publish_docking_velocity(payload, "aruco_search",
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
                    "marker_seek_mode": "monotonic",
                    "docking_timeout_sec": min(
                        15.0,
                        float(payload.get("docking_timeout_sec", ARUCO_DOCKING_TIMEOUT_SEC)),
                    ),
                },
            )
        print(
            f"[aruco_seek] marker={marker_id} not visible "
            f"→ monotonic slow seek (timeout={payload.get('marker_search_timeout_sec', ARUCO_MARKER_SEARCH_TIMEOUT_SEC)}s)"
        )
        seek_payload = {**payload, "marker_seek_mode": "monotonic"}
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
            "[dock] full_center: skip phase2 forward — fork_insert is the only insert advance"
        )
        return detection
    print(f"[dock] full align phase2: forward marker={marker_id} (keep center, then width target)")
    return execute_precision_docking(marker_id, payload)


def execute_center_align_only(marker_id: int, payload: Dict[str, Any]):
    """마커 중앙에 맞출 때까지 제자리 회전만 한다. approach 캘리브 기준과 동일."""
    if not runtime.navigator:
        raise RuntimeError("runtime.navigator is not initialized")
    deadline = time.monotonic() + float(payload.get("docking_timeout_sec", ARUCO_DOCKING_TIMEOUT_SEC))
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
            _publish_docking_velocity(payload, "aruco_align",
                linear_x=0.0,
                angular_z=seek_dir * centering_speed,
                duration_sec=burst_sec,
            )
            runtime.navigator.publish_stop_velocity()
            if not monotonic and last_detection is not None and miss_streak >= 2:
                err = _marker_center_error_norm(last_detection)
                sweep_dir = -1.0 if err is not None and err > 0.0 else 1.0
            elif not monotonic and miss_streak >= 3:
                sweep_dir *= -1.0
            time.sleep(0.05)
            continue
        miss_streak = 0
        last_detection = detection
        error_norm = float(detection.get("center_error_norm", 0.0))
        done, settle_count, label = _try_align_settled(error_norm, payload, settle_count, settle_need)
        if done:
            runtime.navigator.publish_stop_velocity()
            if label == "good-enough":
                print(f"[center_align] marker={marker_id} good-enough err={error_norm:.4f}")
            return detection
        if settle_count > 0:
            runtime.navigator.publish_stop_velocity()
            time.sleep(control_period)
            continue
        settle_count = 0
        speed = min(max_angular, search_speed, max(centering_speed, abs(angular_gain * error_norm)))
        angular_z = _apply_angular_deadband(
            _clamp(-angular_gain * error_norm, -speed, speed),
            payload,
        )
        _publish_docking_velocity(payload, "aruco_align", require_aruco=True,
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


def execute_precision_docking(marker_id: int, payload: Dict[str, Any]):
    if not runtime.navigator:
        raise RuntimeError("runtime.navigator is not initialized")
    metric_only = bool(payload.get("metric_distance_only", False))
    center_tolerance = _acquire_center_tolerance(payload)
    if metric_only:
        timeout_sec = _bounded_metric_motion_value(
            payload,
            "docking_timeout_sec",
            ARUCO_DOCKING_TIMEOUT_SEC,
            minimum=1.0,
            maximum=None,
        )
    else:
        timeout_sec = _bounded_metric_motion_value(
            payload,
            "docking_timeout_sec",
            ARUCO_DOCKING_TIMEOUT_SEC,
            minimum=1.0,
            maximum=None,
        )
    deadline = time.monotonic() + timeout_sec
    coarse_center_tolerance = float(payload.get("coarse_center_tolerance_norm", max(center_tolerance * 3.0, 0.30)))
    if metric_only:
        control_period = _bounded_metric_motion_value(
            payload,
            "control_period_sec",
            0.10,
            minimum=0.05,
            maximum=0.20,
        )
        linear_speed = _bounded_metric_motion_value(
            payload,
            "dock_linear_speed",
            0.018,
            minimum=0.005,
            maximum=0.03,
        )
        min_linear_speed = _bounded_metric_motion_value(
            payload,
            "dock_min_linear_speed",
            0.006,
            minimum=0.001,
            maximum=linear_speed,
        )
    else:
        control_period = max(
            0.05,
            float(payload.get("control_period_sec", ARUCO_DOCK_CONTROL_PERIOD_SEC)),
        )
        linear_speed = abs(float(payload.get("dock_linear_speed", ARUCO_DOCK_LINEAR_SPEED)))
        min_linear_speed = abs(
            float(payload.get("dock_min_linear_speed", ARUCO_DOCK_MIN_LINEAR_SPEED))
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
    require_normal = bool(payload.get("require_normal_alignment", False))
    straight_insert = bool(payload.get("straight_when_normal_aligned", False))
    normal_coarse_lateral = abs(float(payload.get("normal_coarse_lateral_m", 0.10)))
    normal_coarse_yaw = abs(float(payload.get("normal_coarse_yaw_rad", 0.22)))
    normal_lateral_tolerance = abs(float(payload.get("normal_lateral_tolerance_m", 0.04)))
    normal_backoff_budget = max(0.0, float(payload.get("normal_realign_backoff_m", 0.04)))
    normal_backoff_m = 0.0
    straight_miss_count = 0
    straight_miss_limit = max(1, int(payload.get("straight_alignment_miss_frames", 3)))
    last_detection = None
    last_seen_at = None
    settle_count = 0
    settle_need = _center_settle_need(payload)
    last_progress_log = 0.0

    while time.monotonic() < deadline:
        if runtime.navigator.safety.estop:
            raise RuntimeError("precision docking aborted by estop")
        detection = runtime.navigator.get_latest_aruco_detection(marker_id, max_age_sec=ARUCO_DETECTION_MAX_AGE_SEC)
        if not detection:
            last_normal_ok = not require_normal or marker_normal_aligned(last_detection, payload)
            if (
                payload.get("allow_marker_lost_at_insert_start", True)
                and last_detection
                and last_normal_ok
                and marker_near_insert_start(last_detection, payload)
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
                    payload.get("forward_center_tolerance_norm", center_tolerance)
                )
                if last_err <= forward_tol and last_normal_ok and not straight_insert:
                    _publish_docking_velocity(payload, "aruco_align", require_aruco=True,
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
        last_detection = detection
        last_seen_at = time.monotonic()
        error_norm = float(detection.get("center_error_norm", 0.0))
        metric_state = (
            metric_distance_state(detection, payload)
            if payload.get("metric_distance_only", False)
            else None
        )
        if metric_state == "invalid":
            _abort_docking_motion()
            raise RuntimeError(
                f"ArUco marker {marker_id} has no valid calibrated forward distance"
            )
        if metric_state == "overshot":
            _abort_docking_motion()
            distance = _metric_forward_distance(detection)
            target = float(payload.get("target_distance_m", ARUCO_DOCK_TARGET_DISTANCE_M))
            raise RuntimeError(
                f"metric docking target overshot: distance={distance:.3f}m target={target:.3f}m"
            )
        normal_errors = marker_normal_errors(detection, payload) if require_normal else None
        if require_normal and normal_errors is None:
            runtime.navigator.publish_stop_velocity()
            raise RuntimeError(
                f"ArUco marker {marker_id} has no calibrated lateral/yaw pose; "
                "metric normal alignment is unavailable"
            )
        normal_ok = not require_normal or marker_normal_aligned(detection, payload)
        close_enough = marker_close_enough(detection, payload)
        if close_enough and abs(error_norm) <= center_tolerance and normal_ok:
            settle_count += 1
            if _centered_enough(error_norm, center_tolerance, settle_count, settle_need):
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
        if require_normal and not normal_ok:
            angular_z = normal_alignment_angular_command(
                detection, payload, max_angular=max_angular
            ) or 0.0
        elif abs_error > center_tolerance and not straight_insert:
            gain = angular_gain * (0.45 if wall_mode else 1.0)
            cap = max_angular * (0.6 if wall_mode and width < target_width * 0.85 else 1.0)
            angular_z = _apply_angular_deadband(
                _clamp(-gain * error_norm, -cap, cap),
                payload,
            )

        forward_tol = float(
            payload.get("forward_center_tolerance_norm", center_tolerance)
        )
        normal_within_coarse = bool(
            not require_normal
            or (
                normal_errors is not None
                and abs(normal_errors["lateral_m"]) <= normal_coarse_lateral
                and abs(normal_errors["yaw_rad"]) <= normal_coarse_yaw
            )
        )

        if straight_insert:
            # The final 0.40m -> 0.18/0.20m leg is deliberately straight.  A
            # drift does not trigger steering beside the pallet; it stops and
            # fails so the operator can re-run the 0.40m normal-alignment gate.
            if not normal_ok or abs(error_norm) > forward_tol:
                straight_miss_count += 1
                command_linear = 0.0
                angular_z = 0.0
                if straight_miss_count >= straight_miss_limit:
                    runtime.navigator.publish_stop_velocity()
                    raise RuntimeError(
                        f"marker {marker_id} normal alignment drifted during straight insert"
                    )
            elif not close_enough:
                straight_miss_count = 0
                command_linear = linear_speed
                angular_z = 0.0
            else:
                straight_miss_count = 0
                command_linear = 0.0
                angular_z = 0.0
        # At the standoff target, create a small amount of room before another
        # curved approach when lateral alignment is still outside tolerance.
        elif (
            require_normal
            and close_enough
            and normal_errors is not None
            and abs(normal_errors["lateral_m"]) > normal_lateral_tolerance
            and normal_backoff_m < normal_backoff_budget
        ):
            command_linear = -min_linear_speed
            angular_z = 0.0
            normal_backoff_m += min_linear_speed * control_period
        # 중앙·법선의 coarse gate가 맞기 전에는 전진하지 않는다.
        elif abs(error_norm) > forward_tol or not normal_within_coarse:
            command_linear = 0.0
        elif not close_enough:
            command_linear = linear_speed
        elif metric_state == "within" and (abs_error > center_tolerance or not normal_ok):
            # At a metric standoff, finish angular/lateral correction without
            # creeping closer than the bounded target band.
            command_linear = 0.0
        elif abs_error > center_tolerance or not normal_ok:
            error_span = max(0.001, coarse_center_tolerance - center_tolerance)
            scale = 1.0 - min(1.0, max(0.0, (abs_error - center_tolerance) / error_span))
            command_linear = max(min_linear_speed, linear_speed * scale)
        else:
            command_linear = linear_speed

        ok = _publish_docking_velocity(payload, "aruco_align", require_aruco=True,
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
            normal_log = ""
            if normal_errors is not None:
                normal_log = (
                    f" lateral={normal_errors['lateral_m']:+.3f}m"
                    f" yaw={math.degrees(normal_errors['yaw_rad']):+.1f}deg"
                )
            print(
                f"[dock] full align progress marker={marker_id} "
                f"err={error_norm:.3f} width={width:.0f}/{target_width:.0f} "
                f"linear={command_linear:.3f} angular={angular_z:.3f}{normal_log}"
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


def resolve_insert_stop_width_px(payload: Dict[str, Any]) -> float:
    """payload/zones insert_stop_width_px → 전역 INSERT_STOP_WIDTH_PX(135). target_marker_width_px와 분리."""
    for key in ("insert_stop_width_px", "insert_stop_marker_width_px"):
        explicit = payload.get(key)
        if explicit is not None:
            return float(explicit)
    return INSERT_STOP_WIDTH_PX


def resolve_insert_extra_after_vision_m(payload: Dict[str, Any]) -> float:
    """Return an explicitly commissioned post-vision insertion distance.

    The safe default is zero.  Physical pallet slots opt in through zones.json,
    which keeps ordinary ArUco parking and uncommissioned docks unchanged.
    """
    for key in (
        "insert_extra_after_vision_m",
        "insert_extra_m",
        "fork_insert_extra_after_vision_m",
    ):
        if payload.get(key) is not None:
            return max(0.0, float(payload[key]))
    return 0.0


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
    """dock_transfer payload에 슬롯별 삽입 거리와 후진 여유를 주입한다."""
    if "fork_insert_distance_m" not in payload and "insert_distance_m" not in payload:
        calibrated = fork_insert_distance_for_marker(marker_id)
        if calibrated is not None:
            payload["fork_insert_distance_m"] = calibrated
    if payload.get("reverse_extra_m") is None:
        waypoint_id = approach_waypoint_id_for_marker(marker_id)
        waypoint = load_waypoint_goals().get(waypoint_id or "") or {}
        extra = waypoint.get("reverse_extra_m")
        if extra is None and isinstance(waypoint.get("aruco_align"), dict):
            extra = waypoint["aruco_align"].get("reverse_extra_m")
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
    return bool(lift_client and getattr(lift_client, "enabled", False))


def resolve_post_insert_dwell_sec(payload: Dict[str, Any]) -> float:
    """insert 후 lift 동작 시간. 리프트 미연동이면 기본 4s 대기 후 후진."""
    explicit = payload.get("post_insert_dwell_sec", payload.get("lift_dwell_sec"))
    if explicit is not None:
        return max(0.0, float(explicit))
    if lift_action_enabled(payload):
        return 0.0
    return max(0.0, float(DOCK_POST_INSERT_DWELL_SEC))


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

    center_tolerance = _acquire_center_tolerance(payload)
    deadline = time.monotonic() + float(
        payload.get(
            "pre_insert_center_timeout_sec",
            payload.get("docking_timeout_sec", ARUCO_DOCKING_TIMEOUT_SEC),
        )
    )
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
        }
        try:
            detection = execute_center_align_only(marker_id, cycle_payload)
            error_norm = _marker_center_error_norm(detection)
            if detection and error_norm is not None and abs(error_norm) <= center_tolerance:
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
        if detection and error_norm is not None and abs(error_norm) <= center_tolerance:
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
            _publish_docking_velocity(payload, "pre_insert", require_aruco=True,
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
            _publish_docking_velocity(payload, "pre_insert", require_aruco=True,
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
    if detection and error_norm is not None and abs(error_norm) <= center_tolerance:
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


def execute_metric_precision_insert(payload: Dict[str, Any]):
    """Recheck the 0.40 m normal, then drive the calibrated final leg straight."""
    if not runtime.navigator:
        raise RuntimeError("runtime.navigator is not initialized")
    marker_value = payload.get("aruco_marker_id")
    if marker_value is None:
        raise ValueError("metric precision insert requires aruco_marker_id")
    marker_id = int(marker_value)
    stage1 = float(payload.get("stage1_target_distance_m", 0.40))
    stage2 = float(payload.get("target_distance_m", 0.20))
    if stage1 <= 0.0 or stage2 <= 0.0 or stage2 >= stage1:
        raise ValueError("metric precision insert requires 0 < stage2 < stage1")

    recheck = dict(payload)
    recheck.update(
        {
            "target_distance_m": stage1,
            "metric_distance_only": True,
            "require_normal_alignment": True,
            "straight_when_normal_aligned": False,
            "fork_insert_enabled": False,
            "insert_vision_stop": False,
            "allow_marker_lost_at_insert_start": False,
            "docking_timeout_sec": float(payload.get("normal_realign_timeout_sec", 20.0)),
        }
    )
    detection = runtime.navigator.get_latest_aruco_detection(
        marker_id, max_age_sec=ARUCO_DETECTION_MAX_AGE_SEC
    )
    if metric_distance_state(detection, recheck) == "overshot":
        _abort_docking_motion()
        distance = _metric_forward_distance(detection)
        raise RuntimeError(
            f"metric 0.40m gate already overshot: distance={distance:.3f}m target={stage1:.3f}m"
        )
    center_error = _marker_center_error_norm(detection)
    stage1_ready = bool(
        detection
        and center_error is not None
        and abs(center_error) <= float(recheck.get("center_tolerance_norm", ARUCO_DOCK_CENTER_TOLERANCE_NORM))
        and marker_close_enough(detection, recheck)
        and marker_normal_aligned(detection, recheck)
    )
    if not stage1_ready:
        print(f"[dock_transfer] re-align marker={marker_id} at {stage1:.2f}m normal gate")
        detection = execute_precision_docking(marker_id, recheck)
    else:
        print(f"[dock_transfer] marker={marker_id} normal gate already valid at {stage1:.2f}m")

    start_distance = _metric_forward_distance(detection)

    payload.update(
        {
            "target_distance_m": stage2,
            "metric_distance_only": True,
            "require_normal_alignment": True,
            "straight_when_normal_aligned": True,
            "fork_insert_enabled": False,
            "insert_vision_stop": False,
            "allow_marker_lost_at_insert_start": False,
            "marker_lost_grace_sec": 0.0,
        }
    )
    print(
        f"[dock_transfer] metric straight insert marker={marker_id} "
        f"{stage1:.2f}m -> {stage2:.2f}m"
    )
    final_detection = execute_precision_docking(marker_id, payload)
    if metric_distance_state(final_detection, payload) != "within":
        raise RuntimeError("metric straight insert did not finish inside the target distance band")
    final_distance = _metric_forward_distance(final_detection)
    if start_distance is not None and final_distance is not None:
        actual = max(0.0, start_distance - final_distance)
    else:
        actual = stage1 - stage2
    payload["_actual_insert_distance_m"] = actual
    payload["_requested_insert_distance_m"] = stage1 - stage2
    return True


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
    if (
        "fork_insert_forward_margin_m" not in payload
        and "insert_forward_margin_m" not in payload
    ):
        # This segment intentionally closes on the pallet.  A positive generic
        # obstacle margin would reject the commissioned final few centimetres;
        # marker-width and distance caps remain active below.
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
    result = True
    moved_duration = 0.0
    segment_sec = max(0.08, min(0.25, float(payload.get("fork_insert_segment_sec", 0.12))))
    stop_width_px = float(stop_width) if stop_width is not None else None
    vision_hit = False
    while moved_duration < duration:
        if runtime.navigator.safety.estop:
            result = False
            break
        raise_if_command_canceled("insert")
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

    measured_extra_m = 0.0
    if result and vision_hit and extra_after_vision_m > 1e-4 and not runtime.navigator.safety.estop:
        extra_duration_cap = extra_after_vision_m / max(0.01, speed) * 2.0 + 0.5

        def _insert_extra_stop_condition():
            raise_if_command_canceled("insert_extra")
            if runtime.navigator.safety.estop:
                return "estop"
            return None

        print(
            f"[dock_transfer] fork insert extra after vision: "
            f"target=+{extra_after_vision_m:.3f}m odom_closed_loop "
            f"cap={extra_duration_cap:.2f}s @ {speed:.3f}m/s"
        )
        try:
            distance_drive = runtime.navigator.publish_velocity_for_distance(
                linear_x=speed,
                distance_m=extra_after_vision_m,
                rate_hz=12.0,
                forward_margin_m=insert_margin,
                max_duration_sec=extra_duration_cap,
                tolerance_m=float(payload.get("insert_extra_tolerance_m", 0.005)),
                stop_condition=_insert_extra_stop_condition,
            )
        except Exception:
            _abort_docking_motion()
            raise
        measured_extra_m = float(distance_drive.get("distance_m", 0.0) or 0.0)
        payload["_insert_extra_after_vision_m"] = extra_after_vision_m
        payload["_insert_extra_after_vision_odom_m"] = measured_extra_m
        payload["_insert_extra_after_vision_feedback"] = bool(distance_drive.get("feedback"))
        payload["_insert_extra_after_vision_reason"] = distance_drive.get("reason")
        if not distance_drive.get("ok"):
            print(
                f"[dock_transfer] fork insert extra failed: "
                f"reason={distance_drive.get('reason')} measured={measured_extra_m:.3f}m "
                f"target={extra_after_vision_m:.3f}m"
            )
            result = False

    payload["_actual_insert_distance_m"] = speed * moved_duration + measured_extra_m
    runtime.navigator.publish_stop_velocity()
    return result


def execute_lift_action(action: str, level: int, payload: Dict[str, Any]):
    lift_client = getattr(runtime, "lift_client", None)
    if not lift_client or not getattr(lift_client, "enabled", False):
        raise RuntimeError("lift client is not enabled")
    _require_docking_motion_or_abort(payload, "lift", require_lift=True)
    result = lift_client.execute_transfer(action, level, payload)
    print(f"[dock_transfer] lift {action} level={level} complete: {result}")
    return True


def execute_pre_insert_lift(action: str, level: int, payload: Dict[str, Any]):
    """insert 전 선반 높이 맞춤 (level 2 등). lift 미연동이면 skip."""
    lift_client = getattr(runtime, "lift_client", None)
    if not lift_client or not getattr(lift_client, "enabled", False):
        return
    from nav_app.services.lift_phases import resolve_pre_insert_height_mm

    home_requested = payload.get("pre_insert_home", False)
    if isinstance(home_requested, str):
        home_requested = home_requested.strip().lower() in ("1", "true", "yes", "on")
    target = resolve_pre_insert_height_mm(action, level, payload, lift_client.config)
    if home_requested or target == 0.0:
        _require_docking_motion_or_abort(payload, "pre_insert_lift", require_lift=True)
        print(f"[dock_transfer] pre-insert lift home action={action} level={level}")
        result = lift_client.home(timeout_sec=payload.get("lift_timeout_sec"))
        print(f"[dock_transfer] pre-insert lift home complete: {result}")
        return
    if target is None:
        print(f"[dock_transfer] pre-insert lift skipped action={action} level={level}")
        return
    _require_docking_motion_or_abort(payload, "pre_insert_lift", require_lift=True)
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
    """load 후 이동 전 carry 높이까지 올림 (level 1 → 50mm 등)."""
    if str(action).lower() != "load":
        return
    lift_client = getattr(runtime, "lift_client", None)
    if not lift_client or not getattr(lift_client, "enabled", False):
        return
    from nav_app.services.lift_phases import resolve_carry_height_mm

    target = resolve_carry_height_mm(action, level, payload, lift_client.config)
    if target is None:
        return
    _require_docking_motion_or_abort(payload, "carry", require_lift=True)
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


def _finite_pose_value(pose: Dict[str, Any], field: str, *, fallback: Optional[str] = None) -> float:
    value = pose.get(field)
    if value is None and fallback:
        value = pose.get(fallback)
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise RuntimeError(f"map pose {field} is unavailable") from None
    if not math.isfinite(number):
        raise RuntimeError(f"map pose {field} is not finite")
    return number


def _validated_map_pose(
    pose: Any,
    *,
    label: str,
    source_max_age_sec: Optional[float] = None,
    captured_max_age_sec: Optional[float] = None,
) -> Dict[str, Any]:
    if not isinstance(pose, dict):
        raise RuntimeError(f"{label}: map pose unavailable")
    if pose.get("frame_id") != "map":
        raise RuntimeError(f"{label}: frame_id must be map")
    source = str(pose.get("source") or "")
    if source not in {"tf", "amcl_pose"}:
        raise RuntimeError(f"{label}: live pose source must be tf or amcl_pose")
    stamp = pose.get("stamp")
    if not isinstance(stamp, dict) or stamp.get("sec") is None or stamp.get("nanosec") is None:
        raise RuntimeError(f"{label}: source stamp is unavailable")
    try:
        stamp_sec = float(stamp["sec"])
        stamp_nanosec = float(stamp["nanosec"])
    except (TypeError, ValueError):
        raise RuntimeError(f"{label}: source stamp is invalid") from None
    if (
        not math.isfinite(stamp_sec)
        or not math.isfinite(stamp_nanosec)
        or not stamp_sec.is_integer()
        or not stamp_nanosec.is_integer()
        or stamp_sec < 0.0
        or stamp_nanosec < 0.0
        or stamp_nanosec >= 1_000_000_000.0
    ):
        raise RuntimeError(f"{label}: source stamp is invalid")
    x = _finite_pose_value(pose, "x")
    y = _finite_pose_value(pose, "y")
    yaw = _finite_pose_value(pose, "yaw", fallback="theta")
    normalized = {
        **pose,
        "source": source,
        "frame_id": "map",
        "x": x,
        "y": y,
        "yaw": yaw,
        "stamp": {"sec": int(stamp_sec), "nanosec": int(stamp_nanosec)},
    }
    if source_max_age_sec is not None:
        age = _finite_pose_value(pose, "age_sec")
        if age < 0.0 or age > float(source_max_age_sec):
            raise RuntimeError(
                f"{label}: live pose is stale ({age:.3f}s > {float(source_max_age_sec):.3f}s)"
            )
        normalized["age_sec"] = age
    if captured_max_age_sec is not None:
        captured_at = _finite_pose_value(pose, "captured_at_epoch_sec")
        captured_age = time.time() - captured_at
        if captured_age < -1.0 or captured_age > float(captured_max_age_sec):
            raise RuntimeError(
                f"{label}: saved return pose is stale ({captured_age:.3f}s)"
            )
        normalized["captured_at_epoch_sec"] = captured_at
    return normalized


def _require_localized_for_metric_pose(label: str) -> None:
    health = robot_context.localization_health()
    if not isinstance(health, dict) or health.get("localized") is not True:
        raise RuntimeError(f"{label}: localization is not healthy")


def capture_arrived_return_pose(
    pose: Any, *, source_max_age_sec: float
) -> Dict[str, Any]:
    """Capture a fresh live map pose that may later drive physical reverse."""
    _require_localized_for_metric_pose("metric ARRIVED pose")
    captured = _validated_map_pose(
        pose,
        label="metric ARRIVED pose",
        source_max_age_sec=source_max_age_sec,
    )
    captured["captured_at_epoch_sec"] = time.time()
    return captured


def _current_metric_map_pose(payload: Dict[str, Any], *, label: str) -> Dict[str, Any]:
    _require_localized_for_metric_pose(label)
    return _validated_map_pose(
        runtime.navigator.get_current_pose(),
        label=label,
        source_max_age_sec=float(payload.get("return_pose_source_max_age_sec", 1.0)),
    )


def validate_metric_return_pose_preflight(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Fail before insert/lift unless the saved ARRIVED pose is still usable."""
    target = payload.get("return_target_pose")
    source_max_age_sec = float(payload.get("return_pose_source_max_age_sec", 1.0))
    captured_max_age_sec = float(payload.get("return_pose_max_age_sec", 180.0))
    target_pose = _validated_map_pose(
        target,
        label="saved metric return pose preflight",
        source_max_age_sec=source_max_age_sec,
        captured_max_age_sec=captured_max_age_sec,
    )
    current_pose = _current_metric_map_pose(
        payload,
        label="metric return pose preflight live pose",
    )
    yaw_tolerance = max(
        0.001,
        abs(float(payload.get("return_pose_yaw_tolerance_rad", math.radians(5.0)))),
    )
    yaw_error = abs(_normalize_angle(current_pose["yaw"] - target_pose["yaw"]))
    if yaw_error > yaw_tolerance:
        raise RuntimeError(
            "metric return pose preflight yaw mismatch: "
            f"error={yaw_error:.3f}rad tolerance={yaw_tolerance:.3f}rad"
        )
    payload["return_target_pose"] = target_pose
    return target_pose


def execute_reverse_to_map_pose(payload: Dict[str, Any], target: Dict[str, Any]) -> bool:
    """Reverse straight to a fresh, server-captured map pose."""
    if not runtime.navigator:
        raise RuntimeError("runtime.navigator is not initialized")
    speed = _bounded_metric_motion_value(
        payload,
        "reverse_speed",
        DOCK_REVERSE_SPEED,
        minimum=0.01,
        maximum=METRIC_DOCK_REVERSE_MAX_SPEED_MPS,
    )
    tolerance = _bounded_metric_motion_value(
        payload,
        "reverse_target_tolerance_m",
        0.015,
        minimum=0.005,
        maximum=0.05,
    )
    lateral_tolerance = _bounded_metric_motion_value(
        payload,
        "reverse_target_lateral_tolerance_m",
        0.06,
        minimum=tolerance,
        maximum=0.10,
    )
    control_period = _bounded_metric_motion_value(
        payload,
        "reverse_control_period_sec",
        0.10,
        minimum=0.05,
        maximum=0.20,
    )
    require_aruco = bool(payload.get("reverse_require_aruco", False))
    try:
        target_pose = _validated_map_pose(
            target,
            label="saved metric return pose",
            source_max_age_sec=float(payload.get("return_pose_source_max_age_sec", 1.0)),
            captured_max_age_sec=float(payload.get("return_pose_max_age_sec", 180.0)),
        )
    except Exception:
        _abort_docking_motion()
        raise
    target_x = target_pose["x"]
    target_y = target_pose["y"]
    target_yaw = target_pose["yaw"]
    yaw_tolerance = max(
        0.001,
        abs(float(payload.get("return_pose_yaw_tolerance_rad", math.radians(5.0)))),
    )

    initial = _current_metric_map_pose(payload, label="metric reverse start pose")
    initial_distance = math.hypot(target_x - initial["x"], target_y - initial["y"])
    max_duration = _bounded_metric_motion_value(
        payload,
        "reverse_target_max_duration_sec",
        initial_distance / speed * 2.0 + 1.0,
        minimum=0.5,
        maximum=METRIC_DOCK_REVERSE_MAX_DURATION_SEC,
    )
    deadline = time.monotonic() + max_duration
    last_log = 0.0

    while time.monotonic() < deadline:
        try:
            pose = _current_metric_map_pose(payload, label="metric reverse live pose")
        except RuntimeError:
            runtime.navigator.publish_stop_velocity()
            raise
        dx = target_x - pose["x"]
        dy = target_y - pose["y"]
        distance = math.hypot(dx, dy)
        yaw = pose["yaw"]
        yaw_error = abs(_normalize_angle(yaw - target_yaw))
        if yaw_error > yaw_tolerance:
            runtime.navigator.publish_stop_velocity()
            raise RuntimeError(
                f"metric reverse yaw left the straight corridor: error={yaw_error:.3f}rad"
            )
        if distance <= tolerance:
            runtime.navigator.publish_stop_velocity()
            print(f"[dock_transfer] exact reverse reached ARRIVED pose (error={distance:.3f}m)")
            return True

        forward_error = dx * math.cos(target_yaw) + dy * math.sin(target_yaw)
        lateral_error = -dx * math.sin(target_yaw) + dy * math.cos(target_yaw)
        if forward_error > tolerance:
            runtime.navigator.publish_stop_velocity()
            raise RuntimeError("saved ARRIVED pose is not behind the robot")
        if abs(lateral_error) > lateral_tolerance:
            runtime.navigator.publish_stop_velocity()
            raise RuntimeError(
                f"saved ARRIVED pose is outside straight reverse corridor: lateral={lateral_error:.3f}m"
            )

        burst = min(control_period, max(0.05, distance / speed))
        if not _publish_docking_velocity(
            payload,
            "reverse",
            require_aruco=require_aruco,
            linear_x=-speed,
            angular_z=0.0,
            duration_sec=burst,
        ):
            runtime.navigator.publish_stop_velocity()
            return False
        now = time.monotonic()
        if now - last_log >= 1.0:
            print(
                f"[dock_transfer] exact reverse remaining={distance:.3f}m "
                f"lateral={lateral_error:+.3f}m"
            )
            last_log = now

    runtime.navigator.publish_stop_velocity()
    raise RuntimeError("exact dock reverse timed out before ARRIVED pose")


def execute_dock_reverse(payload: Dict[str, Any]):
    if not runtime.navigator:
        raise RuntimeError("runtime.navigator is not initialized")
    target = payload.get("return_target_pose")
    if isinstance(target, dict):
        return execute_reverse_to_map_pose(payload, target)
    speed = abs(float(payload.get("reverse_speed", DOCK_REVERSE_SPEED)))
    if speed <= 0.0:
        raise ValueError("reverse_speed must be greater than 0")
    distance = resolve_dock_reverse_distance_m(payload)
    duration = distance / speed if distance > 0.0 else 0.0
    if duration <= 0.0:
        raise ValueError("reverse_duration_sec or reverse_distance_m must be greater than 0")
    _require_docking_motion_or_abort(payload, "reverse")
    print(f"[dock_transfer] dock reverse speed={speed:.3f}m/s distance={distance:.3f}m duration={duration:.2f}s")
    # The marker is deliberately allowed to leave the camera frame after the
    # insert/lift completes.  Reverse remains fail-closed on fresh scan, TF,
    # localization, lift telemetry, and E-stop; requiring continuous ArUco here
    # turns a normal close-range field of view loss into a false task failure.
    result = _publish_docking_velocity(
        payload,
        "reverse",
        require_aruco=False,
        linear_x=-speed,
        angular_z=0.0,
        duration_sec=duration,
    )
    runtime.navigator.publish_stop_velocity()
    return result


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
    """leave_dock 후진 거리: 명시값 → 마커 40cm 이격 → 저장값 → 검증 fallback."""
    for key in ("distance_m", "reverse_distance_m"):
        if payload.get(key) is not None:
            return abs(float(payload[key]))

    marker_id = payload.get("aruco_marker_id")
    if marker_id is not None and runtime.navigator:
        detection = runtime.navigator.get_latest_aruco_detection(
            int(marker_id), max_age_sec=float(payload.get("reverse_marker_max_age_sec", 5.0))
        )
        if detection and detection.get("estimated_distance_m") is not None:
            try:
                current_marker_distance = float(detection["estimated_distance_m"])
                clearance_m = max(
                    0.05, float(payload.get("reverse_clearance_marker_distance_m", 0.40))
                )
                if math.isfinite(current_marker_distance) and current_marker_distance >= 0.0:
                    distance = max(0.0, clearance_m - current_marker_distance)
                    print(
                        f"[leave_dock] marker={int(marker_id)} current={current_marker_distance:.3f}m "
                        f"clearance={clearance_m:.3f}m reverse={distance:.3f}m"
                    )
                    return distance
            except (TypeError, ValueError):
                pass
    stored = runtime.get_standby_park_reverse_distance_m()
    if stored is not None and stored > 0.0:
        return stored
    fallback_m = max(0.05, float(payload.get("reverse_clearance_fallback_m", 0.20)))
    print(f"[leave_dock] marker unavailable; calibrated fallback={fallback_m:.3f}m")
    return fallback_m


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


def _fresh_pose_relation_to_parking(payload: Dict[str, Any]) -> str:
    """Return ``at_parking``, ``away_from_parking``, or ``unknown``."""
    parking_pose = payload.get("parking_pose")
    if not isinstance(parking_pose, dict) or not runtime.navigator:
        return "unknown"
    current = runtime.navigator.get_current_pose()
    if not isinstance(current, dict):
        return "unknown"
    try:
        age_sec = float(current.get("age_sec"))
        dx = float(current["x"]) - float(parking_pose["x"])
        dy = float(current["y"]) - float(parking_pose["y"])
        yaw_error = abs(
            _normalize_angle(float(current["yaw"]) - float(parking_pose["yaw"]))
        )
    except (KeyError, TypeError, ValueError):
        return "unknown"
    if not all(math.isfinite(value) for value in (age_sec, dx, dy, yaw_error)):
        return "unknown"
    max_age_sec = max(0.05, float(payload.get("parking_pose_max_age_sec", 2.0)))
    if not 0.0 <= age_sec <= max_age_sec:
        return "unknown"
    position_tolerance_m = max(
        0.02, float(payload.get("parking_position_tolerance_m", 0.18))
    )
    yaw_tolerance_rad = max(
        0.02, float(payload.get("parking_yaw_tolerance_rad", math.radians(20.0)))
    )
    at_parking = bool(
        math.hypot(dx, dy) <= position_tolerance_m
        and yaw_error <= yaw_tolerance_rad
    )
    return "at_parking" if at_parking else "away_from_parking"


def _fresh_marker_requires_leave_dock(
    detection: Optional[Dict[str, Any]], payload: Dict[str, Any]
) -> bool:
    if not detection:
        return False
    clearance_m = max(
        0.05, float(payload.get("reverse_clearance_marker_distance_m", 0.40))
    )
    distance = _metric_forward_distance(detection)
    if distance is not None:
        return distance < clearance_m - 0.005
    try:
        width_px = float(detection.get("marker_width_px", 0.0))
        min_width_px = float(
            payload.get("reverse_marker_min_width_px", ARUCO_DOCK_TARGET_WIDTH_PX)
        )
    except (TypeError, ValueError):
        return False
    return bool(
        math.isfinite(width_px)
        and math.isfinite(min_width_px)
        and width_px >= max(8.0, min_width_px)
    )


def execute_leave_dock_step(step: MovementStep):
    if not runtime.navigator:
        raise RuntimeError("runtime.navigator is not initialized")
    payload = step.payload
    force = bool(payload.get("force", False))
    parked = runtime.get_standby_parked()

    # Process-local parking state can be stale after a restart or physical
    # reposition. Prefer fresh physical evidence from the expected marker or
    # the authoritative map pose carried by Main.
    marker_id = payload.get("aruco_marker_id")
    detection = None
    if marker_id is not None:
        detection = runtime.navigator.get_latest_aruco_detection(
            int(marker_id), max_age_sec=float(payload.get("reverse_marker_max_age_sec", 5.0))
        )
    marker_requires_reverse = _fresh_marker_requires_leave_dock(detection, payload)
    pose_relation = _fresh_pose_relation_to_parking(payload)
    if force:
        reverse_required = True
        evidence = "operator_force"
    elif pose_relation == "at_parking":
        reverse_required = True
        evidence = "fresh_parking_pose"
    elif pose_relation == "away_from_parking":
        reverse_required = False
        evidence = "fresh_pose_away_from_parking"
    elif marker_requires_reverse:
        reverse_required = True
        evidence = "fresh_expected_marker"
    elif parked is True:
        reverse_required = True
        evidence = "process_parking_state"
    else:
        reverse_required = False
        evidence = "parking_not_confirmed"

    if not reverse_required:
        print(
            f"[leave_dock] reverse no-op: {evidence} "
            f"(standby_parked={parked}, marker={marker_id})"
        )
        runtime.set_standby_parked(False)
        return True

    duration_requested = (
        payload.get("duration_sec") is not None or payload.get("reverse_duration_sec") is not None
    ) and payload.get("distance_m") is None and payload.get("reverse_distance_m") is None
    if duration_requested:
        # Preserve the public API contract: an explicit duration remains a
        # time-based request even though the actuator now stops by measured distance.
        speed, duration = leave_dock_motion_params(payload)
        requested_distance = speed * duration
    else:
        requested_distance = resolve_leave_dock_distance_m(payload)
    if requested_distance <= 0.005:
        print("[leave_dock] marker clearance already satisfied; handoff=Nav2")
        runtime.navigator.publish_stop_velocity()
        runtime.set_standby_parked(False)
        return True
    if not duration_requested:
        speed, duration = leave_dock_motion_params(
            {**payload, "distance_m": requested_distance}
        )
    try:
        _require_docking_motion_or_abort(payload, "leave_dock")
    except Exception as exc:
        raise StageError("leave_dock", str(exc)) from exc
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
            if allowed < requested_distance:
                requested_distance = allowed
                duration = requested_distance / speed
                print(f"[leave_dock] 후방 여유 {rear:.2f}m → 후진거리 {allowed:.2f}m 로 제한")

    print(f"[leave_dock] reversing out speed={speed:.3f}m/s distance={requested_distance:.3f}m "
          f"(parked={parked}, evidence={evidence})")
    try:
        result = runtime.navigator.publish_velocity_for_distance(
            linear_x=-speed,
            distance_m=requested_distance,
            max_duration_sec=duration * 2.0 + 0.5,
            tolerance_m=float(payload.get("reverse_tolerance_m", 0.005)),
            stop_condition=lambda: (
                _require_docking_motion_or_abort(payload, "leave_dock", require_aruco=False) or None
            ),
        )
    except Exception:
        _abort_docking_motion()
        raise
    runtime.navigator.publish_stop_velocity()
    print(f"[leave_dock] reverse result={result}; handoff=Nav2")
    if isinstance(result, dict) and result.get("ok"):
        runtime.set_standby_parked(False)
        return True
    return False


def raise_if_estop(stage: str):
    if runtime.navigator and runtime.navigator.safety.estop:
        raise CommandAborted("estop", stage=stage)
    raise_if_command_canceled(stage)


def raise_if_command_canceled(stage: str) -> None:
    command_id = runtime.active_movement_command_id
    command = runtime.movement_commands.get(command_id) if command_id else None
    if command and command.get("state") in (
        "CANCEL_REQUESTED",
        "CANCELED",
        "CANCELLED",
        "STOP_UNCONFIRMED",
    ):
        raise CommandAborted("operator_cancel", stage=stage)


def execute_aruco_align_step(step: MovementStep):
    payload = step.payload
    normalize_aruco_payload(payload)
    if "aruco_marker_id" not in payload:
        raise ValueError("aruco_align step requires payload.aruco_marker_id")
    marker_id = int(payload["aruco_marker_id"])
    final = str(payload.get("final", "hold"))
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
        if final == "hold" and hold_fork_insert_enabled(payload) and has_capability("lift"):
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
        if hold_fork_insert_enabled(payload) and has_capability("lift"):
            try:
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
        elif hold_fork_insert_enabled(payload):
            # Charge/non-lift parking may align to a marker but never drive into a
            # fork slot or infer lift intent from final=hold.
            print("[aruco_align] non-lift profile: hold alignment complete; fork insert skipped")
        runtime.set_standby_parked(True)
        return True
    return True


def execute_dock_transfer_step(
    step: MovementStep, *, metric_docking_admitted: bool = False
):
    payload = step.payload
    normalize_aruco_payload(payload)
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
    if payload.get("metric_precision_insert") and not metric_docking_admitted:
        raise ValueError("metric docking requires a server-issued ARRIVED admission")
    apply_slot_fork_defaults(payload, marker_id)
    apply_slot_lift_defaults(payload, marker_id)
    apply_slot_aruco_defaults(payload, marker_id)
    if payload.get("metric_precision_insert"):
        payload.setdefault("skip_approach_yaw_rotate", True)
        payload.setdefault("align_mode", "skip")
    simulation = bool(
        payload.get("dry_run")
        or is_simulation_mode()
        or (runtime.mission_manager and runtime.mission_manager.dry_run)
    )
    if payload.get("metric_precision_insert") and not simulation:
        try:
            validate_metric_return_pose_preflight(payload)
        except Exception as exc:
            _abort_docking_motion()
            raise StageError("return_pose", str(exc)) from exc
    try:
        ensure_lift_ready_for_dock_transfer(simulation=simulation)
    except Exception as exc:
        raise StageError("lift_ready", str(exc)) from exc
    if simulation:
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
        if payload.get("metric_precision_insert"):
            insert_ok = execute_metric_precision_insert(payload)
        else:
            insert_ok = execute_fork_insert(payload)
        if not insert_ok:
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
