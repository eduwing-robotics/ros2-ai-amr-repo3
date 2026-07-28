#!/usr/bin/env python3
"""Validate Phase 3 robot/domain bridge configuration consistency."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from sim_paths import nav2_config_root

EXPECTED_API_PORTS = {
    "tb3_burger_01": 8001,
    "tb3_burger_02": 8002,
}


class ConfigError(RuntimeError):
    pass


def load_bridge_yaml(path: Path) -> dict[str, object]:
    data: dict[str, object] = {"topics": {}}
    current_topic: str | None = None
    in_topics = False

    for raw in path.read_text(encoding="utf-8").splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        if indent == 0 and line == "topics:":
            in_topics = True
            continue
        if indent == 0 and ":" in line:
            key, value = line.split(":", 1)
            value = value.strip()
            data[key] = int(value) if value.isdigit() else value
            in_topics = False
            current_topic = None
            continue
        if in_topics and indent == 2 and line.endswith(":"):
            current_topic = line[:-1]
            data["topics"][current_topic] = {}
            continue
        if in_topics and indent == 4 and current_topic and ":" in line:
            key, value = line.split(":", 1)
            data["topics"][current_topic][key.strip()] = value.strip()

    return data


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigError(message)


def normalize_topic(topic: str) -> str:
    return topic.lstrip("/")


def bridge_suffix(bridge_robot_id: str) -> str:
    match = re.fullmatch(r"tb3_(\d+)", bridge_robot_id)
    require(match is not None, f"bridge robot id must look like tb3_N: {bridge_robot_id}")
    return match.group(1)


def validate() -> list[str]:
    config_root = nav2_config_root()
    require(config_root is not None, "nav2_REFECTOR not found (set NAV2_REFECTOR_ROOT or clone ../WS/nav2_REFECTOR)")
    robots_json = config_root / "robots.json"
    bridge_root = config_root / "domain_bridge"

    robots = json.loads(robots_json.read_text(encoding="utf-8"))["robots"]
    enabled = [robot for robot in robots if robot.get("enabled", False)]
    require(len(enabled) >= 2, "Phase 3 expects at least two enabled robots")

    seen_domains: set[int] = set()
    seen_bridge_ids: set[str] = set()
    messages: list[str] = []

    for robot in enabled:
        robot_id = str(robot["robot_id"])
        bridge_id = str(robot["bridge_robot_id"])
        robot_domain = int(robot["ros_domain_id"])
        center_domain = int(robot["center_domain_id"])
        suffix = bridge_suffix(bridge_id)

        require(robot_domain not in seen_domains, f"duplicate ROS_DOMAIN_ID: {robot_domain}")
        require(bridge_id not in seen_bridge_ids, f"duplicate bridge_robot_id: {bridge_id}")
        seen_domains.add(robot_domain)
        seen_bridge_ids.add(bridge_id)

        require(center_domain == 1, f"{robot_id} center_domain_id should be 1, got {center_domain}")
        require(robot_id in EXPECTED_API_PORTS, f"missing expected API port mapping for {robot_id}")

        center_to_robot = load_bridge_yaml(bridge_root / f"center_to_tb3_{suffix}.yaml")
        robot_to_center = load_bridge_yaml(bridge_root / f"tb3_{suffix}_to_center.yaml")

        require(center_to_robot.get("from_domain") == center_domain, f"{bridge_id} center_to from_domain mismatch")
        require(center_to_robot.get("to_domain") == robot_domain, f"{bridge_id} center_to to_domain mismatch")
        require(robot_to_center.get("from_domain") == robot_domain, f"{bridge_id} robot_to from_domain mismatch")
        require(robot_to_center.get("to_domain") == center_domain, f"{bridge_id} robot_to to_domain mismatch")

        center_topics = center_to_robot["topics"]
        robot_topics = robot_to_center["topics"]
        require(normalize_topic(str(robot["teleop_command_topic"])) in center_topics, f"{bridge_id} teleop topic missing from center_to bridge")
        require(normalize_topic(str(robot["camera_topic"])) in robot_topics, f"{bridge_id} camera topic missing from robot_to bridge")
        require(normalize_topic(str(robot["aruco_detection_topic"])) in robot_topics, f"{bridge_id} ArUco topic missing from robot_to bridge")

        messages.append(
            f"{robot_id}: bridge={bridge_id} domain={robot_domain} center={center_domain} api_port={EXPECTED_API_PORTS[robot_id]}"
        )

    return messages


def main() -> None:
    try:
        messages = validate()
    except ConfigError as exc:
        raise SystemExit(f"Phase 3 config check failed: {exc}") from exc

    print("Phase 3 config check passed")
    for message in messages:
        print(f"- {message}")


if __name__ == "__main__":
    main()