"""Robot-commands API to movement command adaptation."""
import json
import math
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from nav_app.models import MovementCommandRequest, MovementStep, RobotCommandRequest
from nav_app.runtime import runtime
from nav_app.services import capabilities
from nav_app.services.command_state import consume_arrived_gate as _consume_arrived_gate
from nav_app.services.robot_context import (
    active_bridge_robot_id as _active_bridge_robot_id,
)
from nav_app.settings import (
    ARUCO_DOCKING_TIMEOUT_SEC,
    GATE_TIMEOUT_SEC,
    METRIC_DOCK_CONTROL_PERIOD_SEC,
    METRIC_DOCK_ARUCO_MAX_AGE_SEC,
    METRIC_DOCK_FRESHNESS_SEGMENT_SEC,
    METRIC_DOCK_REVERSE_CONTROL_PERIOD_SEC,
    METRIC_DOCK_REVERSE_MAX_DURATION_SEC,
    METRIC_DOCK_REVERSE_MAX_SPEED_MPS,
    METRIC_DOCK_REVERSE_SPEED_MPS,
    METRIC_DOCK_SENSOR_MAX_AGE_SEC,
    ROBOTS_CONFIG_PATH,
    ROOT,
)

NAV_ARUCO_FINALS = {"hold", "return_approach"}
MAIN_ARUCO_FINAL_ALIASES = {"park": "hold", "charge": "hold"}
METRIC_DOCKING_RESERVED_FIELDS = {
    "camera_distance_insert",
    "metric_precision_insert",
    "metric_distance_only",
    "metric_docking_profile",
    "stage1_target_distance_m",
    "return_target_pose",
    "reverse_target_tolerance_m",
    "reverse_target_lateral_tolerance_m",
    "reverse_require_aruco",
    "target_lateral_offset_m",
    "target_marker_yaw_rad",
    "require_pose_quality",
    "max_reprojection_error_px",
}
METRIC_DOCKING_CLIENT_FIELDS = frozenset({
    "aruco_marker_id",
    "action",
    "level",
    "home_on_unload",
    "pre_insert_home",
    "pre_insert_lift_mm",
    "pre_insert_force_move",
})
CAMERA_DISTANCE_LEGACY_INSERT_FIELDS = (
    "fork_insert_distance_m",
    "insert_distance_m",
    "insert_stop_width_px",
    "insert_stop_marker_width_px",
    "insert_reference_start_width_px",
    "insert_extra_after_vision_m",
    "insert_extra_m",
    "fork_insert_extra_after_vision_m",
)


def normalize_aruco_final_payload(payload: Dict[str, Any]) -> None:
    """Normalize Main aruco_align final intent to Nav execution vocabulary.

    Main historically sends final=park/charge for standby intents. Nav execution
    only accepts final=hold/return_approach, so preserve the original Main intent
    for telemetry/debug while making the executable contract explicit.
    """
    raw_final = payload.get("final", "hold")
    final_text = str(raw_final).strip().lower()
    normalized = MAIN_ARUCO_FINAL_ALIASES.get(final_text, final_text)
    if normalized not in NAV_ARUCO_FINALS:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "aruco_align final must be hold, return_approach, park, or charge",
                "received_final": raw_final,
                "nav_supported_finals": sorted(NAV_ARUCO_FINALS),
                "main_final_aliases": MAIN_ARUCO_FINAL_ALIASES,
            },
        )
    if normalized != final_text:
        payload.setdefault("main_final_intent", raw_final)
        payload.setdefault("original_final", raw_final)
    payload["final"] = normalized


def load_zones_config():
    zones_path = ROOT / "map" / "zones.json"
    return json.loads(zones_path.read_text(encoding="utf-8"))


def load_waypoint_goals():
    return load_zones_config().get("waypoints", {})


def approach_waypoint_id_for_marker(marker_id: int) -> Optional[str]:
    """semantic_zones에서 marker_id에 대응하는 approach waypoint id를 찾는다."""
    for zone in load_zones_config().get("semantic_zones", {}).values():
        if zone.get("aruco_marker_id") != marker_id:
            continue
        waypoint_id = zone.get("approach_waypoint")
        if isinstance(waypoint_id, str):
            return waypoint_id
    return None


def lift_slot_levels_for_marker(marker_id: int) -> Dict[str, Any]:
    """zones.json approach waypoint의 lift_levels_mm (슬롯·level별 높이 override)."""
    waypoint_id = approach_waypoint_id_for_marker(marker_id)
    if not waypoint_id:
        return {}
    waypoint = load_waypoint_goals().get(waypoint_id) or {}
    levels = waypoint.get("lift_levels_mm")
    return levels if isinstance(levels, dict) else {}


def apply_slot_lift_defaults(payload: Dict[str, Any], marker_id: int) -> None:
    """dock_transfer payload에 슬롯별 리프트 높이를 zones.json에서 주입한다."""
    levels = lift_slot_levels_for_marker(marker_id)
    if not levels:
        return
    level_key = str(int(payload.get("level", 1)))
    entry = levels.get(level_key)
    if not isinstance(entry, dict):
        return
    for slot_key in ("pre_insert_mm", "load_height_mm", "unload_height_mm", "carry_height_mm"):
        if slot_key in entry and payload.get(slot_key) is None:
            value = entry[slot_key]
            if value is not None:
                payload[slot_key] = value


