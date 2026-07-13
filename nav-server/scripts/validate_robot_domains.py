#!/usr/bin/env python3
"""Validate robot/domain routing and domain_bridge configuration."""

import argparse
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG = ROOT / "config" / "robots.json"
DEFAULT_BRIDGE_DIR = ROOT / "config" / "domain_bridge"


REQUIRED_FIELDS = (
    "robot_id",
    "bridge_robot_id",
    "ros_domain_id",
    "center_domain_id",
    "namespace",
    "teleop_command_topic",
    "camera_topic",
    "aruco_detection_topic",
)


def _topic_for_bridge(bridge_robot_id, suffix):
    return f"/mission/{bridge_robot_id}/{suffix}"


def _topic_key(topic):
    return topic.lstrip("/")


def _check_unique(robots, field, errors):
    seen = {}
    for robot in robots:
        value = robot.get(field)
        if value in (None, ""):
            continue
        if value in seen:
            errors.append(
                f"{field} 값이 중복됩니다: {value} "
                f"({seen[value]} / {robot.get('robot_id', '<unknown>')})"
            )
        else:
            seen[value] = robot.get("robot_id", "<unknown>")


def _parse_bridge_yaml(path):
    """Parse the small domain_bridge YAML shape used by this project."""
    result = {"topics": {}}
    current_topic = None

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()

        if indent == 0 and ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if key == "topics":
                continue
            if key in ("from_domain", "to_domain"):
                try:
                    result[key] = int(value)
                except ValueError:
                    result[key] = value
            else:
                result[key] = value
            current_topic = None
        elif indent == 2 and line.endswith(":"):
            current_topic = line[:-1].strip()
            result["topics"][current_topic] = {}
        elif indent >= 4 and current_topic and ":" in line:
            key, value = line.split(":", 1)
            result["topics"][current_topic][key.strip()] = value.strip()

    return result


def _expect_bridge_file(path, name, from_domain, to_domain, topic, msg_type, errors):
    if not path.exists():
        errors.append(f"domain_bridge YAML이 없습니다: {path}")
        return

    data = _parse_bridge_yaml(path)
    label = path.name

    if data.get("name") != name:
        errors.append(f"{label}: name={data.get('name')}, 기대값={name}")
    if data.get("from_domain") != from_domain:
        errors.append(f"{label}: from_domain={data.get('from_domain')}, 기대값={from_domain}")
    if data.get("to_domain") != to_domain:
        errors.append(f"{label}: to_domain={data.get('to_domain')}, 기대값={to_domain}")

    topic_key = _topic_key(topic)
    topics = data.get("topics", {})
    if topic_key not in topics:
        errors.append(f"{label}: topic이 없습니다: {topic_key}")
        return

    actual_type = topics[topic_key].get("type")
    if actual_type != msg_type:
        errors.append(f"{label}: {topic_key} type={actual_type}, 기대값={msg_type}")


def _validate_bridge_files(robots, bridge_dir, errors):
    if not bridge_dir.exists():
        errors.append(f"domain_bridge 디렉터리가 없습니다: {bridge_dir}")
        return

    expected_files = set()
    for robot in robots:
        if not robot.get("enabled", True):
            continue

        bridge_robot_id = robot.get("bridge_robot_id")
        if not bridge_robot_id:
            continue

        center_domain_id = int(robot.get("center_domain_id"))
        ros_domain_id = int(robot.get("ros_domain_id"))
        teleop_topic = robot.get("teleop_command_topic")
        camera_topic = robot.get("camera_topic")
        aruco_detection_topic = robot.get("aruco_detection_topic")

        center_to_robot = bridge_dir / f"center_to_{bridge_robot_id}.yaml"
        robot_to_center = bridge_dir / f"{bridge_robot_id}_to_center.yaml"
        expected_files.update({center_to_robot.name, robot_to_center.name})

        nav_local_domain = robot.get("nav_local_domain_id")
        if nav_local_domain is not None:
            hardware_nav = bridge_dir / f"{bridge_robot_id}_hardware_nav.yaml"
            expected_files.add(hardware_nav.name)
            _expect_bridge_file(
                hardware_nav,
                name=f"{bridge_robot_id}_hardware_nav",
                from_domain=ros_domain_id,
                to_domain=int(nav_local_domain),
                topic="/scan",
                msg_type="sensor_msgs/msg/LaserScan",
                errors=errors,
            )
            _expect_bridge_file(
                hardware_nav,
                name=f"{bridge_robot_id}_hardware_nav",
                from_domain=ros_domain_id,
                to_domain=int(nav_local_domain),
                topic="/cmd_vel",
                msg_type="geometry_msgs/msg/TwistStamped",
                errors=errors,
            )

        _expect_bridge_file(
            center_to_robot,
            name=f"center_to_{bridge_robot_id}",
            from_domain=center_domain_id,
            to_domain=ros_domain_id,
            topic=teleop_topic,
            msg_type="std_msgs/msg/String",
            errors=errors,
        )
        _expect_bridge_file(
            robot_to_center,
            name=f"{bridge_robot_id}_to_center",
            from_domain=ros_domain_id,
            to_domain=center_domain_id,
            topic=camera_topic,
            msg_type="sensor_msgs/msg/CompressedImage",
            errors=errors,
        )
        _expect_bridge_file(
            robot_to_center,
            name=f"{bridge_robot_id}_to_center",
            from_domain=ros_domain_id,
            to_domain=center_domain_id,
            topic=aruco_detection_topic,
            msg_type="std_msgs/msg/String",
            errors=errors,
        )

    for path in bridge_dir.glob("*.yaml"):
        if path.name not in expected_files:
            errors.append(f"예상하지 않은 domain_bridge YAML입니다: {path.name}")


