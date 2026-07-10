#!/usr/bin/env python3
"""Build and validate the config-driven Nav API bringup plan."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import importlib.util  # noqa: E402

_VALIDATION_PATH = ROOT / "nav_app" / "config" / "validation.py"
_SPEC = importlib.util.spec_from_file_location("nav_config_validation", _VALIDATION_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise RuntimeError(f"cannot load validation helper: {_VALIDATION_PATH}")
_VALIDATION = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_VALIDATION)
validate_robots_document = _VALIDATION.validate_robots_document


def _as_int(robot_id: str, field: str, value: Any, errors: list[str]) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        errors.append(f"{robot_id}: {field} must be an integer")
        return None


def _resolve_map_path(raw_path: Any, errors: list[str], robot_id: str) -> str | None:
    if raw_path in (None, ""):
        errors.append(f"{robot_id}: missing active_map_yaml")
        return None
    path = Path(str(raw_path)).expanduser()
    if not path.is_absolute():
        path = ROOT / path
    path = path.resolve()
    if not path.is_file():
        errors.append(f"{robot_id}: active_map_yaml does not exist: {path}")
        return None
    return str(path)


def build_plan(config_path: Path, host: str, python_bin: str) -> tuple[dict[str, Any] | None, list[str]]:
    errors: list[str] = []
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None, [f"robots config not found: {config_path}"]
    except json.JSONDecodeError as exc:
        return None, [f"robots config is not valid JSON: {exc}"]

    errors.extend(validate_robots_document(data))
    robots = data.get("robots") if isinstance(data, dict) else None
    if not isinstance(robots, list):
        return None, errors or ["robots.json must contain a robots list"]

    plan_robots: list[dict[str, Any]] = []
    ports: dict[int, str] = {}
    domains: dict[int, str] = {}
    for index, robot in enumerate(robots):
        if not isinstance(robot, dict):
            continue
        if not robot.get("enabled", True):
            continue
        robot_id = str(robot.get("robot_id") or f"robots[{index}]")
        ros_domain_id = _as_int(robot_id, "ros_domain_id", robot.get("ros_domain_id"), errors)
        api_port = _as_int(robot_id, "api_port", robot.get("api_port"), errors)
        active_map_yaml = _resolve_map_path(robot.get("active_map_yaml"), errors, robot_id)
        if ros_domain_id is None or api_port is None or active_map_yaml is None:
            continue
        if api_port in ports:
            errors.append(f"api_port duplicate: {api_port} ({ports[api_port]} / {robot_id})")
        else:
            ports[api_port] = robot_id
        if ros_domain_id in domains:
            errors.append(f"ros_domain_id duplicate: {ros_domain_id} ({domains[ros_domain_id]} / {robot_id})")
        else:
            domains[ros_domain_id] = robot_id
        plan_robots.append(
            {
                "robot_id": robot_id,
                "ros_domain_id": ros_domain_id,
                "api_port": api_port,
                "active_map_yaml": active_map_yaml,
            }
        )

    if not plan_robots:
        errors.append("no enabled robots in robots config")

    plan = {
        "config_path": str(config_path.resolve()),
        "host": host,
        "python_bin": python_bin,
        "app": "nav_app.app:app",
        "robots": sorted(plan_robots, key=lambda item: item["robot_id"]),
    }
    return plan, errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--python-bin", required=True)
    parser.add_argument("--print-plan", action="store_true")
    parser.add_argument("--tsv", action="store_true", help="Print robot_id, ros_domain_id, api_port, active_map_yaml rows")
    args = parser.parse_args()

    plan, errors = build_plan(args.config, args.host, args.python_bin)
    if errors:
        for error in errors:
            print(f"[nav_servers] {error}", file=sys.stderr)
        return 1
    assert plan is not None

    if args.tsv:
        for robot in plan["robots"]:
            print(
                f"{robot['robot_id']}\t{robot['ros_domain_id']}\t{robot['api_port']}\t{robot['active_map_yaml']}",
                flush=True,
            )
    else:
        print(json.dumps(plan, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