def aruco_align_defaults_for_marker(marker_id: int) -> Dict[str, Any]:
    """zones.json approach waypoint의 aruco_align 기본값을 반환한다."""
    waypoint_id = approach_waypoint_id_for_marker(marker_id)
    if not waypoint_id:
        return {}
    waypoint = load_waypoint_goals().get(waypoint_id) or {}
    defaults = waypoint.get("aruco_align")
    return defaults if isinstance(defaults, dict) else {}


def metric_two_stage_for_waypoint(waypoint_id: Optional[str]) -> Dict[str, Any]:
    """Return an enabled metric docking profile for a pallet-slot approach."""
    if not waypoint_id:
        return {}
    waypoint = load_waypoint_goals().get(str(waypoint_id)) or {}
    profile = waypoint.get("metric_two_stage")
    if not isinstance(profile, dict) or profile.get("enabled") is not True:
        return {}
    return dict(profile)


def _robot_profile(robot_id: str) -> Dict[str, Any]:
    """Load a robot from the configured manifest instead of a fixed file."""
    document = json.loads(ROBOTS_CONFIG_PATH.read_text(encoding="utf-8"))
    for profile in document.get("robots", []):
        if robot_id in (profile.get("robot_id"), profile.get("bridge_robot_id")):
            return dict(profile)
    return {}


def _config_path(value: Any) -> Optional[Path]:
    if not isinstance(value, str) or not value.strip():
        return None
    path = Path(value.strip())
    return path if path.is_absolute() else ROOT / path


def metric_pose_calibration_available(robot_id: str) -> bool:
    """Report camera calibration only; calibration never admits live motion alone."""
    metric = _robot_profile(robot_id).get("metric_docking")
    if not isinstance(metric, dict):
        return False
    calibration = _config_path(metric.get("camera_calibration"))
    return bool(calibration and calibration.is_file())


def metric_docking_live_config(robot_id: str) -> Dict[str, Any]:
    """Return a commissioned robot-scoped metric config or fail closed with {}."""
    robot = _robot_profile(robot_id)
    metric = robot.get("metric_docking")
    if not isinstance(metric, dict):
        return {}
    if metric.get("enabled") is not True or metric.get("live_enabled") is not True:
        return {}
    if metric.get("commissioning_status") != "COMMISSIONED":
        return {}
    calibration = _config_path(metric.get("camera_calibration"))
    camera_to_base = metric.get("camera_to_base")
    if not calibration or not calibration.is_file():
        return {}
    if not isinstance(camera_to_base, dict) or camera_to_base.get("measured") is not True:
        return {}
    try:
        lateral = float(camera_to_base["target_lateral_offset_m"])
        yaw = float(camera_to_base["target_marker_yaw_rad"])
        reprojection = float(metric.get("max_reprojection_error_px", 2.0))
        source_max_age = float(
            metric.get(
                "return_pose_source_max_age_sec",
                (robot.get("localization") or {}).get("max_tf_age_sec", 1.0),
            )
        )
        target_max_age = float(metric.get("return_pose_max_age_sec", GATE_TIMEOUT_SEC + 60.0))
        yaw_tolerance = float(metric.get("return_pose_yaw_tolerance_rad", math.radians(5.0)))
    except (KeyError, TypeError, ValueError):
        return {}
    values = (lateral, yaw, reprojection, source_max_age, target_max_age, yaw_tolerance)
    if not all(math.isfinite(value) for value in values):
        return {}
    if reprojection <= 0.0 or source_max_age <= 0.0 or target_max_age <= 0.0 or yaw_tolerance <= 0.0:
        return {}
    return {
        **metric,
        "camera_calibration": str(calibration),
        "target_lateral_offset_m": lateral,
        "target_marker_yaw_rad": yaw,
        "max_reprojection_error_px": reprojection,
        "return_pose_source_max_age_sec": source_max_age,
        "return_pose_max_age_sec": target_max_age,
        "return_pose_yaw_tolerance_rad": yaw_tolerance,
    }


def metric_docking_profile_for_robot(
    robot_id: str, waypoint_id: Optional[str]
) -> Dict[str, Any]:
    robot_metric = metric_docking_live_config(robot_id)
    waypoint_metric = metric_two_stage_for_waypoint(waypoint_id)
    if not robot_metric or not waypoint_metric:
        return {}
    return {
        **waypoint_metric,
        "target_lateral_offset_m": robot_metric["target_lateral_offset_m"],
        "target_marker_yaw_rad": robot_metric["target_marker_yaw_rad"],
        "require_pose_quality": True,
        "max_reprojection_error_px": robot_metric["max_reprojection_error_px"],
        "return_pose_source_max_age_sec": robot_metric["return_pose_source_max_age_sec"],
        "return_pose_max_age_sec": robot_metric["return_pose_max_age_sec"],
        "return_pose_yaw_tolerance_rad": robot_metric["return_pose_yaw_tolerance_rad"],
    }


def _strip_metric_docking_reserved_fields(payload: Dict[str, Any]) -> None:
    for field in METRIC_DOCKING_RESERVED_FIELDS:
        payload.pop(field, None)


