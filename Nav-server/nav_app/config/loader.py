import json
import os
import socket
from concurrent.futures import TimeoutError as FutureTimeoutError
from typing import Any, Dict
from urllib.parse import urlparse

from nav_app.settings import (
    ACTIVE_ROBOT_ID,
    ENV_MAIN_API_BASE,
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
                "capabilities": ["navigate", "inbound", "outbound", "charge"],
                "enabled": True,
            },
            "tb3_burger_02": {
                "robot_id": "tb3_burger_02",
                "bridge_robot_id": "tb3_2",
                "ros_domain_id": 5,
                "center_domain_id": 1,
                "namespace": "/tb3_burger_02",
                "teleop_command_topic": "/mission/tb3_2/teleop_cmd",
                "camera_topic": "/mission/tb3_2/camera/compressed",
                "capabilities": ["navigate", "inbound", "outbound", "charge"],
                "enabled": True,
            },
        }

    data = json.loads(ROBOTS_CONFIG_PATH.read_text(encoding="utf-8"))
    errors = validate_robots_document(data)
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
            "nav_pc_fallback_host": "<operator-configured-nav-lan-ip>",
            "main_public_base_url": "http://smartfactory-main.local:8088",
            "main_api_base": "http://smartfactory-main.local:8088/api/v1",
            "command_events_endpoint": "http://smartfactory-main.local:8088/api/v1/movement/command-events",
            "movement_results_endpoint": "http://smartfactory-main.local:8088/api/v1/movement/results",
            "robot_status_endpoint_template": "http://smartfactory-main.local:8088/api/v1/movement/robots/{robot_name}/status",
            "webhook_endpoint": "http://smartfactory-main.local:8088/api/v1/movement/command-events",
            "webhook_fallback_endpoint": "http://<operator-configured-main-lan-ip>:8088/api/v1/movement/command-events",
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
            return robot
    profile = ROBOT_PROFILES.get(ACTIVE_ROBOT_ID, {})
    port = 8001 if profile.get("bridge_robot_id") == "tb3_1" else 8002
    host = MAIN_SERVER_ROUTES.get("nav_pc_host", "smartfactory-nav.local")
    fallback_host = MAIN_SERVER_ROUTES.get("nav_pc_fallback_host", "<operator-configured-nav-lan-ip>")
    return {
        "robot_id": ACTIVE_ROBOT_ID,
        "nav_api_url": f"http://{host}:{port}",
        "nav_api_fallback_url": f"http://{fallback_host}:{port}",
        "ros_domain_id": profile.get("ros_domain_id"),
        "bridge_robot_id": profile.get("bridge_robot_id"),
        "center_domain_id": profile.get("center_domain_id"),
        "mission_types": ["inbound", "outbound"],
    }


def _url_host(url: str) -> str:
    parsed = urlparse(url or "")
    return parsed.hostname


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
    profile = active_robot_profile()
    return int(os.getenv("ROS_DOMAIN_ID", str(profile["ros_domain_id"])))


def ensure_process_domain_matches_profile() -> int:
    profile = active_robot_profile()
    expected_domain = int(profile["ros_domain_id"])
    configured_domain = os.getenv("ROS_DOMAIN_ID")
    if configured_domain is None:
        os.environ["ROS_DOMAIN_ID"] = str(expected_domain)
        return expected_domain

    actual_domain = int(configured_domain)
    if actual_domain != expected_domain:
        raise RuntimeError(
            f"ROBOT_ID={ACTIVE_ROBOT_ID}는 ROS_DOMAIN_ID={expected_domain} 설정이 필요하지만 "
            f"현재 ROS_DOMAIN_ID={actual_domain}입니다."
        )
    return actual_domain


def active_endpoint_contract() -> Dict[str, Any]:
    route = active_route_config()
    nav_host = MAIN_SERVER_ROUTES.get("nav_pc_host") or _url_host(route.get("nav_api_url"))
    webhook_host = _url_host(MAIN_SERVER_ROUTES.get("webhook_endpoint"))
    fallback_host = MAIN_SERVER_ROUTES.get("nav_pc_fallback_host")
    webhook_fallback_host = _url_host(MAIN_SERVER_ROUTES.get("webhook_fallback_endpoint"))
    return {
        "policy": "hostname-first",
        "os_hostname": socket.gethostname(),
        "active_robot_id": ACTIVE_ROBOT_ID,
        "active_robot_name": route.get("bridge_robot_id"),
        "active_ros_domain_id": current_ros_domain_id(),
        "robot_fixed_ip": route.get("robot_fixed_ip"),
        "robot_fixed_ips": MAIN_SERVER_ROUTES.get("robot_fixed_ips", {}),
        "nav_pc_host": nav_host,
        "nav_api_url": route.get("nav_api_url"),
        "nav_api_fallback_url": route.get("nav_api_fallback_url"),
        "main_public_base_url": MAIN_PUBLIC_BASE_URL or MAIN_SERVER_ROUTES.get("main_public_base_url"),
        "main_api_base": MAIN_API_BASE or MAIN_SERVER_ROUTES.get("main_api_base"),
        "command_events_endpoint": MAIN_SERVER_ROUTES.get("command_events_endpoint") or MAIN_SERVER_ROUTES.get("webhook_endpoint"),
        "movement_results_endpoint": MAIN_SERVER_ROUTES.get("movement_results_endpoint"),
        "robot_status_endpoint_template": MAIN_SERVER_ROUTES.get("robot_status_endpoint_template"),
        "webhook_endpoint": MAIN_SERVER_ROUTES.get("webhook_endpoint"),
        "webhook_fallback_endpoint": MAIN_SERVER_ROUTES.get("webhook_fallback_endpoint"),
        "resolution": {
            "nav_pc_host": _resolve_hostname(nav_host),
            "nav_pc_fallback_host": _resolve_hostname(fallback_host),
            "webhook_host": _resolve_hostname(webhook_host),
            "webhook_fallback_host": _resolve_hostname(webhook_fallback_host),
        },
        "fallback_policy": {
            "use_fallback_only_when": ["hostname_unresolved", "health_timeout", "status_non_2xx"],
            "do_not_hardcode_dhcp_ip": True,
        },
        "robots": MAIN_SERVER_ROUTES.get("robots", []),
        "reported_at": utc_now(),
    }
