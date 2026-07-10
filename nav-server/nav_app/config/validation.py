"""Config validation helpers (ROS-free)."""

from __future__ import annotations

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
    if value < minimum:
        errors.append(f"{robot_id}: {field} must be >= {minimum}")


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



def validate_localization_config(robot_id: str, localization: Any) -> List[str]:
    errors: List[str] = []
    if not isinstance(localization, Mapping):
        return [f"{robot_id}: localization must be an object"]
    for field in ("map_id", "map_metadata_identity", "base_frame", "scan_topic"):
        if not str(localization.get(field, "")).strip():
            errors.append(f"{robot_id}: localization.{field} is required")
    for field in ("max_scan_age_sec", "max_tf_age_sec", "max_covariance_x", "max_covariance_y", "max_covariance_yaw", "convergence_timeout_sec", "persisted_seed_max_age_sec", "kidnapped_jump_distance_m"):
        _validate_number(robot_id, localization, field, errors, minimum=0.0)
    try:
        if int(localization.get("consecutive_samples", 0)) < 1:
            errors.append(f"{robot_id}: localization.consecutive_samples must be >= 1")
    except (TypeError, ValueError):
        errors.append(f"{robot_id}: localization.consecutive_samples must be an integer")
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
    errors.extend(validate_lift_config(robot_id, robot.get("lift")))
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
