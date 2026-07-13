import json
import os
import socket
from concurrent.futures import TimeoutError as FutureTimeoutError
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlparse

from nav_app.settings import (
    ACTIVE_ROBOT_ID,
    ENV_MAIN_API_BASE,
    ENV_NAV_PC_HOST,
    ENV_WEBHOOK_ENDPOINT,
    HOSTNAME_RESOLVE_TIMEOUT_SEC,
    LMS_PUBLIC_BASE_URL,
    MAIN_SERVER_ROUTES_PATH,
    ROBOTS_CONFIG_PATH,
    hostname_resolver,
)
from nav_app.util.time import utc_now
from nav_app.config.validation import (
    format_validation_errors,
    validate_active_robot_id,
    validate_main_server_routes,
    validate_robots_document,
)


def load_robot_profiles() -> Dict[str, Dict[str, Any]]:
    """robot_id별 ROS Domain/namespace 라우팅 설정을 로드합니다."""
    if not ROBOTS_CONFIG_PATH.exists():
        return {
            "tb3_burger_01": {
                "robot_id": "tb3_burger_01",
                "bridge_robot_id": "tb3_1",
                "ros_domain_id": 2,
                "center_domain_id": 1,
                "namespace": "/tb3_burger_01",
                "teleop_command_topic": "/mission/tb3_1/teleop_cmd",
                "camera_topic": "/mission/tb3_1/camera/compressed",
                "capabilities": ["navigate", "charge"],
                "enabled": True,
                "api_port": 8001, "active_map_yaml": "map/robot2_map.yaml", "localization": {"map_id": "robot2_map", "map_metadata_identity": "map/robot2_map.yaml", "base_frame": "base_footprint", "scan_topic": "/scan", "max_scan_age_sec": 1.0, "max_tf_age_sec": 1.0, "max_covariance_x": 0.25, "max_covariance_y": 0.25, "max_covariance_yaw": 0.35, "consecutive_samples": 3, "convergence_timeout_sec": 30.0, "persisted_seed_max_age_sec": 3600.0, "kidnapped_jump_distance_m": 1.5}, "field_dispatch": {"inbound": False, "outbound": False, "status": "BLOCKED_PENDING_PER_MAP_FIELD_BINDINGS"},
            },
            "tb3_burger_02": {
                "robot_id": "tb3_burger_02",
                "bridge_robot_id": "tb3_2",
                "ros_domain_id": 5,
                "center_domain_id": 1,
                "namespace": "/tb3_burger_02",
                "teleop_command_topic": "/mission/tb3_2/teleop_cmd",
                "camera_topic": "/mission/tb3_2/camera/compressed",
                "capabilities": ["navigate", "charge", "lift"],
                "enabled": True,
                "api_port": 8002, "active_map_yaml": "map/robot2_map.yaml", "localization": {"map_id": "robot2_map", "map_metadata_identity": "map/robot2_map.yaml", "base_frame": "base_footprint", "scan_topic": "/scan", "max_scan_age_sec": 1.0, "max_tf_age_sec": 1.0, "max_covariance_x": 0.25, "max_covariance_y": 0.25, "max_covariance_yaw": 0.35, "consecutive_samples": 3, "convergence_timeout_sec": 30.0, "persisted_seed_max_age_sec": 3600.0, "kidnapped_jump_distance_m": 1.5}, "lift": {"enabled": True}, "field_dispatch": {"inbound": False, "outbound": False, "status": "BLOCKED_PENDING_PER_MAP_FIELD_BINDINGS"},
            },
        }

    data = json.loads(ROBOTS_CONFIG_PATH.read_text(encoding="utf-8"))
    errors = validate_robots_document(data)
    for robot in data.get("robots", []):
        if not isinstance(robot, dict) or not robot.get("active_map_yaml"):
            continue
        map_path = Path(str(robot["active_map_yaml"]))
        if not map_path.is_absolute():
            map_path = ROBOTS_CONFIG_PATH.parent.parent / map_path
        if not map_path.is_file():
            errors.append(f"{robot.get('robot_id', '<unknown>')}: active_map_yaml not found: {map_path}")
    if errors:
        raise RuntimeError(format_validation_errors("robots.json", errors))
    profiles: Dict[str, Dict[str, Any]] = {}
    for robot in data.get("robots", []):
        robot_id = robot.get("robot_id")
        if robot_id:
            profiles[robot_id] = robot
    return profiles


ROBOT_PROFILES = load_robot_profiles()