def strip_camera_distance_legacy_insert_fields(payload: Dict[str, Any]) -> None:
    for field in CAMERA_DISTANCE_LEGACY_INSERT_FIELDS:
        payload.pop(field, None)


def _metric_profile_float(
    profile: Dict[str, Any],
    field: str,
    default: float,
    *,
    minimum: float,
    maximum: Optional[float],
) -> float:
    try:
        value = float(profile.get(field, default))
    except (TypeError, ValueError):
        value = math.nan
    if not math.isfinite(value) or value < minimum or (
        maximum is not None and value > maximum
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "metric_docking_profile_invalid",
                "message": f"metric docking profile field {field} is outside its valid range",
                "field": field,
                "minimum": minimum,
                "maximum": maximum,
            },
        )
    return value


def camera_distance_insert_profile_for_robot(
    robot_id: str, marker_id: int
) -> Dict[str, Any]:
    """Build the dock-only camera-distance contract for a calibrated robot."""
    robot = _robot_profile(robot_id)
    metric = robot.get("metric_docking")
    detector = robot.get("aruco_detector")
    if not isinstance(metric, dict) or metric.get("enabled") is not True:
        return {}
    if not isinstance(detector, dict) or detector.get("transport") != "ros_topic":
        return {}
    if not metric_pose_calibration_available(robot_id):
        return {}

    waypoint_id = approach_waypoint_id_for_marker(int(marker_id))
    profile = metric_two_stage_for_waypoint(waypoint_id)
    if not profile:
        return {}

    target = _metric_profile_float(
        profile, "stage2_target_distance_m", 0.20, minimum=0.10, maximum=0.30
    )
    tolerance = _metric_profile_float(
        profile, "metric_distance_tolerance_m", 0.02, minimum=0.005, maximum=0.05
    )
    center_tolerance = _metric_profile_float(
        profile, "center_tolerance_norm", 0.03, minimum=0.005, maximum=0.15
    )
    linear_speed = _metric_profile_float(
        profile, "dock_linear_speed", 0.018, minimum=0.005, maximum=0.03
    )
    min_linear_speed = _metric_profile_float(
        profile,
        "dock_min_linear_speed",
        0.006,
        minimum=0.001,
        maximum=linear_speed,
    )
    return {
        "camera_distance_insert": True,
        "aruco_observation_transport": "ros_topic",
        "metric_distance_only": True,
        "target_distance_m": target,
        "metric_distance_tolerance_m": tolerance,
        "center_tolerance_norm": center_tolerance,
        "forward_center_tolerance_norm": center_tolerance,
        "dock_linear_speed": linear_speed,
        "dock_min_linear_speed": min_linear_speed,
        "control_period_sec": _metric_profile_float(
            profile,
            "control_period_sec",
            METRIC_DOCK_CONTROL_PERIOD_SEC,
            minimum=0.05,
            maximum=0.20,
        ),
        "docking_timeout_sec": _metric_profile_float(
            profile,
            "docking_timeout_sec",
            ARUCO_DOCKING_TIMEOUT_SEC,
            minimum=1.0,
            maximum=None,
        ),
        "straight_when_normal_aligned": True,
        "require_normal_alignment": False,
        "allow_marker_lost_at_insert_start": False,
        "marker_lost_grace_sec": 0.0,
        "fork_insert_enabled": False,
        "insert_vision_stop": False,
        "close_from_marker_width_only": False,
        "use_good_enough": False,
    }


def _admit_server_metric_request(request: MovementCommandRequest) -> MovementCommandRequest:
    if any(
        isinstance(step.payload.get("metric_docking_profile"), dict)
        or step.payload.get("metric_precision_insert") is True
        or step.payload.get("camera_distance_insert") is True
        for step in request.steps
    ):
        request.admit_metric_docking()
    return request


