#!/usr/bin/env python3
"""Fail-fast static audit for the declarative field configuration.

This deliberately does not probe the network or claim that map coordinates match
the physical field.  It checks only relationships that can be proven from files
in this repository; unavailable declarative counterparts are reported as gaps.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import sys
from ipaddress import IPv4Address
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[2]
NAV = ROOT / "nav-server"
MAIN = ROOT / "main-server"
AI = ROOT / "ai-server"


def fail(message: str) -> None:
    raise AssertionError(message)


def load_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"{path.relative_to(ROOT)} is not valid JSON: {exc}")


def unique(values: list[object], label: str) -> None:
    duplicates = sorted({value for value in values if values.count(value) > 1})
    if duplicates:
        fail(f"duplicate {label}: {duplicates}")


def require_url(value: object, label: str) -> None:
    parsed = urlparse(str(value))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.port is None:
        fail(f"{label} must be an absolute HTTP(S) URL with host and port: {value!r}")


def require_network_host(value: object, label: str) -> None:
    """Accept a routable IPv4 address or RFC-style DNS hostname.

    The field contract is hostname-first, but an operator may supply a LAN IPv4
    address where a host is accepted.  Loopback and malformed host values must
    never pass the static deployment audit.
    """
    host = str(value).rstrip(".")
    try:
        address = IPv4Address(host)
    except ValueError:
        hostname_labels = host.split(".")
        is_dns_name = bool(host) and len(host) <= 253 and all(
            re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", hostname_label)
            for hostname_label in hostname_labels
        )
        if not is_dns_name or host.lower() == "localhost":
            fail(f"{label} must be a valid DNS hostname or IPv4 address: {value!r}")
        return
    if address.is_loopback:
        fail(f"{label} must not use a loopback address: {value!r}")


def yaml_scalar(path: Path, key: str) -> str | None:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*(\S+)\s*$", path.read_text(encoding="utf-8"))
    return match.group(1) if match else None


def bridge_document(path: Path) -> tuple[int, int, set[str]]:
    text = path.read_text(encoding="utf-8")
    source = re.search(r"(?m)^from_domain:\s*(\d+)\s*$", text)
    target = re.search(r"(?m)^to_domain:\s*(\d+)\s*$", text)
    topics = set(re.findall(r"(?m)^\s{2}([^\s:]+):\s*$", text))
    if not source or not target or not topics:
        fail(f"{path.relative_to(ROOT)} must declare domains and topics")
    return int(source.group(1)), int(target.group(1)), topics


def finite_pose(value: object, label: str) -> None:
    if not isinstance(value, dict):
        fail(f"{label} must be an object")
    for key in ("x", "y", "theta"):
        number = value.get(key)
        if not isinstance(number, (int, float)) or isinstance(number, bool) or not math.isfinite(number):
            fail(f"{label}.{key} must be finite")


def check_field_bindings(zones: dict, locations: dict[str, tuple]) -> None:
    """Prove Main's task rows use the same Nav facts as the binding contract."""
    bindings = load_json(MAIN / "backend/config/field-bindings.json")
    if not isinstance(bindings, dict) or bindings.get("version") != 1:
        fail("field-bindings.json must declare version 1")
    declared, scans, map_dispatch = bindings.get("locations"), bindings.get("scans"), bindings.get("map_dispatch")
    if not isinstance(declared, dict) or not isinstance(scans, dict) or not isinstance(map_dispatch, dict):
        fail("field-bindings.json must contain locations, scans, and map_dispatch objects")
    expected_robot1_policy = {
        "inbound": False,
        "outbound": False,
        "status": "BLOCKED_SUPERSEDED_MAP_COORDINATES_UNVERIFIED",
    }
    expected_robot2_policy = {"inbound": False, "outbound": False, "status": "BLOCKED_PENDING_PER_MAP_FIELD_BINDINGS"}
    if map_dispatch.get("robot1_map") != expected_robot1_policy:
        fail("robot1_map must remain blocked because its coordinates belong to the superseded map")
    if map_dispatch.get("robot2_map") != expected_robot2_policy:
        fail("robot2_map must remain explicitly blocked pending per-map field bindings")
    waypoints = zones["waypoints"]
    semantic = zones["semantic_zones"]
    required_kinds = {"inbound", "outbound", "storage", "home", "charge"}
    if {binding.get("kind") for binding in declared.values() if isinstance(binding, dict)} != required_kinds:
        fail("field-bindings.json must bind inbound, outbound, storage, home, and charge locations")
    for location_id, binding in declared.items():
        if not isinstance(binding, dict):
            fail(f"field binding {location_id} must be an object")
        required = {"kind", "map_id", "nav_zone", "nav_waypoint", "pose", "marker_id", "scan_location_id"}
        if set(binding) != required:
            fail(f"field binding {location_id} must contain exactly the authoritative fields")
        zone = semantic.get(binding["nav_zone"])
        waypoint = waypoints.get(binding["nav_waypoint"])
        if not isinstance(zone, dict) or not isinstance(waypoint, dict):
            fail(f"field binding {location_id} references a missing Nav zone or waypoint")
        if zone.get("aruco_marker_id") != binding["marker_id"]:
            fail(f"field binding {location_id} marker_id must match its Nav zone")
        pose = binding["pose"]
        if not isinstance(pose, dict) or any(pose.get(key) != waypoint.get(nav_key) for key, nav_key in (("x", "x"), ("y", "y"), ("yaw", "theta"))):
            fail(f"field binding {location_id} pose must equal its Nav waypoint")
        seed = locations.get(location_id)
        if not seed:
            fail(f"Main seed missing bound location {location_id}")
        _, x, y, yaw, marker, map_id = seed
        if (x, y, yaw, marker, map_id) != (pose["x"], pose["y"], pose["yaw"], str(binding["marker_id"]), binding["map_id"]):
            fail(f"Main seed {location_id} conflicts with field-bindings.json")
        scan_id = binding["scan_location_id"]
        scan = scans.get(scan_id)
        if not isinstance(scan, dict) or scan.get("location_id") != location_id:
            fail(f"field binding {location_id} must declare its paired scan location")
        scan_waypoint = waypoints.get(scan.get("nav_waypoint"))
        scan_pose = scan.get("pose")
        if not isinstance(scan_waypoint, dict) or not isinstance(scan_pose, dict):
            fail(f"scan binding {scan_id} references a missing Nav waypoint or pose")
        if scan.get("marker_id") != binding["marker_id"] or any(scan_pose.get(key) != scan_waypoint.get(nav_key) for key, nav_key in (("x", "x"), ("y", "y"), ("yaw", "theta"))):
            fail(f"scan binding {scan_id} must match its location marker and Nav waypoint")
        scan_seed = locations.get(scan_id)
        if not scan_seed:
            fail(f"Main seed missing bound scan {scan_id}")
        _, x, y, yaw, marker, map_id = scan_seed
        if (x, y, yaw, marker, map_id) != (scan_pose["x"], scan_pose["y"], scan_pose["yaw"], str(scan["marker_id"]), binding["map_id"]):
            fail(f"Main seed {scan_id} conflicts with field-bindings.json")