def validate(config_path, bridge_dir=None):
    data = json.loads(config_path.read_text(encoding="utf-8"))
    robots = data.get("robots")
    errors = []

    if not isinstance(robots, list) or not robots:
        return ["robots 배열이 비어 있거나 없습니다."]

    for index, robot in enumerate(robots):
        label = robot.get("robot_id", f"robots[{index}]")

        for field in REQUIRED_FIELDS:
            if field not in robot:
                errors.append(f"{label}: 필수 필드가 없습니다: {field}")

        if not robot.get("enabled", True):
            continue

        robot_id = robot.get("robot_id", "")
        bridge_robot_id = robot.get("bridge_robot_id", "")
        namespace = robot.get("namespace", "")
        teleop_topic = robot.get("teleop_command_topic", "")
        camera_topic = robot.get("camera_topic", "")
        aruco_detection_topic = robot.get("aruco_detection_topic", "")

        try:
            ros_domain_id = int(robot.get("ros_domain_id"))
        except (TypeError, ValueError):
            errors.append(f"{label}: ros_domain_id는 정수여야 합니다.")
            ros_domain_id = None

        try:
            center_domain_id = int(robot.get("center_domain_id"))
        except (TypeError, ValueError):
            errors.append(f"{label}: center_domain_id는 정수여야 합니다.")
            center_domain_id = None

        nav_local_domain_id = robot.get("nav_local_domain_id")
        if nav_local_domain_id is not None:
            try:
                nav_local_domain_id = int(nav_local_domain_id)
            except (TypeError, ValueError):
                errors.append(f"{label}: nav_local_domain_id는 정수여야 합니다.")
                nav_local_domain_id = None
            if nav_local_domain_id is not None and nav_local_domain_id == ros_domain_id:
                errors.append(f"{label}: nav_local_domain_id와 ros_domain_id는 달라야 합니다.")

        if ros_domain_id == center_domain_id:
            errors.append(f"{label}: center_domain_id와 ros_domain_id가 같으면 브릿지 경계가 없습니다.")

        if robot_id and bridge_robot_id and robot_id == bridge_robot_id:
            errors.append(f"{label}: robot_id와 bridge_robot_id는 명시적으로 분리해야 합니다.")

        if namespace and not namespace.startswith("/"):
            errors.append(f"{label}: namespace는 '/'로 시작해야 합니다: {namespace}")

        expected_teleop = _topic_for_bridge(bridge_robot_id, "teleop_cmd")
        if bridge_robot_id and teleop_topic != expected_teleop:
            errors.append(f"{label}: teleop_command_topic={teleop_topic}, 기대값={expected_teleop}")

        expected_camera = _topic_for_bridge(bridge_robot_id, "camera/compressed")
        if bridge_robot_id and camera_topic != expected_camera:
            errors.append(f"{label}: camera_topic={camera_topic}, 기대값={expected_camera}")

        expected_aruco = _topic_for_bridge(bridge_robot_id, "aruco/detections")
        if bridge_robot_id and aruco_detection_topic != expected_aruco:
            errors.append(f"{label}: aruco_detection_topic={aruco_detection_topic}, 기대값={expected_aruco}")

    _check_unique(robots, "robot_id", errors)
    _check_unique(robots, "bridge_robot_id", errors)
    _check_unique(robots, "ros_domain_id", errors)
    _check_unique(robots, "namespace", errors)
    _check_unique(robots, "teleop_command_topic", errors)
    _check_unique(robots, "camera_topic", errors)
    _check_unique(robots, "aruco_detection_topic", errors)

    if bridge_dir is not None and not errors:
        _validate_bridge_files(robots, bridge_dir, errors)

    return errors


def main():
    parser = argparse.ArgumentParser(description="Validate logistics robot domain routing config.")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="Path to robots.json")
    parser.add_argument(
        "--bridge-dir",
        type=Path,
        default=DEFAULT_BRIDGE_DIR,
        help="Path to domain_bridge YAML directory",
    )
    parser.add_argument(
        "--skip-bridge-files",
        action="store_true",
        help="Only validate robots.json and skip domain_bridge YAML checks",
    )
    args = parser.parse_args()

    if not args.config.exists():
        print(f"[검증 실패] 설정 파일이 없습니다: {args.config}", file=sys.stderr)
        return 1

    try:
        bridge_dir = None if args.skip_bridge_files else args.bridge_dir
        errors = validate(args.config, bridge_dir)
    except json.JSONDecodeError as exc:
        print(f"[검증 실패] JSON 파싱 실패: {exc}", file=sys.stderr)
        return 1
    except (TypeError, ValueError) as exc:
        print(f"[검증 실패] 설정 값 파싱 실패: {exc}", file=sys.stderr)
        return 1

    if errors:
        print("[검증 실패] robot domain routing 설정 오류:")
        for error in errors:
            print(f"- {error}")
        return 1

    print(f"[검증 성공] robot domain routing 설정 정상: {args.config}")
    if bridge_dir is not None:
        print(f"[검증 성공] domain_bridge YAML 설정 정상: {bridge_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