def apply_metric_docking_gate(payload: Dict[str, Any], gate: Dict[str, Any]) -> bool:
    """Carry a server-recorded 0.40 m ARRIVED pose into precision transfer."""
    profile = gate.get("metric_docking_profile")
    arrived_return_pose = gate.get("arrived_return_pose")
    if not isinstance(profile, dict) or profile.get("enabled") is not True:
        return False
    if (
        not isinstance(arrived_return_pose, dict)
        or arrived_return_pose.get("x") is None
        or arrived_return_pose.get("y") is None
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "metric_docking_return_pose_missing",
                "message": "metric dock_transfer requires the preceding 0.40m ARRIVED return pose",
            },
        )
    arrived_marker = gate.get("arrived_marker_id")
    requested_marker = payload.get("aruco_marker_id")
    if arrived_marker is None or requested_marker is None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "metric_docking_marker_missing",
                "message": "metric dock_transfer requires marker IDs in both ARRIVED gate and request",
            },
        )
    if int(arrived_marker) != int(requested_marker):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "metric_docking_marker_mismatch",
                "message": "dock_transfer marker differs from the preceding 0.40m ARRIVED gate",
            },
        )

    stage1 = _metric_profile_float(
        profile, "stage1_target_distance_m", 0.40, minimum=0.25, maximum=0.60
    )
    stage2 = _metric_profile_float(
        profile, "stage2_target_distance_m", 0.20, minimum=0.10, maximum=0.30
    )
    if stage2 >= stage1:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "metric_docking_profile_invalid",
                "message": "metric docking requires stage2_target_distance_m < stage1_target_distance_m",
            },
        )
    dock_linear_speed = _metric_profile_float(
        profile, "dock_linear_speed", 0.018, minimum=0.005, maximum=0.03
    )
    dock_min_linear_speed = _metric_profile_float(
        profile,
        "dock_min_linear_speed",
        0.006,
        minimum=0.001,
        maximum=dock_linear_speed,
    )
    control_period = _metric_profile_float(
        profile,
        "control_period_sec",
        METRIC_DOCK_CONTROL_PERIOD_SEC,
        minimum=0.05,
        maximum=0.20,
    )
    freshness_segment = _metric_profile_float(
        profile,
        "docking_freshness_segment_sec",
        METRIC_DOCK_FRESHNESS_SEGMENT_SEC,
        minimum=0.02,
        maximum=0.20,
    )
    scan_max_age = _metric_profile_float(
        profile,
        "scan_max_age_sec",
        METRIC_DOCK_SENSOR_MAX_AGE_SEC,
        minimum=0.05,
        maximum=1.0,
    )
    tf_max_age = _metric_profile_float(
        profile,
        "tf_max_age_sec",
        METRIC_DOCK_SENSOR_MAX_AGE_SEC,
        minimum=0.05,
        maximum=1.0,
    )
    aruco_max_age = _metric_profile_float(
        profile,
        "aruco_max_age_sec",
        METRIC_DOCK_ARUCO_MAX_AGE_SEC,
        minimum=0.05,
        maximum=METRIC_DOCK_ARUCO_MAX_AGE_SEC,
    )
    reverse_speed = _metric_profile_float(
        profile,
        "reverse_speed",
        METRIC_DOCK_REVERSE_SPEED_MPS,
        minimum=0.01,
        maximum=METRIC_DOCK_REVERSE_MAX_SPEED_MPS,
    )
    reverse_control_period = _metric_profile_float(
        profile,
        "reverse_control_period_sec",
        METRIC_DOCK_REVERSE_CONTROL_PERIOD_SEC,
        minimum=0.05,
        maximum=0.20,
    )
    reverse_duration_default = max(2.0, (stage1 - stage2) / reverse_speed * 2.0 + 1.0)
    reverse_max_duration = _metric_profile_float(
        profile,
        "reverse_target_max_duration_sec",
        reverse_duration_default,
        minimum=0.5,
        maximum=METRIC_DOCK_REVERSE_MAX_DURATION_SEC,
    )
    payload.update(
        {
            "metric_precision_insert": True,
            "metric_distance_only": True,
            "metric_docking_profile": dict(profile),
            "stage1_target_distance_m": stage1,
            "target_distance_m": stage2,
            "return_target_pose": dict(arrived_return_pose),
            "fork_insert_enabled": False,
            "insert_vision_stop": False,
            "require_normal_alignment": bool(profile.get("require_normal_alignment", True)),
            "straight_when_normal_aligned": bool(profile.get("straight_when_normal_aligned", True)),
            "close_from_marker_width_only": False,
            "use_good_enough": False,
            "control_period_sec": control_period,
            "docking_freshness_segment_sec": freshness_segment,
            "scan_max_age_sec": scan_max_age,
            "tf_max_age_sec": tf_max_age,
            "aruco_max_age_sec": aruco_max_age,
            "dock_linear_speed": dock_linear_speed,
            "dock_min_linear_speed": dock_min_linear_speed,
            "normal_realign_timeout_sec": _metric_profile_float(
                profile, "normal_realign_timeout_sec", 20.0, minimum=1.0, maximum=30.0
            ),
            "docking_timeout_sec": _metric_profile_float(
                profile,
                "docking_timeout_sec",
                ARUCO_DOCKING_TIMEOUT_SEC,
                minimum=1.0,
                maximum=None,
            ),
            "reverse_speed": reverse_speed,
            "reverse_control_period_sec": reverse_control_period,
            "reverse_target_max_duration_sec": reverse_max_duration,
        }
    )
    for key, default, minimum, maximum in (
        ("center_tolerance_norm", 0.03, 0.005, 0.15),
        ("coarse_center_tolerance_norm", 0.14, 0.03, 0.40),
        ("normal_lateral_tolerance_m", 0.04, 0.005, 0.15),
        ("normal_yaw_tolerance_rad", 0.08726646, 0.005, 0.35),
        ("normal_coarse_lateral_m", 0.10, 0.02, 0.30),
        ("normal_coarse_yaw_rad", 0.22, 0.05, 0.60),
        ("dock_angular_gain", 0.45, 0.05, 2.0),
        ("dock_max_angular_speed", 0.16, 0.02, 0.30),
        ("metric_distance_tolerance_m", 0.02, 0.005, 0.05),
        ("target_lateral_offset_m", 0.0, -0.30, 0.30),
        ("target_marker_yaw_rad", 0.0, -1.0, 1.0),
        ("max_reprojection_error_px", 2.0, 0.1, 5.0),
        ("return_pose_source_max_age_sec", 1.0, 0.05, 1.0),
        ("return_pose_max_age_sec", GATE_TIMEOUT_SEC + 60.0, 1.0, 300.0),
        ("return_pose_yaw_tolerance_rad", math.radians(5.0), 0.005, 0.35),
        ("reverse_target_tolerance_m", 0.015, 0.005, 0.05),
        ("reverse_target_lateral_tolerance_m", 0.06, 0.01, 0.10),
    ):
        payload[key] = _metric_profile_float(
            profile,
            key,
            default,
            minimum=minimum,
            maximum=maximum,
        )
    payload["require_pose_quality"] = bool(profile.get("require_pose_quality", True))
    # The validated Nav baseline reverses to the saved 0.40 m map pose.  The
    # marker may naturally leave the close-range camera view after lift action,
    # so reverse remains guarded by map pose, scan/TF freshness, lift telemetry,
    # and E-stop rather than continuous ArUco visibility.
    payload["reverse_require_aruco"] = bool(profile.get("reverse_require_aruco", False))
    return True


