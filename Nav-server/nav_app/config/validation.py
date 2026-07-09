"""Config validation helpers (ROS-free)."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

ROBOT_REQUIRED_FIELDS: Sequence[str] = (
    "robot_id",
    "bridge_robot_id",
    "ros_domain_id",
    "center_domain_id",
    "namespace",
    "teleop_command_topic",
    "camera_topic",
)

ROBOT_UNIQUE_FIELDS: Sequence[str] = (
    "robot_id",
    "bridge_robot_id",
    "ros_domain_id",
    "namespace",
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
        errors.append(f"{robot_id}: lift.{field} must be numeric")
        return
    if value < minimum:
        errors.append(f"{robot_id}: lift.{field} must be >= {minimum}")


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
    errors.extend(validate_lift_config(robot_id, robot.get("lift")))
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