def check_robots_routes_maps_bridges() -> tuple[list[dict], dict]:
    robots_doc = load_json(NAV / "config/robots.json")
    routes = load_json(NAV / "config/main_server_routes.json")
    assert isinstance(robots_doc, dict) and isinstance(routes, dict)
    robots = robots_doc.get("robots")
    route_robots = routes.get("robots")
    if not isinstance(robots, list) or not robots or not isinstance(route_robots, list):
        fail("robots.json and main_server_routes.json must each have a non-empty robots list")

    for key in ("robot_id", "bridge_robot_id", "ros_domain_id", "api_port"):
        unique([robot.get(key) for robot in robots], f"robots.json {key}")
    robot_by_id = {str(robot["robot_id"]): robot for robot in robots}
    if set(robot_by_id) != {str(route.get("robot_id")) for route in route_robots}:
        fail("main_server_routes robot IDs must exactly match robots.json")

    for robot in robots:
        robot_id = str(robot["robot_id"])
        bridge_id = str(robot["bridge_robot_id"])
        if not str(robot.get("namespace", "")).startswith("/"):
            fail(f"{robot_id}.namespace must be absolute")
        map_rel = robot.get("active_map_yaml")
        if not isinstance(map_rel, str) or not (NAV / map_rel).is_file():
            fail(f"{robot_id}.active_map_yaml does not exist: {map_rel!r}")
        if robot.get("localization", {}).get("map_metadata_identity") != map_rel:
            fail(f"{robot_id}.localization.map_metadata_identity must equal active_map_yaml")
        if robot.get("localization", {}).get("map_id") != Path(map_rel).stem:
            fail(f"{robot_id}.localization.map_id must equal active_map_yaml stem")
        image = yaml_scalar(NAV / map_rel, "image")
        if not image or not (NAV / map_rel).parent.joinpath(image).is_file():
            fail(f"{robot_id} active map image is missing for {map_rel}")

        # zones.json has one canonical coordinate frame.  Audit it against
        # every enabled robot map, rather than only the default map selected by
        # validate_zones.py, so a second robot cannot inherit invalid poses.
        if robot.get("enabled") and any(robot.get("field_dispatch", {}).get(kind, False) for kind in ("inbound", "outbound")):
            result = subprocess.run(
                [sys.executable, str(NAV / "scripts/validate_zones.py")],
                cwd=NAV,
                env={**__import__("os").environ, "ACTIVE_MAP_YAML": str(NAV / map_rel)},
                text=True,
                capture_output=True,
                check=False,
            )
            if result.returncode:
                detail = (result.stdout + result.stderr).strip().replace("\n", "; ")
                fail(f"{robot_id}.active_map_yaml fails zones/waypoints audit: {detail}")

        route = next(route for route in route_robots if route.get("robot_id") == robot_id)
        for key in ("bridge_robot_id", "ros_domain_id", "center_domain_id"):
            if route.get(key) != robot.get(key):
                fail(f"{robot_id} route {key} must match robots.json")
        if "nav_api_fallback_url" in route:
            fail(f"{robot_id} must not declare automatic fixed-IP fallback routing")
        require_url(route.get("nav_api_url"), f"{robot_id}.nav_api_url")
        parsed = urlparse(str(route["nav_api_url"]))
        if parsed.port != robot["api_port"]:
            fail(f"{robot_id}.nav_api_url port must equal api_port")
        require_network_host(parsed.hostname, f"{robot_id}.nav_api_url hostname")
        if f"/mission/{bridge_id}/teleop_cmd" != robot.get("teleop_command_topic"):
            fail(f"{robot_id} teleop topic must use bridge_robot_id")
        if f"/mission/{bridge_id}/camera/compressed" != robot.get("camera_topic"):
            fail(f"{robot_id} camera topic must use bridge_robot_id")

        outbound = NAV / "config/domain_bridge" / f"{bridge_id}_to_center.yaml"
        inbound = NAV / "config/domain_bridge" / f"center_to_{bridge_id}.yaml"
        for path, expected_from, expected_to, expected_topics in (
            (outbound, robot["ros_domain_id"], robot["center_domain_id"], {f"mission/{bridge_id}/camera/compressed", f"mission/{bridge_id}/aruco/detections"}),
            (inbound, robot["center_domain_id"], robot["ros_domain_id"], {f"mission/{bridge_id}/teleop_cmd"}),
        ):
            if not path.is_file():
                fail(f"missing domain bridge {path.relative_to(ROOT)}")
            actual_from, actual_to, topics = bridge_document(path)
            if (actual_from, actual_to) != (expected_from, expected_to) or not expected_topics <= topics:
                fail(f"{path.relative_to(ROOT)} does not match {robot_id} domains/topics")

    unique([route.get("nav_api_url") for route in route_robots], "robot nav_api_url")
    require_network_host(routes.get("nav_pc_host"), "main_server_routes.nav_pc_host")
    if routes.get("robot_fixed_ips"):
        fail("main_server_routes must not declare fixed-IP robot routing")
    return robots, routes