def apply_slot_aruco_defaults(payload: Dict[str, Any], marker_id: int) -> None:
    """dock_transfer도 approach와 같은 슬롯별 ArUco close 기준을 사용한다."""
    for key, value in aruco_align_defaults_for_marker(marker_id).items():
        if payload.get(key) is None:
            payload[key] = value


def fork_insert_distance_for_marker(marker_id: int) -> Optional[float]:
    """zones.json approach waypoint에 저장된 슬롯별 fork_insert_distance_m을 반환한다."""
    waypoint_id = approach_waypoint_id_for_marker(marker_id)
    if not waypoint_id:
        return None
    waypoint = load_waypoint_goals().get(waypoint_id)
    if not waypoint:
        return None
    value = waypoint.get("fork_insert_distance_m")
    if value is None:
        return None
    try:
        distance = float(value)
    except (TypeError, ValueError):
        return None
    return distance if distance > 0.0 else None


def approach_yaw_for_marker(marker_id: int) -> Optional[float]:
    waypoint_id = approach_waypoint_id_for_marker(marker_id)
    if not waypoint_id:
        return None
    waypoint = load_waypoint_goals().get(waypoint_id)
    if not waypoint:
        return None
    return float(waypoint.get("theta", waypoint.get("yaw", 0.0)) or 0.0)


def approach_yaw_for_waypoint(waypoint_id: Optional[str]) -> Optional[float]:
    if not waypoint_id:
        return None
    waypoint = load_waypoint_goals().get(str(waypoint_id))
    if not waypoint:
        return None
    return float(waypoint.get("theta", waypoint.get("yaw", 0.0)) or 0.0)


def semantic_zone_for_approach(waypoint_id: str) -> Optional[Dict[str, Any]]:
    for zone in load_zones_config().get("semantic_zones", {}).values():
        if zone.get("approach_waypoint") == waypoint_id:
            return zone
    return None


def is_wall_adjacent_approach(waypoint_id: Optional[str]) -> bool:
    """입고/출고/하단벽 슬롯처럼 ArUco를 보려면 벽에 밀착해야 하는 approach."""
    if not waypoint_id:
        return False
    wp = str(waypoint_id)
    if wp.startswith(("inbound_slot_", "outbound_slot_")):
        return True
    # robot2_map 하단 행 창고 슬롯 (A/B): approach y<0, 마커 정면(+x) 도킹
    if wp in ("warehouse_a_approach", "warehouse_b_approach"):
        return True
    zone = semantic_zone_for_approach(wp)
    if not zone:
        return False
    role = str(zone.get("role", ""))
    return role.startswith("inbound") or role.startswith("outbound")


def align_mode_for_approach_waypoint(waypoint_id: Optional[str]) -> str:
    """벽 밀착 슬롯: full_center(회전·마커만, 전진 없음). insert가 유일한 전진."""
    if is_wall_adjacent_approach(waypoint_id):
        return "full_center"
    return "center_only"


def align_mode_for_hold_park(marker_id: int) -> str:
    """hold 주차: 대기장 center_only, 벽 밀착 full_center."""
    waypoint_id = approach_waypoint_id_for_marker(marker_id)
    if waypoint_id and str(waypoint_id).startswith("vehicle_"):
        return "center_only"
    if is_wall_adjacent_approach(waypoint_id):
        return "full_center"
    return "center_only"


def align_mode_for_dock_marker(marker_id: int) -> str:
    """dock_transfer: 벽 밀착 full_center(정렬 전진 생략) → fork_insert만 전진."""
    return align_mode_for_hold_park(marker_id)


def marker_id_for_approach_waypoint(waypoint_id: str) -> Optional[int]:
    """approach waypoint id에 대응하는 ArUco marker_id를 semantic_zones에서 찾는다."""
    for zone in load_zones_config().get("semantic_zones", {}).values():
        if zone.get("approach_waypoint") != waypoint_id:
            continue
        marker_id = zone.get("aruco_marker_id")
        if marker_id is not None:
            return int(marker_id)
    return None


