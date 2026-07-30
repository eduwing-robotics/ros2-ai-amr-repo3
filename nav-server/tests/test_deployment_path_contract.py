"""Deployment scripts must not rely on a particular operator home directory."""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MOVED_SERVICE_MODULES = {
    "aruco_detector_activation",
    "logistics_navigator",
    "mission_manager",
    "route_builder",
    "traffic_manager",
    "zone_lock_manager",
}


def test_importable_nav_services_live_only_in_the_package():
    for module_name in MOVED_SERVICE_MODULES:
        assert (ROOT / "nav_app" / "services" / f"{module_name}.py").is_file()
        assert not (ROOT / "scripts" / f"{module_name}.py").exists()


def test_canonical_app_import_does_not_add_scripts_to_sys_path():
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import json, sys; "
                "import nav_app.app; "
                "print(json.dumps({'paths': sys.path, 'app': nav_app.app.__file__}))"
            ),
        ],
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout)
    resolved_paths = {
        Path(value or ROOT).resolve()
        for value in payload["paths"]
    }

    assert (ROOT / "scripts").resolve() not in resolved_paths
    assert Path(payload["app"]).resolve() == (ROOT / "nav_app" / "app.py").resolve()


def _nav2_skip_policy():
    source = (ROOT / "nav_app" / "services" / "logistics_navigator.py").read_text(encoding="utf-8")
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
    source = (ROOT / "nav_app" / "services" / "logistics_navigator.py").read_text(encoding="utf-8")
    assert "if not navigator.ensure_nav2_ready():" in source
    assert "navigator.nav.waitUntilNav2Active(localizer=\"amcl\")" not in source


def test_nav2_readiness_cannot_reenable_basic_navigator_amcl_seeding():
    path = ROOT / "nav_app" / "services" / "logistics_navigator.py"
    source = path.read_text(encoding="utf-8")
    module = ast.parse(source)
    method = next(
        node
        for node in module.body
        if isinstance(node, ast.ClassDef) and node.name == "LogisticsNavigator"
        for node in node.body
        if isinstance(node, ast.FunctionDef) and node.name == "ensure_nav2_ready"
    )
    method_source = ast.get_source_segment(source, method)

    assert 'for node_name in ("amcl", "bt_navigator")' in method_source
    assert "_wait_for_lifecycle_active(node_name)" in method_source
    assert "waitUntilNav2Active" not in method_source
    assert "NAV2_LOCALIZER" not in method_source


def test_api_runtime_starts_nonblocking_nav2_readiness_monitor():
    source = (ROOT / "nav_app" / "server_core.py").read_text(encoding="utf-8")

    assert "runtime.navigator.start_nav2_readiness_monitor()" in source


def test_deployment_scripts_do_not_embed_operator_home_paths():
    paths = [*ROOT.joinpath("scripts").rglob("*.sh"), ROOT / "map" / "generate_factory_map.py"]
    offenders = [str(path.relative_to(ROOT)) for path in paths if "/home/lucas" in path.read_text() or "/home/musk" in path.read_text()]
    assert offenders == []


def test_overlay_paths_are_explicit_when_they_are_not_repository_relative():
    required = {
        "scripts/restart_robot_camera_tb3_2.sh": "ROBOT_WS_SETUP:?",
        "scripts/robot_sbc/start_bringup.sh": "WS_SETUP:?",
        "scripts/robot_sbc/start_camera.sh": "WS_SETUP:?",
        "scripts/robot_sbc/start_lift_bridge.sh": "LIFT_WS_SETUP:?",
        "scripts/run_center_slot_l2_lift_test.sh": "LIFT_WS_SETUP:?",
    }
    for relative_path, marker in required.items():
        assert marker in (ROOT / relative_path).read_text(encoding="utf-8")


def test_nav2_overlay_default_is_user_portable_and_still_overridable():
    source = (ROOT / "scripts" / "run_nav2_with_initial_pose.sh").read_text(encoding="utf-8")

    assert 'TURTLEBOT3_SETUP="${TURTLEBOT3_SETUP:-$HOME/turtlebot3_ws/install/setup.bash}"' in source
    assert "/home/codelab" not in source


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