def check_nohardware_profile(robots: list[dict]) -> None:
    """Simulation is an explicit fixture, never a production-map substitution."""
    document = load_json(NAV / "config/robots.nohardware.json")
    if not isinstance(document, dict) or document.get("profile") != "nohardware-simulation-v1":
        fail("robots.nohardware.json must declare profile=nohardware-simulation-v1")
    fixtures = document.get("robots")
    if not isinstance(fixtures, list):
        fail("robots.nohardware.json must contain robots")
    production_by_id = {str(robot["robot_id"]): robot for robot in robots}
    fixture_by_id = {str(robot.get("robot_id")): robot for robot in fixtures if isinstance(robot, dict)}
    if set(fixture_by_id) != set(production_by_id):
        fail("nohardware profile robot IDs must match production robots")
    for robot_id, production in production_by_id.items():
        fixture = fixture_by_id[robot_id]
        if fixture.get("simulation_fixture") is not True:
            fail(f"{robot_id} nohardware profile must be explicitly marked simulation_fixture")
        for key in ("active_map_yaml", "localization", "field_dispatch", "capabilities"):
            if fixture.get(key) != production.get(key):
                fail(f"{robot_id} nohardware profile must not relabel production {key}")


def check_locations_markers_and_task_config() -> None:
    zones = load_json(NAV / "map/zones.json")
    inventory = load_json(NAV / "config/inventory_locations.json")
    assert isinstance(zones, dict) and isinstance(inventory, dict)
    waypoints = zones.get("waypoints", {})
    semantic = zones.get("semantic_zones", {})
    if not isinstance(waypoints, dict) or not isinstance(semantic, dict):
        fail("zones.json must contain waypoints and semantic_zones objects")
    for name, pose in waypoints.items():
        finite_pose(pose, f"waypoints.{name}")
    for name in ("inbound_entry", "outbound_entry"):
        if name not in waypoints:
            fail(f"zones.json missing {name}")

    markers: list[int] = []
    for name, zone in semantic.items():
        if not isinstance(zone, dict):
            fail(f"semantic_zones.{name} must be an object")
        marker_id = zone.get("aruco_marker_id")
        if marker_id is None:
            continue
        marker = zone.get("aruco_marker")
        if not isinstance(marker_id, int) or not isinstance(marker, dict) or marker.get("id") != marker_id:
            fail(f"semantic_zones.{name} has inconsistent ArUco marker declaration")
        finite_pose(marker, f"semantic_zones.{name}.aruco_marker")
        markers.append(marker_id)
        for key in ("approach_waypoint", "dock_waypoint"):
            waypoint = zone.get(key)
            if not isinstance(waypoint, str) or waypoint not in waypoints:
                fail(f"semantic_zones.{name}.{key} must reference a waypoint")
        approach = waypoints[zone["approach_waypoint"]]
        if not isinstance(approach.get("aruco_align"), dict):
            fail(f"semantic_zones.{name} approach waypoint must declare aruco_align")
    unique(markers, "ArUco marker IDs")

    for item in inventory.get("items", []):
        if item.get("section_id") not in semantic:
            fail(f"inventory {item.get('item_code')} section_id has no semantic zone")
        for key in ("approach_waypoint", "dock_waypoint"):
            if item.get(key) not in waypoints:
                fail(f"inventory {item.get('item_code')} {key} has no waypoint")

    commands = (MAIN / "database/seed/commands_pg.sql").read_text(encoding="utf-8")
    expected = {
        "INBOUND": ("inbound_scan", "storage_scan", "home", "inbound_load", "storage_unload"),
        "OUTBOUND": ("storage_scan", "outbound_scan", "home", "storage_load", "outbound_unload"),
        "CHARGE": ("charge", "charge"),
    }
    for task, values in expected.items():
        for value in values:
            if f"'{task}'" not in commands or f'"{value}"' not in commands:
                fail(f"commands_pg.sql missing {task} task value {value}")
    fixture = (MAIN / "backend/tests/fixtures/demo_seed_pg.sql").read_text(encoding="utf-8")
    rows = re.findall(
        r"(?m)^\s*\('([^']+)',\s*'([^']+)',\s*'[^']+',\s*([-\d.]+),\s*([-\d.]+),\s*([-\d.]+),\s*(NULL|\d+),\s*'([^']+)'\)",
        fixture,
    )
    if not rows:
        fail("demo_seed_pg.sql has no parseable location seed rows")
    locations = {
        location_id: (kind, float(x), float(y), float(yaw), marker, map_id)
        for location_id, kind, x, y, yaw, marker, map_id in rows
    }
    unique(list(locations), "Main seed location IDs")
    for location_id, (kind, x, y, yaw, marker, map_id) in locations.items():
        if not all(math.isfinite(value) for value in (x, y, yaw)):
            fail(f"Main seed {location_id} has non-finite coordinates")
        if map_id not in {"robot1_map", "robot2_map"}:
            fail(f"Main seed {location_id} has unknown map_id {map_id!r}")
        if kind == "scan":
            parent_id = location_id.removeprefix("scan_")
            parent = locations.get(parent_id)
            if not parent or parent[4] != marker:
                fail(f"Main seed scan {location_id} must pair with its location marker")
    for location_id, kind in (("INBOUND_01", "inbound"), ("OUTBOUND_01", "outbound"), ("HOME_01", "home"), ("CHARGE_01", "charge")):
        if locations.get(location_id, (None,))[0] != kind:
            fail(f"Main seed missing {kind} location {location_id}")
    if not any(kind == "storage" for kind, *_ in locations.values()):
        fail("Main seed must include a storage location")
    check_field_bindings(zones, locations)