def is_aruco_chained_approach(waypoint_id: Optional[str]) -> bool:
    """ArUco approach/dock가 있는 waypoint면 Nav2 후 aruco_align을 체인 (슬롯·대기장 포함)."""
    if not waypoint_id or not str(waypoint_id).endswith("_approach"):
        return False
    wp = str(waypoint_id)
    if wp.endswith("_entry"):
        return False
    return marker_id_for_approach_waypoint(wp) is not None


def is_slot_docking_approach(waypoint_id: Optional[str]) -> bool:
    """입고/출고/창고 슬롯 approach (vehicle 대기장 제외)."""
    if not is_aruco_chained_approach(waypoint_id):
        return False
    wp = str(waypoint_id)
    return not wp.startswith("vehicle_")


def docking_approach_goal_overrides(waypoint_id: Optional[str]) -> Dict[str, float]:
    """*_approach waypoint Nav2 도착 검증 허용치 (슬롯·대기장 포함)."""
    from nav_app.settings import (
        NAV_APPROACH_SOFT_XY_TOLERANCE_M,
        NAV_APPROACH_SOFT_YAW_TOLERANCE_RAD,
        NAV_APPROACH_XY_TOLERANCE_M,
        NAV_APPROACH_YAW_TOLERANCE_RAD,
        NAV_WALL_APPROACH_SOFT_XY_TOLERANCE_M,
    )

    if not waypoint_id or not str(waypoint_id).endswith("_approach"):
        return {}
    overrides = {
        "xy_tolerance_m": NAV_APPROACH_XY_TOLERANCE_M,
        "yaw_tolerance_rad": NAV_APPROACH_YAW_TOLERANCE_RAD,
        "soft_xy_tolerance_m": NAV_APPROACH_SOFT_XY_TOLERANCE_M,
        "soft_yaw_tolerance_rad": NAV_APPROACH_SOFT_YAW_TOLERANCE_RAD,
    }
    # 슬롯 approach: Nav2는 xy만 맞추고 yaw는 ArUco가 담당 (벽 앞에서 Nav2 yaw 보정 시 전진 충돌 방지)
    if is_slot_docking_approach(waypoint_id):
        overrides["nav_position_only"] = True
        overrides["yaw_tolerance_rad"] = None
        overrides["relax_forward_clearance"] = True
        if is_wall_adjacent_approach(waypoint_id):
            overrides["soft_xy_tolerance_m"] = NAV_WALL_APPROACH_SOFT_XY_TOLERANCE_M
    elif str(waypoint_id).startswith("vehicle_"):
        # 대기장: xy 정밀 Nav2 + center_only ArUco (full 전진은 마커 방향으로 비스듬히 벽 충돌)
        overrides["nav_position_only"] = True
        overrides["yaw_tolerance_rad"] = None
        overrides["relax_forward_clearance"] = True
    wp_cfg = load_waypoint_goals().get(str(waypoint_id)) or {}
    for goal_key, wp_key in (
        ("xy_tolerance_m", "xy_tolerance_m"),
        ("soft_xy_tolerance_m", "soft_xy_tolerance_m"),
        ("soft_yaw_tolerance_rad", "soft_yaw_tolerance_rad"),
    ):
        if wp_key in wp_cfg and wp_cfg[wp_key] is not None:
            overrides[goal_key] = float(wp_cfg[wp_key])
    return overrides


def goal_from_waypoint_id(waypoint_id: str):
    waypoints = load_waypoint_goals()
    waypoint = waypoints.get(waypoint_id)
    if not waypoint:
        valid = sorted(waypoints.keys())
        raise HTTPException(
            status_code=400,
            detail={
                "message": f"unknown waypoint_id: {waypoint_id}",
                "valid_waypoint_ids": valid,
            },
        )
    goal = {
        "x": float(waypoint["x"]),
        "y": float(waypoint["y"]),
        "yaw": float(waypoint.get("theta", waypoint.get("yaw", 0.0))),
        "waypoint": waypoint_id,
        "role": waypoint.get("role"),
    }
    goal.update(docking_approach_goal_overrides(waypoint_id))
    return goal


def traffic_segments_for_waypoint_id(waypoint_id: Optional[str]):
    if not waypoint_id:
        return []
    data = load_zones_config()
    segments = []

    for segment_id, segment in data.get("traffic_segments", {}).items():
        waypoint_refs = []
        for key in ("entry_waypoints", "right_hand_waypoints"):
            values = segment.get(key)
            if isinstance(values, list):
                waypoint_refs.extend(values)
        yield_waypoint = segment.get("yield_waypoint")
        if isinstance(yield_waypoint, str):
            waypoint_refs.append(yield_waypoint)
        if waypoint_id in waypoint_refs and segment_id not in segments:
            segments.append(segment_id)

    for zone in data.get("semantic_zones", {}).values():
        if waypoint_id not in (zone.get("approach_waypoint"), zone.get("dock_waypoint")):
            continue
        role = str(zone.get("role", ""))
        kind = str(zone.get("kind", ""))
        if role.startswith("inbound"):
            candidate = "inbound_lane"
        elif role.startswith("outbound"):
            candidate = "outbound_lane"
        elif kind in ("inventory_section", "waiting_charging") or role.startswith("slot_"):
            candidate = "warehouse_aisle"
        else:
            candidate = None
        if candidate and candidate not in segments:
            segments.append(candidate)

    return segments