def load_main_server_routes() -> Dict[str, Any]:
    """Main/Control 서버가 조회할 hostname-first endpoint 계약을 로드합니다."""
    if not MAIN_SERVER_ROUTES_PATH.exists():
        return {
            "nav_pc_host": "smartfactory-nav.local",
            "main_public_base_url": "https://smartfactory-main.local:8088",
            "main_api_base": "https://smartfactory-main.local:8088/api/v1",
            "command_events_endpoint": "https://smartfactory-main.local:8088/api/v1/movement/command-events",
            "movement_results_endpoint": "https://smartfactory-main.local:8088/api/v1/movement/results",
            "robot_status_endpoint_template": "https://smartfactory-main.local:8088/api/v1/movement/robots/{robot_name}/status",
            "webhook_endpoint": "https://smartfactory-main.local:8088/api/v1/movement/command-events",
            "robots": [],
        }
    return json.loads(MAIN_SERVER_ROUTES_PATH.read_text(encoding="utf-8"))


def _validated_main_server_routes() -> Dict[str, Any]:
    routes = load_main_server_routes()
    if MAIN_SERVER_ROUTES_PATH.exists():
        errors = validate_main_server_routes(routes)
        if errors:
            raise RuntimeError(format_validation_errors("main_server_routes.json", errors))
    return routes


MAIN_SERVER_ROUTES = _validated_main_server_routes()
active_robot_errors = validate_active_robot_id(ACTIVE_ROBOT_ID, ROBOT_PROFILES)
if active_robot_errors and ROBOTS_CONFIG_PATH.exists():
    raise RuntimeError(format_validation_errors("ROBOT_ID", active_robot_errors))
MAIN_PUBLIC_BASE_URL = LMS_PUBLIC_BASE_URL or str(MAIN_SERVER_ROUTES.get("main_public_base_url", "")).rstrip("/")
MAIN_API_BASE = ENV_MAIN_API_BASE or str(MAIN_SERVER_ROUTES.get("main_api_base", "")).rstrip("/")
if not MAIN_API_BASE and MAIN_PUBLIC_BASE_URL:
    MAIN_API_BASE = f"{MAIN_PUBLIC_BASE_URL}/api/v1"


def active_route_config() -> Dict[str, Any]:
    for robot in MAIN_SERVER_ROUTES.get("robots", []):
        if robot.get("robot_id") == ACTIVE_ROBOT_ID:
            route = dict(robot)
            if ENV_NAV_PC_HOST:
                route["nav_api_url"] = _url_with_host(str(route["nav_api_url"]), ENV_NAV_PC_HOST)
            return route
    profile = ROBOT_PROFILES.get(ACTIVE_ROBOT_ID, {})
    port = int(profile.get("api_port") or (8001 if profile.get("bridge_robot_id") == "tb3_1" else 8002))
    host = ENV_NAV_PC_HOST or MAIN_SERVER_ROUTES.get("nav_pc_host", "smartfactory-nav.local")
    return {
        "robot_id": ACTIVE_ROBOT_ID,
        "nav_api_url": f"http://{host}:{port}",
        "ros_domain_id": profile.get("ros_domain_id"),
        "bridge_robot_id": profile.get("bridge_robot_id"),
        "center_domain_id": profile.get("center_domain_id"),
        "mission_types": ["inbound", "outbound"],
    }


def _url_host(url: str) -> str:
    parsed = urlparse(url or "")
    return parsed.hostname


def _url_with_host(url: str, host: str) -> str:
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise RuntimeError(f"invalid configured Nav API URL: {url}")
    hostname = host.strip()
    if not hostname or ":" in hostname or "/" in hostname:
        raise RuntimeError("NAV_PC_HOST must be a hostname without scheme or port")
    netloc = hostname if parsed.port is None else f"{hostname}:{parsed.port}"
    return parsed._replace(netloc=netloc).geturl()


def _lookup_hostname_addresses(hostname: str):
    return sorted({info[4][0] for info in socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)})


def _resolve_hostname(hostname: str) -> Dict[str, Any]:
    if not hostname or hostname.startswith("<"):
        return {"hostname": hostname, "resolved": False, "addresses": [], "reason": "not_configured"}
    if HOSTNAME_RESOLVE_TIMEOUT_SEC <= 0:
        return {"hostname": hostname, "resolved": False, "addresses": [], "reason": "resolution_disabled"}
    try:
        future = hostname_resolver.submit(_lookup_hostname_addresses, hostname)
        addresses = future.result(timeout=HOSTNAME_RESOLVE_TIMEOUT_SEC)
        return {"hostname": hostname, "resolved": True, "addresses": addresses, "reason": "ok"}
    except FutureTimeoutError:
        return {
            "hostname": hostname,
            "resolved": False,
            "addresses": [],
            "reason": "resolution_timeout",
            "timeout_sec": HOSTNAME_RESOLVE_TIMEOUT_SEC,
        }
    except socket.gaierror as exc:
        return {"hostname": hostname, "resolved": False, "addresses": [], "reason": "hostname_unresolved", "error": str(exc)}


