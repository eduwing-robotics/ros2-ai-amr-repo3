"""Deployment scripts must not rely on a particular operator home directory."""

from __future__ import annotations

import ast
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _nav2_skip_policy():
    source = (ROOT / "scripts" / "logistics_navigator.py").read_text(encoding="utf-8")
    module = ast.parse(source)
    function = next(
        node for node in module.body if isinstance(node, ast.FunctionDef) and node.name == "nav2_active_wait_is_skipped"
    )
    namespace = {"os": os}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "<nav2-policy>", "exec"), namespace)
    return namespace["nav2_active_wait_is_skipped"]


def test_nav2_active_wait_skip_is_simulation_only(monkeypatch):
    policy = _nav2_skip_policy()
    monkeypatch.setenv("NAV2_SKIP_ACTIVE_WAIT", "1")
    monkeypatch.setenv("SIMULATION_MODE", "0")

    with pytest.raises(RuntimeError, match="SIMULATION_MODE=1"):
        policy()

    monkeypatch.setenv("SIMULATION_MODE", "1")
    assert policy() is True


def test_nav2_cli_uses_the_guarded_readiness_path():
    source = (ROOT / "scripts" / "logistics_navigator.py").read_text(encoding="utf-8")
    assert "if not navigator.ensure_nav2_ready():" in source
    assert "navigator.nav.waitUntilNav2Active(localizer=\"amcl\")" not in source


def test_deployment_scripts_do_not_embed_operator_home_paths():
    paths = [*ROOT.joinpath("scripts").rglob("*.sh"), ROOT / "map" / "generate_factory_map.py"]
    offenders = [str(path.relative_to(ROOT)) for path in paths if "/home/lucas" in path.read_text() or "/home/musk" in path.read_text()]
    assert offenders == []


def test_overlay_paths_are_explicit_when_they_are_not_repository_relative():
    required = {
        "scripts/run_nav2_with_initial_pose.sh": "TURTLEBOT3_SETUP:?",
        "scripts/restart_robot_camera_tb3_2.sh": "ROBOT_WS_SETUP:?",
        "scripts/robot_sbc/start_bringup.sh": "WS_SETUP:?",
        "scripts/robot_sbc/start_camera.sh": "WS_SETUP:?",
        "scripts/robot_sbc/start_lift_bridge.sh": "LIFT_WS_SETUP:?",
        "scripts/run_center_slot_l2_lift_test.sh": "LIFT_WS_SETUP:?",
    }
    for relative_path, marker in required.items():
        assert marker in (ROOT / relative_path).read_text(encoding="utf-8")


def test_main_routes_are_hostname_based_without_automatic_fallbacks():
    routes = json.loads((ROOT / "config" / "main_server_routes.json").read_text(encoding="utf-8"))
    serialized = json.dumps(routes)

    assert routes["nav_pc_host"] == "smartfactory-nav.local"
    assert "fallback" not in serialized
    assert "127.0.0.1" not in serialized
    assert "localhost" not in serialized
    assert "192.168." not in serialized
    assert all("smartfactory-nav.local" in robot["nav_api_url"] for robot in routes["robots"])
    assert routes["main_public_base_url"] == "http://smartfactory-main.local:8088"
    assert routes["main_api_base"] == "http://smartfactory-main.local:8088/api/v1"
    assert routes["webhook_endpoint"].startswith("http://smartfactory-main.local:8088/")


def test_explicit_nohardware_robot_configuration_is_preserved():
    nohardware = json.loads((ROOT / "config" / "robots.nohardware.json").read_text(encoding="utf-8"))
    assert nohardware["profile"] == "nohardware-simulation-v1"
    assert all(robot["simulation_fixture"] is True for robot in nohardware["robots"])


def test_endpoint_environment_overrides_take_precedence_over_route_defaults():
    env = os.environ | {
        "PYTHONPATH": str(ROOT),
        "NAV_PC_HOST": "nav-overlay.example",
        "MAIN_API_BASE": "https://main-overlay.example/api/v1",
        "WEBHOOK_ENDPOINT": "https://main-overlay.example/api/v1/movement/command-events",
        "HOSTNAME_RESOLVE_TIMEOUT_SEC": "0",
    }
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from nav_app.config.loader import active_endpoint_contract; import json; print(json.dumps(active_endpoint_contract()))",
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    endpoint = json.loads(result.stdout)
    assert endpoint["nav_api_url"] == "http://nav-overlay.example:8001"
    assert endpoint["main_api_base"] == "https://main-overlay.example/api/v1"
    assert endpoint["command_events_endpoint"] == "https://main-overlay.example/api/v1/movement/command-events"
    assert endpoint["webhook_endpoint"] == "https://main-overlay.example/api/v1/movement/command-events"