def check_ai_sources_and_aruco(robots: list[dict]) -> None:
    sources_path = AI / "config/vision/sources.yaml"
    profiles_path = AI / "config/perception/aruco_pose_profiles.example.json"
    bridge_ids = {str(robot["bridge_robot_id"]) for robot in robots}
    source_robot_ids = set(re.findall(r"(?m)^\s+robot_id:\s*([^\s#]+)", sources_path.read_text(encoding="utf-8"))) - {"null"}
    unknown = source_robot_ids - bridge_ids
    if unknown:
        fail(f"AI source robot IDs have no robots.json bridge mapping: {sorted(unknown)}")
    profiles = load_json(profiles_path)
    assert isinstance(profiles, dict)
    marker_ids = {
        zone["aruco_marker_id"]
        for zone in load_json(NAV / "map/zones.json")["semantic_zones"].values()
        if isinstance(zone, dict) and "aruco_marker_id" in zone
    }
    for name, profile in profiles.get("profiles", {}).items():
        marker = str(profile.get("marker_id", ""))
        match = re.fullmatch(r"ARUCO_(\d+)X\1_(\d+)_(\d+)", marker)
        if not match:
            fail(f"ArUco profile {name} has invalid dictionary/marker ID: {marker!r}")
        marker_id = int(match.group(3))
        if marker_id not in marker_ids:
            fail(f"ArUco profile {name} marker {marker_id} is absent from zones.json")
        source = profile.get("source")
        if source and f"source_id: {source}" not in sources_path.read_text(encoding="utf-8"):
            fail(f"ArUco profile {name} source does not exist: {source}")


def main() -> int:
    try:
        robots, _ = check_robots_routes_maps_bridges()
        check_nohardware_profile(robots)
        check_locations_markers_and_task_config()
        check_ai_sources_and_aruco(robots)
    except AssertionError as exc:
        print(f"[field-config] FAILED: {exc}", file=sys.stderr)
        return 1
    print("[field-config] PASSED: declarative robot, route, map, bridge, waypoint, marker, task, and AI-source links are consistent")
    print("[field-config] NOT CHECKED: network reachability and physical-coordinate accuracy")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