def active_robot_profile() -> Dict[str, Any]:
    profile = ROBOT_PROFILES.get(ACTIVE_ROBOT_ID)
    if not profile:
        raise RuntimeError(f"알 수 없는 ROBOT_ID입니다: {ACTIVE_ROBOT_ID}")
    if not profile.get("enabled", True):
        raise RuntimeError(f"비활성화된 ROBOT_ID입니다: {ACTIVE_ROBOT_ID}")
    return profile


def current_ros_domain_id() -> int:
    """Return the robot hardware domain exposed by the public API contract."""
    profile = active_robot_profile()
    return int(profile["ros_domain_id"])


def process_ros_domain_id() -> int:
    """Return the DDS domain used by this Nav process (optionally bridge-isolated)."""
    profile = active_robot_profile()
    return int(os.getenv("ROS_DOMAIN_ID", str(profile["ros_domain_id"])))


def ensure_process_domain_matches_profile() -> int:
    profile = active_robot_profile()
    hardware_domain = int(profile["ros_domain_id"])
    expected_domain = int(os.getenv("NAV_LOCAL_ROS_DOMAIN_ID", str(hardware_domain)))
    configured_domain = os.getenv("ROS_DOMAIN_ID")
    if configured_domain is None:
        os.environ["ROS_DOMAIN_ID"] = str(expected_domain)
        return expected_domain

    actual_domain = int(configured_domain)
    if actual_domain != expected_domain:
        raise RuntimeError(
            f"ROBOT_ID={ACTIVE_ROBOT_ID}는 NAV_LOCAL_ROS_DOMAIN_ID={expected_domain}에 맞춘 "
            f"ROS_DOMAIN_ID가 필요하지만 현재 ROS_DOMAIN_ID={actual_domain}입니다."
        )
    return actual_domain


def active_endpoint_contract() -> Dict[str, Any]:
    route = active_route_config()
    nav_host = ENV_NAV_PC_HOST or MAIN_SERVER_ROUTES.get("nav_pc_host") or _url_host(route.get("nav_api_url"))
    if ENV_MAIN_API_BASE:
        command_events_endpoint = f"{MAIN_API_BASE}/movement/command-events"
        movement_results_endpoint = f"{MAIN_API_BASE}/movement/results"
        robot_status_endpoint_template = f"{MAIN_API_BASE}/movement/robots/{{robot_name}}/status"
    else:
        command_events_endpoint = MAIN_SERVER_ROUTES.get("command_events_endpoint") or MAIN_SERVER_ROUTES.get("webhook_endpoint")
        movement_results_endpoint = MAIN_SERVER_ROUTES.get("movement_results_endpoint")
        robot_status_endpoint_template = MAIN_SERVER_ROUTES.get("robot_status_endpoint_template")
    webhook_endpoint = ENV_WEBHOOK_ENDPOINT or command_events_endpoint
    webhook_host = _url_host(webhook_endpoint)
    return {
        "policy": "hostname-first",
        "os_hostname": socket.gethostname(),
        "active_robot_id": ACTIVE_ROBOT_ID,
        "active_robot_name": route.get("bridge_robot_id"),
        "active_ros_domain_id": current_ros_domain_id(),
        "nav_pc_host": nav_host,
        "nav_api_url": route.get("nav_api_url"),
        "main_public_base_url": MAIN_PUBLIC_BASE_URL or MAIN_SERVER_ROUTES.get("main_public_base_url"),
        "main_api_base": MAIN_API_BASE or MAIN_SERVER_ROUTES.get("main_api_base"),
        "command_events_endpoint": command_events_endpoint,
        "movement_results_endpoint": movement_results_endpoint,
        "robot_status_endpoint_template": robot_status_endpoint_template,
        "webhook_endpoint": webhook_endpoint,
        "resolution": {
            "nav_pc_host": _resolve_hostname(nav_host),
            "webhook_host": _resolve_hostname(webhook_host),
        },
        "robots": MAIN_SERVER_ROUTES.get("robots", []),
        "reported_at": utc_now(),
    }