def traffic_segments_from_move_params(params: Dict[str, Any], goal: Dict[str, Any]):
    explicit = params.get("traffic_segments")
    if isinstance(explicit, list):
        return [segment for segment in explicit if isinstance(segment, str)]
    waypoint_id = params.get("waypoint_id") or params.get("waypoint") or goal.get("waypoint")
    return traffic_segments_for_waypoint_id(str(waypoint_id) if waypoint_id else None)


def goal_from_move_to_point_params(params: Dict[str, Any]):
    waypoint_id = params.get("waypoint_id") or params.get("waypoint")
    has_xy = "x" in params and "y" in params
    if has_xy:
        goal = {
            "x": float(params["x"]),
            "y": float(params["y"]),
            "yaw": float(params.get("yaw", params.get("theta", 0.0)) or 0.0),
            "waypoint": waypoint_id or "move_to_point",
        }
        if waypoint_id:
            goal.update(docking_approach_goal_overrides(str(waypoint_id)))
        for key in (
            "nav_position_only",
            "relax_forward_clearance",
            "xy_tolerance_m",
            "yaw_tolerance_rad",
            "soft_xy_tolerance_m",
            "soft_yaw_tolerance_rad",
        ):
            if key in params:
                goal[key] = params[key]
        return goal
    if waypoint_id:
        return goal_from_waypoint_id(str(waypoint_id))
    raise HTTPException(
        status_code=400,
        detail="move_to_point requires either params.x and params.y, or params.waypoint_id",
    )


def prepend_leave_dock_if_parked(steps: List[MovementStep]) -> List[MovementStep]:
    """hold 주차(standby_parked) 상태에서 move_to_point 시 먼저 후진 이탈."""
    if not runtime.get_standby_parked():
        return steps
    return [
        MovementStep(action="leave_dock", payload={"reason": "auto_before_nav"}),
        *steps,
    ]


def move_to_point_steps(req: RobotCommandRequest, goal: Dict[str, Any], traffic_segments: List[str]):
    """approach waypoint면 Nav2 후 마커 중앙 정렬(aruco_align)을 자동 체인한다."""
    waypoint_id = goal.get("waypoint")
    marker_id = (
        marker_id_for_approach_waypoint(str(waypoint_id))
        if is_aruco_chained_approach(str(waypoint_id) if waypoint_id else None)
        else None
    )
    shared = {
        "dry_run": req.dry_run,
        "gate_timeout_sec": (req.params or {}).get("gate_timeout_sec", GATE_TIMEOUT_SEC),
        "traffic_segments": traffic_segments,
    }
    nav_step = MovementStep(
        action="nav2_pose",
        payload={"frame_id": "map", "goal": goal, **shared},
    )
    if marker_id is None:
        nav_step.payload["terminal_state"] = "ARRIVED"
        return prepend_leave_dock_if_parked([nav_step])

    align_mode = align_mode_for_approach_waypoint(str(waypoint_id) if waypoint_id else None)
    align_payload = {
            "aruco_marker_id": marker_id,
            "align_mode": align_mode,
            "final": "return_approach",
            "terminal_state": "ARRIVED",
            "marker_search_on_miss": True,
            # Nav2 xy → map yaw → (마커 보이면 full align / 없으면 monotonic seek)
            "marker_search_timeout_sec": 60 if is_wall_adjacent_approach(str(waypoint_id) if waypoint_id else None) else 45,
            "docking_timeout_sec": ARUCO_DOCKING_TIMEOUT_SEC,
            "marker_centering_angular_speed": 0.12,
            **shared,
        }
    if is_wall_adjacent_approach(str(waypoint_id) if waypoint_id else None):
        align_payload["dock_max_angular_speed"] = 0.12
        align_payload["wall_adjacent_approach"] = True
        align_payload["marker_seek_mode"] = "monotonic"
        align_payload["marker_search_angular_speed"] = 0.12
    waypoint_cfg = load_waypoint_goals().get(str(waypoint_id)) if waypoint_id else None
    if isinstance(waypoint_cfg, dict):
        aruco_overrides = waypoint_cfg.get("aruco_align")
        if isinstance(aruco_overrides, dict):
            align_payload.update({k: v for k, v in aruco_overrides.items() if v is not None})
    align_step = MovementStep(
        action="aruco_align",
        payload=align_payload,
    )
    return prepend_leave_dock_if_parked([nav_step, align_step])


