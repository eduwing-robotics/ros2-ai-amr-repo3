"""Config validation helpers (ROS-free)."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

ROBOT_REQUIRED_FIELDS: Sequence[str] = (
    "robot_id",
    "bridge_robot_id",
    "ros_domain_id",
    "center_domain_id",
    "namespace",
    "teleop_command_topic",
    "camera_topic",
    "active_map_yaml",
    "localization",
)

ROBOT_UNIQUE_FIELDS: Sequence[str] = (
    "robot_id",
    "bridge_robot_id",
    "ros_domain_id",
    "namespace",
    "api_port",
)

MAIN_ROUTE_ROBOT_REQUIRED_FIELDS: Sequence[str] = (
    "robot_id",
    "bridge_robot_id",
    "ros_domain_id",
    "nav_api_url",
)


def _append_unique_errors(robots: List[Dict[str, Any]], field: str, errors: List[str]) -> None:
    seen: Dict[Any, str] = {}
    for robot in robots:
        value = robot.get(field)
        if value in (None, ""):
            continue
        robot_id = str(robot.get("robot_id", "<unknown>"))
        if value in seen:
            errors.append(f"{field} duplicate: {value} ({seen[value]} / {robot_id})")
        else:
            seen[value] = robot_id


def _validate_number(robot_id: str, lift: Mapping[str, Any], field: str, errors: List[str], minimum: float = 0.0) -> None:
    if field not in lift:
        return
    try:
        value = float(lift[field])
    except (TypeError, ValueError):
        errors.append(f"{robot_id}: {field} must be numeric")
        return
    if not math.isfinite(value) or value < minimum:
        errors.append(f"{robot_id}: {field} must be >= {minimum}")


def _validate_finite_number(
    robot_id: str,
    values: Mapping[str, Any],
    field: str,
    errors: List[str],
) -> None:
    if field not in values:
        return
    try:
        value = float(values[field])
    except (TypeError, ValueError):
        errors.append(f"{robot_id}: {field} must be numeric")
        return
    if not math.isfinite(value):
        errors.append(f"{robot_id}: {field} must be finite")


def _integer(value: Any) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean is not an integer setting")
    number = float(value)
    if not math.isfinite(number) or not number.is_integer():
        raise ValueError("non-integral setting")
    return int(number)


def validate_lift_config(robot_id: str, lift: Any) -> List[str]:
    errors: List[str] = []
    if lift in (None, ""):
        return errors
    if not isinstance(lift, Mapping):
        return [f"{robot_id}: lift must be an object"]
    if not isinstance(lift.get("enabled", False), bool):
        errors.append(f"{robot_id}: lift.enabled must be boolean")
    topics = lift.get("topics")
    if topics is not None:
        if not isinstance(topics, Mapping):
            errors.append(f"{robot_id}: lift.topics must be an object")
        else:
            for field in ("cmd_move", "cmd_home", "cmd_stop", "position", "direction", "limit_lower"):
                value = topics.get(field)
                if value in (None, ""):
                    errors.append(f"{robot_id}: lift.topics.{field} is required when lift.topics is set")
                elif not str(value).startswith("/"):
                    errors.append(f"{robot_id}: lift.topics.{field} must start with '/': {value}")
    for field in (
        "load_height_mm",
        "carry_height_mm",
        "unload_height_mm",
        "position_tolerance_mm",
        "ready_timeout_sec",
        "move_timeout_sec",
        "home_timeout_sec",
    ):
        _validate_number(robot_id, lift, field, errors)
    levels = lift.get("levels")
    if levels is not None:
        if not isinstance(levels, Mapping):
            errors.append(f"{robot_id}: lift.levels must be an object")
        else:
            for level, values in levels.items():
                if str(level) not in ("1", "2"):
                    errors.append(f"{robot_id}: lift.levels only supports levels 1 and 2")
                if not isinstance(values, Mapping):
                    errors.append(f"{robot_id}: lift.levels.{level} must be an object")
                    continue
                for field in ("load_height_mm", "unload_height_mm"):
                    _validate_number(robot_id, values, field, errors)
    return errors


def validate_metric_docking_config(robot_id: str, metric: Any) -> List[str]:
    errors: List[str] = []
    if metric in (None, ""):
        return errors
    if not isinstance(metric, Mapping):
        return [f"{robot_id}: metric_docking must be an object"]
    for field in ("enabled", "live_enabled"):
        if not isinstance(metric.get(field), bool):
            errors.append(f"{robot_id}: metric_docking.{field} must be boolean")
    status = str(metric.get("commissioning_status", "")).strip()
    if not status:
        errors.append(f"{robot_id}: metric_docking.commissioning_status is required")
    if metric.get("enabled") is True:
        if not str(metric.get("camera_calibration", "")).strip():
            errors.append(f"{robot_id}: metric_docking.camera_calibration is required when enabled")
        camera_to_base = metric.get("camera_to_base")
        if not isinstance(camera_to_base, Mapping):
            errors.append(f"{robot_id}: metric_docking.camera_to_base must be an object")
        else:
            if not isinstance(camera_to_base.get("measured"), bool):
                errors.append(f"{robot_id}: metric_docking.camera_to_base.measured must be boolean")
            for field in ("target_lateral_offset_m", "target_marker_yaw_rad"):
                _validate_finite_number(robot_id, camera_to_base, field, errors)
    if metric.get("live_enabled") is True:
        if status != "COMMISSIONED":
            errors.append(
                f"{robot_id}: metric_docking.live_enabled requires commissioning_status=COMMISSIONED"
            )
        camera_to_base = metric.get("camera_to_base")
        if not isinstance(camera_to_base, Mapping) or camera_to_base.get("measured") is not True:
            errors.append(
                f"{robot_id}: metric_docking.live_enabled requires measured camera_to_base"
            )
    for field in (
        "max_reprojection_error_px",
        "return_pose_source_max_age_sec",
        "return_pose_max_age_sec",
        "return_pose_yaw_tolerance_rad",
    ):
        _validate_number(robot_id, metric, field, errors)
    return errors



def validate_localization_config(robot_id: str, localization: Any) -> List[str]:
    errors: List[str] = []
    if not isinstance(localization, Mapping):
        return [f"{robot_id}: localization must be an object"]
    for field in ("map_id", "map_metadata_identity", "base_frame", "scan_topic"):
        if not str(localization.get(field, "")).strip():
            errors.append(f"{robot_id}: localization.{field} is required")
    for field in ("max_scan_age_sec", "max_tf_age_sec", "max_covariance_x", "max_covariance_y", "max_covariance_yaw", "convergence_timeout_sec", "persisted_seed_max_age_sec", "kidnapped_jump_distance_m", "stable_min_duration_sec", "max_pose_jitter_m", "max_yaw_jitter_rad"):
        _validate_number(robot_id, localization, field, errors, minimum=0.0)
    try:
        if _integer(localization.get("consecutive_samples", 0)) < 1:
            errors.append(f"{robot_id}: localization.consecutive_samples must be >= 1")
    except (TypeError, ValueError):
        errors.append(f"{robot_id}: localization.consecutive_samples must be an integer")
    search = localization.get("global_search", {})
    if not isinstance(search, Mapping):
        errors.append(f"{robot_id}: localization.global_search must be an object")
        return errors
    allowed = search.get("allowed_strategies", ["observe_only", "bounded_linear_wiggle"])
    allowed_is_valid = isinstance(allowed, list) and bool(allowed)
    if not allowed_is_valid:
        errors.append(f"{robot_id}: localization.global_search.allowed_strategies must be a non-empty list")
    else:
        unsupported = sorted(set(map(str, allowed)) - {"observe_only", "bounded_linear_wiggle"})
        if unsupported:
            errors.append(f"{robot_id}: localization.global_search unsupported strategies: {', '.join(unsupported)}")
        if "observe_only" not in allowed:
            errors.append(f"{robot_id}: localization.global_search must allow observe_only")
    default_strategy = search.get("default_strategy", "observe_only")
    if default_strategy != "observe_only":
        errors.append(f"{robot_id}: localization.global_search.default_strategy must be observe_only")
    if allowed_is_valid and default_strategy not in allowed:
        errors.append(f"{robot_id}: localization.global_search.default_strategy must be allowed")
    if search.get("motion_requires_explicit_request", True) is not True:
        errors.append(f"{robot_id}: localization.global_search.motion_requires_explicit_request must be true")
    adaptive = {
        "coarse_nomotion_interval_sec": 0.75,
        "fine_nomotion_interval_sec": 1.0,
        "nomotion_update_timeout_sec": 120.0,
        "coarse_stable_min_duration_sec": 1.5,
        "fine_stable_min_duration_sec": 3.0,
        "coarse_max_pose_jitter_m": 0.15,
        "coarse_max_yaw_jitter_rad": 0.35,
        "fine_max_pose_jitter_m": 0.08,
        "fine_max_yaw_jitter_rad": 0.15,
        "fine_fallback_max_pose_jitter_m": 0.12,
        "fine_fallback_max_yaw_jitter_rad": 0.25,
        "coarse_consecutive_samples": 3,
        "fine_consecutive_samples": 10,
        "fine_fallback_breaches": 3,
        "max_global_reinitializations": 2,
        "coarse_covariance_limits": {"x": 0.50, "y": 0.50, "yaw": 1.0},
        "fine_fallback_covariance_limits": {"x": 0.40, "y": 0.40, "yaw": 0.70},
        **search,
    }
    limits = {
        "linear_speed_mps": (0.001, 0.05),
        "max_step_m": (0.001, 0.05),
        "max_total_m": (0.001, 0.20),
        "min_front_clearance_m": (0.60, 10.0),
        "min_rear_clearance_m": (0.60, 10.0),
        "max_scan_age_sec": (0.05, 1.0),
        "max_tf_age_sec": (0.05, 1.0),
    }
    for field, (minimum, maximum) in limits.items():
        try:
            value = float(search.get(field, minimum))
            if not minimum <= value <= maximum:
                errors.append(
                    f"{robot_id}: localization.global_search.{field} must be between {minimum} and {maximum}"
                )
        except (TypeError, ValueError):
            errors.append(f"{robot_id}: localization.global_search.{field} must be numeric")
    adaptive_limits = {
        "coarse_nomotion_interval_sec": (0.01, 2.0),
        "fine_nomotion_interval_sec": (0.01, 2.0),
        "nomotion_update_timeout_sec": (1.0, 180.0),
        "coarse_stable_min_duration_sec": (0.0, 180.0),
        "fine_stable_min_duration_sec": (0.0, 180.0),
        "coarse_max_pose_jitter_m": (0.001, 1.0),
        "coarse_max_yaw_jitter_rad": (0.001, 3.2),
        "fine_max_pose_jitter_m": (0.001, 1.0),
        "fine_max_yaw_jitter_rad": (0.001, 3.2),
        "fine_fallback_max_pose_jitter_m": (0.001, 1.0),
        "fine_fallback_max_yaw_jitter_rad": (0.001, 3.2),
    }
    for field, (minimum, maximum) in adaptive_limits.items():
        try:
            value = float(adaptive.get(field))
            if not minimum <= value <= maximum:
                errors.append(
                    f"{robot_id}: localization.global_search.{field} must be between {minimum} and {maximum}"
                )
        except (TypeError, ValueError):
            errors.append(f"{robot_id}: localization.global_search.{field} must be numeric")
    if search.get("map_wide_scan_matching", False) is True:
        try:
            convergence_timeout = float(localization.get("convergence_timeout_sec"))
            search_timeout = float(adaptive.get("nomotion_update_timeout_sec"))
            required_timeout = search_timeout + 30.0
            if (
                math.isfinite(convergence_timeout)
                and math.isfinite(search_timeout)
                and convergence_timeout < required_timeout
            ):
                errors.append(
                    f"{robot_id}: localization.convergence_timeout_sec must be at least "
                    f"{required_timeout:g} for map-wide search plus admission"
                )
        except (TypeError, ValueError):
            pass
    for field, minimum, maximum in (
        ("coarse_consecutive_samples", 3, 100),
        ("fine_consecutive_samples", 3, 100),
        ("fine_fallback_breaches", 1, 10),
        ("max_global_reinitializations", 1, 2),
    ):
        try:
            value = _integer(adaptive.get(field))
            if value < minimum or value > maximum:
                errors.append(
                    f"{robot_id}: localization.global_search.{field} must be between {minimum} and {maximum}"
                )
        except (TypeError, ValueError):
            errors.append(f"{robot_id}: localization.global_search.{field} must be an integer")
    coarse_covariance = adaptive.get("coarse_covariance_limits")
    fallback_covariance = adaptive.get("fine_fallback_covariance_limits")
    if not isinstance(coarse_covariance, Mapping) or not isinstance(fallback_covariance, Mapping):
        errors.append(f"{robot_id}: localization.global_search covariance limits must be objects")
    else:
        for axis in ("x", "y", "yaw"):
            try:
                fine = float(localization[f"max_covariance_{axis}"])
                fallback = float(fallback_covariance[axis])
                coarse = float(coarse_covariance[axis])
                if not 0 < fine <= fallback <= coarse:
                    errors.append(
                        f"{robot_id}: localization.global_search covariance {axis} must satisfy fine <= fallback <= coarse"
                    )
            except (KeyError, TypeError, ValueError):
                errors.append(f"{robot_id}: localization.global_search covariance {axis} must be numeric")
    try:
        if not (
            float(adaptive["fine_max_pose_jitter_m"])
            <= float(adaptive["fine_fallback_max_pose_jitter_m"])
            <= float(adaptive["coarse_max_pose_jitter_m"])
        ):
            errors.append(f"{robot_id}: localization.global_search pose jitter must satisfy fine <= fallback <= coarse")
        if not (
            float(adaptive["fine_max_yaw_jitter_rad"])
            <= float(adaptive["fine_fallback_max_yaw_jitter_rad"])
            <= float(adaptive["coarse_max_yaw_jitter_rad"])
        ):
            errors.append(f"{robot_id}: localization.global_search yaw jitter must satisfy fine <= fallback <= coarse")
    except (KeyError, TypeError, ValueError):
        errors.append(f"{robot_id}: localization.global_search jitter thresholds must be numeric")
    alignment = localization.get("scan_map_alignment", {})
    if not isinstance(alignment, Mapping):
        errors.append(f"{robot_id}: localization.scan_map_alignment must be an object")
    else:
        allowed_values = {
            "point_selector": {"all_points", "wall_segments"},
            "map_feature_field": {"occupied_surface", "wall_centerline"},
            "loss_backend": {"truncated_mean", "trimmed_huber", "hybrid_trimmed_huber"},
            "global_point_selector": {"all_points", "wall_segments"},
            "global_map_feature_field": {"occupied_surface", "wall_centerline"},
            "global_loss_backend": {"truncated_mean", "trimmed_huber", "hybrid_trimmed_huber"},
        }
        defaults = {
            "point_selector": "all_points",
            "map_feature_field": "occupied_surface",
            "loss_backend": "truncated_mean",
            "global_point_selector": "all_points",
            "global_map_feature_field": "occupied_surface",
            "global_loss_backend": "trimmed_huber",
        }
        for field, allowed_values_for_field in allowed_values.items():
            value = str(alignment.get(field, defaults[field]))
            if value not in allowed_values_for_field:
                errors.append(f"{robot_id}: localization.scan_map_alignment.{field} is unsupported: {value}")
        for field, minimum, maximum in (
            ("loss_trim_fraction", 0.0, 0.49),
            ("loss_area_weight", 0.0, 1.0),
            ("outside_map_penalty_m", 0.0, 10.0),
            ("continuous_check_interval_sec", 0.0, 60.0),
            ("segment_mismatch_weight", 0.0, 10.0),
            ("segment_mismatch_quantile", 0.5, 1.0),
            ("segment_mismatch_tolerance_m", 0.0, 1.0),
            ("max_segment_mismatch_m", 0.0, 1.0),
            ("max_mean_distance_m", 0.0, 1.0),
            ("global_max_mean_distance_m", 0.0, 1.0),
            ("wall_direction_weight_m_per_rad", 0.0, 1.0),
            ("wall_direction_max_distance_m", 0.001, 1.0),
            ("wall_direction_distance_slack_m", 0.0, 0.01),
            ("max_wall_direction_error_rad", 0.001, 1.5708),
        ):
            if field not in alignment:
                continue
            try:
                value = float(alignment[field])
                if not minimum <= value <= maximum:
                    errors.append(
                        f"{robot_id}: localization.scan_map_alignment.{field} must be between {minimum} and {maximum}"
                    )
            except (TypeError, ValueError):
                errors.append(f"{robot_id}: localization.scan_map_alignment.{field} must be numeric")
        try:
            fine_max_mean = float(alignment.get("max_mean_distance_m", 0.015))
            global_max_mean = float(alignment.get("global_max_mean_distance_m", 0.020))
            if global_max_mean < fine_max_mean:
                errors.append(
                    f"{robot_id}: localization.scan_map_alignment.global_max_mean_distance_m "
                    "must be greater than or equal to max_mean_distance_m"
                )
        except (TypeError, ValueError):
            pass
    return errors

def validate_robot_profile(robot: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    robot_id = str(robot.get("robot_id", "<unknown>"))
    for field in ROBOT_REQUIRED_FIELDS:
        if robot.get(field) in (None, ""):
            errors.append(f"{robot_id}: missing required field '{field}'")
    ros_domain_id = robot.get("ros_domain_id")
    if ros_domain_id is not None:
        try:
            int(ros_domain_id)
        except (TypeError, ValueError):
            errors.append(f"{robot_id}: ros_domain_id must be an integer")
    nav_local_domain_id = robot.get("nav_local_domain_id")
    if nav_local_domain_id is not None:
        try:
            local_domain = int(nav_local_domain_id)
        except (TypeError, ValueError):
            errors.append(f"{robot_id}: nav_local_domain_id must be an integer")
        else:
            if ros_domain_id is not None and local_domain == int(ros_domain_id):
                errors.append(f"{robot_id}: nav_local_domain_id must differ from ros_domain_id")
    bridge_robot_id = robot.get("bridge_robot_id")
    if bridge_robot_id in (None, ""):
        errors.append(f"{robot_id}: missing bridge_robot_id")

    api_port = robot.get("api_port")
    if api_port is not None:
        try:
            port = int(api_port)
        except (TypeError, ValueError):
            errors.append(f"{robot_id}: api_port must be an integer")
        else:
            if port <= 0 or port > 65535:
                errors.append(f"{robot_id}: api_port must be between 1 and 65535")

    capabilities = robot.get("capabilities")
    capability_set: set[str] = set()
    lift = robot.get("lift")
    lift_enabled = bool(lift.get("enabled", False)) if isinstance(lift, Mapping) else False
    if capabilities is not None:
        if not isinstance(capabilities, list) or not all(isinstance(capability, str) for capability in capabilities):
            errors.append(f"{robot_id}: capabilities must be a list of strings")
            capability_set = set()
        else:
            capability_set = set(capabilities)
            if lift_enabled and "lift" not in capability_set:
                errors.append(f"{robot_id}: lift.enabled requires lift capability")
            if "lift" in capability_set and not lift_enabled:
                errors.append(f"{robot_id}: lift capability requires lift.enabled=true")
            for mission_capability in ("inbound", "outbound"):
                if mission_capability in capability_set and (not lift_enabled or "lift" not in capability_set):
                    errors.append(
                        f"{robot_id}: {mission_capability} capability requires lift.enabled=true and lift capability"
                    )
    field_dispatch = robot.get("field_dispatch")
    if field_dispatch is not None:
        if not isinstance(field_dispatch, Mapping):
            errors.append(f"{robot_id}: field_dispatch must be an object")
        else:
            for mission in ("inbound", "outbound"):
                if not isinstance(field_dispatch.get(mission), bool):
                    errors.append(f"{robot_id}: field_dispatch.{mission} must be boolean")
            if not str(field_dispatch.get("status", "")).strip():
                errors.append(f"{robot_id}: field_dispatch.status is required")
    localization = robot.get("localization")
    active_map_yaml = robot.get("active_map_yaml")
    if isinstance(localization, Mapping) and isinstance(active_map_yaml, str):
        if localization.get("map_metadata_identity") != active_map_yaml:
            errors.append(f"{robot_id}: localization.map_metadata_identity must equal active_map_yaml")
        if localization.get("map_id") != Path(active_map_yaml).stem:
            errors.append(f"{robot_id}: localization.map_id must equal active_map_yaml stem")
    errors.extend(validate_lift_config(robot_id, robot.get("lift")))
    errors.extend(validate_metric_docking_config(robot_id, robot.get("metric_docking")))
    errors.extend(validate_localization_config(robot_id, robot.get("localization")))
    return errors


def validate_robots_document(data: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    robots = data.get("robots")
    if not isinstance(robots, list) or not robots:
        errors.append("robots.json must contain a non-empty 'robots' list")
        return errors

    for robot in robots:
        if not isinstance(robot, dict):
            errors.append("each robots[] entry must be an object")
            continue
        errors.extend(validate_robot_profile(robot))

    robot_dicts = [robot for robot in robots if isinstance(robot, dict)]
    for field in ROBOT_UNIQUE_FIELDS:
        _append_unique_errors(robot_dicts, field, errors)
    return errors


def validate_main_server_routes(data: Mapping[str, Any]) -> List[str]:
    errors: List[str] = []
    for field in ("nav_pc_host", "main_api_base", "webhook_endpoint"):
        if not str(data.get(field, "")).strip():
            errors.append(f"main_server_routes.json missing '{field}'")

    robots = data.get("robots", [])
    if not isinstance(robots, list):
        errors.append("main_server_routes.json 'robots' must be a list")
        return errors

    for robot in robots:
        if not isinstance(robot, dict):
            errors.append("main_server_routes robots[] entries must be objects")
            continue
        robot_id = str(robot.get("robot_id", "<unknown>"))
        for field in MAIN_ROUTE_ROBOT_REQUIRED_FIELDS:
            if robot.get(field) in (None, ""):
                errors.append(f"routes robot {robot_id}: missing '{field}'")
    return errors


def validate_active_robot_id(active_robot_id: str, profiles: Mapping[str, Dict[str, Any]]) -> List[str]:
    if active_robot_id not in profiles:
        return [f"unknown ROBOT_ID: {active_robot_id}"]
    profile = profiles[active_robot_id]
    if not profile.get("enabled", True):
        return [f"disabled ROBOT_ID: {active_robot_id}"]
    return []


def format_validation_errors(label: str, errors: Sequence[str]) -> str:
    joined = "; ".join(errors)
    return f"{label} validation failed: {joined}"
