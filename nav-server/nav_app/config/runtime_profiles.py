"""Resolve profile-first Nav runtime configuration without mutating hardware facts."""

from __future__ import annotations

import argparse
import json
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

NAV_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST_PATH = NAV_ROOT / "config" / "runtime_profiles" / "manifest.json"
DEFAULT_ROBOTS_PATH = NAV_ROOT / "config" / "robots.json"

MANIFEST_KEYS = {"schema_version", "default_profile", "profiles"}
PROFILE_KEYS = {
    "profile_id",
    "enabled",
    "execution_class",
    "evidence_class",
    "robot_selector",
    "components",
    "lift_backends",
    "virtual_lift",
}
SELECTOR_KEYS = {"robot_ids", "enabled_robots"}
COMPONENT_KEYS = {"enabled", "required", "ownership", "start_script", "readiness_probe", "robot_ids"}
OWNERSHIP_VALUES = {"external", "managed-script", "service-managed"}
EXECUTION_CLASSES = {"live", "synthetic_hil"}
EVIDENCE_CLASSES = {"physical", "nonphysical"}
VIRTUAL_LIFT_KEYS = {"enabled", "backend"}
LIFT_BACKEND_VALUES = {"disabled", "virtual", "physical"}


class RuntimeProfileError(ValueError):
    """Raised when a runtime profile contract fails closed."""


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeProfileError(f"{label} not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeProfileError(f"{label} is not valid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeProfileError(f"{label} must be an object")
    return value


def _require_exact_keys(value: Mapping[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise RuntimeProfileError(f"{label} contains unknown keys: {', '.join(unknown)}")


def load_manifest(path: Path = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    manifest = _read_json(path, "runtime profile manifest")
    _require_exact_keys(manifest, MANIFEST_KEYS, "runtime profile manifest")
    if manifest.get("schema_version") != 1:
        raise RuntimeProfileError("runtime profile manifest schema_version must be 1")
    profiles = manifest.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise RuntimeProfileError("runtime profile manifest profiles must be a non-empty object")
    default_profile = manifest.get("default_profile")
    if not isinstance(default_profile, str) or default_profile not in profiles:
        raise RuntimeProfileError("runtime profile manifest must declare one registered default_profile")
    for profile_id, relative_path in profiles.items():
        if not isinstance(profile_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", profile_id):
            raise RuntimeProfileError("runtime profile IDs must use basename-safe letters, digits, dot, underscore, or dash")
        if not isinstance(relative_path, str) or not relative_path or Path(relative_path).is_absolute():
            raise RuntimeProfileError(f"{profile_id}: profile path must be relative")
    return manifest


def select_profile_id(
    manifest: Mapping[str, Any], cli_profile: str | None = None, environment: Mapping[str, str] | None = None
) -> tuple[str, str]:
    env = os.environ if environment is None else environment
    if cli_profile:
        selected, source = cli_profile, "cli"
    elif env.get("SF_NAV_PROFILE"):
        selected, source = env["SF_NAV_PROFILE"], "environment"
    else:
        selected, source = str(manifest["default_profile"]), "manifest_default"
    if selected not in manifest["profiles"]:
        raise RuntimeProfileError(f"unknown runtime profile: {selected}")
    return selected, source


def _validate_profile(profile: dict[str, Any], expected_id: str) -> None:
    _require_exact_keys(profile, PROFILE_KEYS, expected_id)
    if profile.get("profile_id") != expected_id:
        raise RuntimeProfileError(f"{expected_id}: profile_id does not match manifest registry")
    if profile.get("enabled") is not True:
        raise RuntimeProfileError(f"{expected_id}: profile is disabled")
    execution_class = profile.get("execution_class")
    evidence_class = profile.get("evidence_class")
    if execution_class not in EXECUTION_CLASSES:
        raise RuntimeProfileError(f"{expected_id}: invalid execution_class")
    if evidence_class not in EVIDENCE_CLASSES:
        raise RuntimeProfileError(f"{expected_id}: invalid evidence_class")
    virtual_lift = profile.get("virtual_lift")
    if virtual_lift is not None:
        if not isinstance(virtual_lift, dict):
            raise RuntimeProfileError(f"{expected_id}: virtual_lift must be an object")
        _require_exact_keys(virtual_lift, VIRTUAL_LIFT_KEYS, f"{expected_id}.virtual_lift")
        if virtual_lift.get("enabled") not in {True, False}:
            raise RuntimeProfileError(f"{expected_id}: virtual_lift.enabled must be boolean")
        if execution_class == "live" and virtual_lift.get("enabled") is True:
            raise RuntimeProfileError(f"{expected_id}: live profiles cannot enable virtual_lift")
        if virtual_lift.get("backend") != "deterministic":
            raise RuntimeProfileError(f"{expected_id}: unsupported virtual_lift backend")
    if execution_class == "synthetic_hil" and evidence_class != "nonphysical":
        raise RuntimeProfileError(f"{expected_id}: synthetic_hil evidence must be nonphysical")
    if execution_class == "synthetic_hil" and not (isinstance(virtual_lift, dict) and virtual_lift.get("enabled") is True):
        raise RuntimeProfileError(f"{expected_id}: synthetic_hil requires enabled virtual_lift")

    lift_backends = profile.get("lift_backends")
    if not isinstance(lift_backends, dict) or not lift_backends:
        raise RuntimeProfileError(f"{expected_id}: lift_backends must be a non-empty object")
    invalid_lift_backends = sorted(
        robot_id
        for robot_id, backend in lift_backends.items()
        if not isinstance(robot_id, str) or not robot_id or backend not in LIFT_BACKEND_VALUES
    )
    if invalid_lift_backends:
        raise RuntimeProfileError(f"{expected_id}: invalid lift_backends entry: {', '.join(invalid_lift_backends)}")
    if execution_class == "live" and "virtual" in lift_backends.values():
        raise RuntimeProfileError(f"{expected_id}: live profiles cannot select a virtual lift backend")
    if execution_class == "synthetic_hil" and set(lift_backends.values()) != {"virtual"}:
        raise RuntimeProfileError(f"{expected_id}: synthetic_hil robots must select the virtual lift backend")

    selector = profile.get("robot_selector")
    if not isinstance(selector, dict):
        raise RuntimeProfileError(f"{expected_id}: robot_selector must be an object")
    _require_exact_keys(selector, SELECTOR_KEYS, f"{expected_id}.robot_selector")
    if ("robot_ids" in selector) == ("enabled_robots" in selector):
        raise RuntimeProfileError(f"{expected_id}: robot_selector must contain exactly one selector")
    if "robot_ids" in selector:
        robot_ids = selector["robot_ids"]
        if not isinstance(robot_ids, list) or not robot_ids or any(not isinstance(item, str) for item in robot_ids):
            raise RuntimeProfileError(f"{expected_id}: robot_ids must be a non-empty string list")
        if len(robot_ids) != len(set(robot_ids)):
            raise RuntimeProfileError(f"{expected_id}: robot_ids contains duplicates")
    elif selector.get("enabled_robots") is not True:
        raise RuntimeProfileError(f"{expected_id}: enabled_robots must be true")

    components = profile.get("components")
    if not isinstance(components, dict) or not components:
        raise RuntimeProfileError(f"{expected_id}: components must be a non-empty object")
    for name, component in components.items():
        if not isinstance(component, dict):
            raise RuntimeProfileError(f"{expected_id}.{name}: component must be an object")
        _require_exact_keys(component, COMPONENT_KEYS, f"{expected_id}.{name}")
        if component.get("enabled") not in {True, False} or component.get("required") not in {True, False}:
            raise RuntimeProfileError(f"{expected_id}.{name}: enabled and required must be boolean")
        ownership = component.get("ownership")
        if ownership not in OWNERSHIP_VALUES:
            raise RuntimeProfileError(f"{expected_id}.{name}: invalid ownership")
        if ownership == "service-managed":
            raise RuntimeProfileError(f"{expected_id}.{name}: service-managed is not implemented")
        for field in ("start_script", "readiness_probe"):
            if not isinstance(component.get(field), str):
                raise RuntimeProfileError(f"{expected_id}.{name}: {field} must be a string")
        if component["required"] and not component["enabled"]:
            raise RuntimeProfileError(f"{expected_id}.{name}: required component cannot be disabled")
        robot_ids = component.get("robot_ids")
        if robot_ids is not None and (
            not isinstance(robot_ids, list)
            or not robot_ids
            or any(not isinstance(robot_id, str) or not robot_id for robot_id in robot_ids)
            or len(robot_ids) != len(set(robot_ids))
        ):
            raise RuntimeProfileError(f"{expected_id}.{name}: robot_ids must be a non-empty unique string list")


def resolve_runtime_profile(
    *,
    manifest_path: Path = DEFAULT_MANIFEST_PATH,
    robots_path: Path = DEFAULT_ROBOTS_PATH,
    cli_profile: str | None = None,
    environment: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    manifest_path = manifest_path.resolve()
    manifest = load_manifest(manifest_path)
    profile_id, selection_source = select_profile_id(manifest, cli_profile, environment)
    profile_path = (manifest_path.parent / manifest["profiles"][profile_id]).resolve()
    try:
        profile_path.relative_to(manifest_path.parent.resolve())
    except ValueError as exc:
        raise RuntimeProfileError(f"{profile_id}: profile path escapes manifest directory") from exc
    profile = _read_json(profile_path, f"runtime profile {profile_id}")
    _validate_profile(profile, profile_id)

    robots_document = _read_json(robots_path.resolve(), "robots config")
    robots = robots_document.get("robots")
    if not isinstance(robots, list) or not robots:
        raise RuntimeProfileError("robots config must contain a non-empty robots list")
    robot_by_id: dict[str, dict[str, Any]] = {}
    for robot in robots:
        if not isinstance(robot, dict) or not isinstance(robot.get("robot_id"), str):
            raise RuntimeProfileError("robots config contains an invalid robot entry")
        robot_id = robot["robot_id"]
        if robot_id in robot_by_id:
            raise RuntimeProfileError(f"robots config contains duplicate robot_id: {robot_id}")
        robot_by_id[robot_id] = robot

    selector = profile["robot_selector"]
    selected_ids = (
        [robot["robot_id"] for robot in robots if robot.get("enabled", True)]
        if selector.get("enabled_robots") is True
        else list(selector["robot_ids"])
    )
    selected: list[dict[str, Any]] = []
    for robot_id in selected_ids:
        robot = robot_by_id.get(robot_id)
        if robot is None:
            raise RuntimeProfileError(f"{profile_id}: unknown robot reference: {robot_id}")
        if not robot.get("enabled", True):
            raise RuntimeProfileError(f"{profile_id}: disabled robot reference: {robot_id}")
        resolved_robot = deepcopy(robot)
        map_path = Path(str(resolved_robot.get("active_map_yaml", ""))).expanduser()
        if not map_path.is_absolute():
            map_path = NAV_ROOT / map_path
        if not map_path.is_file():
            raise RuntimeProfileError(f"{robot_id}: active_map_yaml does not exist: {map_path.resolve()}")
        resolved_robot["active_map_yaml"] = str(map_path.resolve())
        resolved_robot["nav_local_domain_id"] = int(
            resolved_robot.get("nav_local_domain_id", resolved_robot["ros_domain_id"])
        )
        selected.append(resolved_robot)

    selected_id_set = set(selected_ids)
    lift_backends = deepcopy(profile["lift_backends"])
    if set(lift_backends) != selected_id_set:
        missing = sorted(selected_id_set - set(lift_backends))
        extra = sorted(set(lift_backends) - selected_id_set)
        detail = []
        if missing:
            detail.append(f"missing={','.join(missing)}")
        if extra:
            detail.append(f"unselected={','.join(extra)}")
        raise RuntimeProfileError(f"{profile_id}: lift_backends must exactly match selected robots ({'; '.join(detail)})")
    for robot in selected:
        robot_id = str(robot["robot_id"])
        backend = lift_backends[robot_id]
        if backend == "physical":
            capabilities = {str(value) for value in robot.get("capabilities") or []}
            lift = robot.get("lift") if isinstance(robot.get("lift"), dict) else {}
            if "lift" not in capabilities or lift.get("enabled") is not True:
                raise RuntimeProfileError(
                    f"{profile_id}: {robot_id} cannot select physical lift without enabled lift hardware facts"
                )

    for name, component in profile["components"].items():
        component_robot_ids = component.get("robot_ids")
        if component_robot_ids is not None and not set(component_robot_ids) <= selected_id_set:
            raise RuntimeProfileError(f"{profile_id}.{name}: component robot_ids must be selected by the profile")

    resources = {
        "robot_ids": [str(robot["robot_id"]) for robot in selected],
        "api_ports": [int(robot["api_port"]) for robot in selected],
        "hardware_ros_domain_ids": [int(robot["ros_domain_id"]) for robot in selected],
        "nav_local_ros_domain_ids": [int(robot["nav_local_domain_id"]) for robot in selected],
    }
    for name, values in resources.items():
        if len(values) != len(set(values)):
            raise RuntimeProfileError(f"{profile_id}: selected resource collision in {name}")

    return {
        "schema_version": 1,
        "profile_id": profile_id,
        "selection_source": selection_source,
        "execution_class": profile["execution_class"],
        "evidence_class": profile["evidence_class"],
        "robots": selected,
        "components": deepcopy(profile["components"]),
        "lift_backends": lift_backends,
        "selected_resources": resources,
        **({"virtual_lift": deepcopy(profile["virtual_lift"])} if "virtual_lift" in profile else {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST_PATH)
    parser.add_argument("--robots", type=Path, default=DEFAULT_ROBOTS_PATH)
    parser.add_argument("--profile")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--tsv", action="store_true")
    args = parser.parse_args()
    try:
        if args.list:
            manifest = load_manifest(args.manifest.resolve())
            for profile_id in manifest["profiles"]:
                suffix = " (default)" if profile_id == manifest["default_profile"] else ""
                print(f"{profile_id}{suffix}")
            return 0
        resolved = resolve_runtime_profile(
            manifest_path=args.manifest, robots_path=args.robots, cli_profile=args.profile
        )
    except RuntimeProfileError as exc:
        parser.error(str(exc))
    if args.tsv:
        for robot in resolved["robots"]:
            print(
                "\t".join(
                    str(robot[field])
                    for field in ("robot_id", "ros_domain_id", "nav_local_domain_id", "api_port", "active_map_yaml")
                )
            )
    else:
        print(json.dumps(resolved, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