def movement_request_from_robot_command(
    req: RobotCommandRequest,
    *,
    allow_runtime_test_dock_transfer: bool = False,
):
    if req.robot_id != _active_bridge_robot_id():
        raise HTTPException(
            status_code=409,
            detail=(
                f"이 Movement API 프로세스는 {_active_bridge_robot_id()}만 담당합니다. "
                f"{req.robot_id} 명령은 해당 robot_id 프로세스로 보내야 합니다."
            ),
        )
    kind = req.kind.strip().lower()
    params = dict(req.params or {})
    if kind == "move_to_point":
        goal = goal_from_move_to_point_params(params)
        traffic_segments = traffic_segments_from_move_params(params, goal)
        return _admit_server_metric_request(MovementCommandRequest(
            command_id=req.command_id,
            task_id=req.task_id,
            robot_name=req.robot_id,
            steps=move_to_point_steps(req, goal, traffic_segments),
            callback_url=req.callback_url,
        ))
    if kind == "dock_transfer":
        capabilities.ensure_dock_transfer_supported(
            allow_runtime_test_grant=allow_runtime_test_dock_transfer,
        )
        gate = _consume_arrived_gate(req.robot_id)
        metric_gate = isinstance(gate.get("metric_docking_profile"), dict)
        if metric_gate and not metric_docking_live_config(req.robot_id):
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "metric_docking_not_commissioned",
                    "message": "metric docking commissioning is not currently admitted for this robot",
                },
            )
        client_params = (
            {key: params[key] for key in METRIC_DOCKING_CLIENT_FIELDS if key in params}
            if metric_gate
            else params
        )
        dock_payload = {**client_params, "terminal_state": "DONE", "dry_run": req.dry_run, "gate_source_command_id": gate.get("command_id"), "traffic_segments": gate.get("traffic_segments", [])}
        _strip_metric_docking_reserved_fields(dock_payload)
        apply_metric_docking_gate(dock_payload, gate)
        marker_id = dock_payload.get("aruco_marker_id")
        if marker_id is not None and "align_mode" not in dock_payload:
            dock_payload["align_mode"] = align_mode_for_dock_marker(int(marker_id))
        dock_payload.setdefault("use_good_enough", False)
        dock_payload.setdefault("wall_adjacent_approach", False)
        if marker_id is not None:
            wp = approach_waypoint_id_for_marker(int(marker_id))
            if is_wall_adjacent_approach(wp):
                dock_payload["wall_adjacent_approach"] = True
                dock_payload.setdefault("relax_forward_clearance", True)
            if not metric_gate:
                camera_profile = camera_distance_insert_profile_for_robot(
                    req.robot_id, int(marker_id)
                )
                if camera_profile:
                    dock_payload.update(camera_profile)
                    strip_camera_distance_legacy_insert_fields(dock_payload)
        if dock_payload.get("metric_precision_insert"):
            dock_payload["align_mode"] = "skip"
            dock_payload["skip_approach_yaw_rotate"] = True
            dock_payload["marker_search_on_miss"] = False
            dock_payload["pre_insert_center_cycles"] = 0
        elif gate.get("post_align_done"):
            dock_payload["align_mode"] = "skip"
            dock_payload["skip_approach_yaw_rotate"] = True
            dock_payload.setdefault("require_center_before_insert", False)
            dock_payload.setdefault("marker_search_on_miss", False)
            dock_payload.setdefault("pre_insert_center_cycles", 0)
        return _admit_server_metric_request(MovementCommandRequest(
            command_id=req.command_id,
            task_id=req.task_id,
            robot_name=req.robot_id,
            steps=[MovementStep(action="dock_transfer", payload=dock_payload)],
            callback_url=req.callback_url,
        ))
    if kind == "aruco_align":
        gate = _consume_arrived_gate(req.robot_id)
        align_payload = {
            **params,
            "terminal_state": "DONE",
            "dry_run": req.dry_run,
            "gate_source_command_id": gate.get("command_id"),
            "traffic_segments": gate.get("traffic_segments", []),
        }
        normalize_aruco_final_payload(align_payload)
        if gate.get("post_align_done"):
            align_payload["skip_approach_yaw_rotate"] = True
        if gate.get("post_align_done") and "align_mode" not in params:
            align_payload["align_mode"] = "skip"
        return MovementCommandRequest(
            command_id=req.command_id,
            task_id=req.task_id,
            robot_name=req.robot_id,
            steps=[MovementStep(action="aruco_align", payload=align_payload)],
            callback_url=req.callback_url,
        )
    if kind in ("leave_dock", "undock"):
        return MovementCommandRequest(
            command_id=req.command_id,
            task_id=req.task_id,
            robot_name=req.robot_id,
            steps=[MovementStep(action="leave_dock", payload={**params, "terminal_state": "DONE", "dry_run": req.dry_run})],
            callback_url=req.callback_url,
        )
    if kind == "reverse_out":
        return MovementCommandRequest(
            command_id=req.command_id,
            task_id=req.task_id,
            robot_name=req.robot_id,
            steps=[MovementStep(action="slot_reverse_out", payload={**params, "terminal_state": "DONE", "dry_run": req.dry_run})],
            callback_url=req.callback_url,
        )
    if kind == "manual_drive":
        command = str(params.get("command", "stop"))
        return MovementCommandRequest(
            command_id=req.command_id,
            task_id=req.task_id,
            robot_name=req.robot_id,
            steps=[MovementStep(action="manual_drive", command=command, duration=params.get("hold") or params.get("timeout_sec"), payload={**params, "dry_run": req.dry_run})],
            callback_url=req.callback_url,
        )
    if kind == "estop":
        op = str(params.get("op", "stop"))
        return MovementCommandRequest(
            command_id=req.command_id,
            task_id=req.task_id,
            robot_name=req.robot_id,
            steps=[MovementStep(action="estop", command=op, payload={**params, "dry_run": req.dry_run})],
            callback_url=req.callback_url,
        )
    raise HTTPException(status_code=400, detail=f"unsupported robot command kind: {req.kind}")
