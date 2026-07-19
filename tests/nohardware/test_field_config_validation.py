"""Regression tests for field-configuration validation entry points."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
CHECKER_PATH = ROOT / "tests/nohardware/check_field_config.py"


def _load_checker():
    spec = importlib.util.spec_from_file_location("field_config_checker_test", CHECKER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_accepts_valid_dns_hostname_for_field_endpoint():
    checker = _load_checker()

    checker.require_network_host("smartfactory-nav.local", "nav endpoint")


def test_rejects_non_loopback_ipv4_for_field_endpoint():
    checker = _load_checker()

    with pytest.raises(AssertionError, match="DNS hostname"):
        checker.require_network_host("192.168.30.102", "robot address")


def test_rejects_invalid_host_for_field_endpoint():
    checker = _load_checker()

    with pytest.raises(AssertionError, match="valid DNS hostname"):
        checker.require_network_host("nav host/invalid", "nav endpoint")


def test_rejects_loopback_ipv4_for_field_endpoint():
    checker = _load_checker()

    with pytest.raises(AssertionError, match="DNS hostname"):
        checker.require_network_host("127.0.0.1", "nav endpoint")


def test_rejects_automatic_fixed_ip_fallback_route(monkeypatch):
    checker = _load_checker()
    original_load_json = checker.load_json
    routes_path = checker.NAV / "config/main_server_routes.json"
    routes = json.loads(routes_path.read_text(encoding="utf-8"))
    routes["robots"][0]["nav_api_fallback_url"] = "http://192.168.30.102:8001"

    def load_json(path):
        if path == routes_path:
            return routes
        return original_load_json(path)

    monkeypatch.setattr(checker, "load_json", load_json)

    with pytest.raises(AssertionError, match="automatic fixed-IP fallback routing"):
        checker.check_robots_routes_maps_bridges()


def test_robot2_map_dispatch_is_scoped_to_the_commissioned_tb2_live_path():
    nav = ROOT / "nav-server"
    main = ROOT / "main-server"
    production = json.loads((nav / "config/robots.json").read_text(encoding="utf-8"))
    nohardware = json.loads((nav / "config/robots.nohardware.json").read_text(encoding="utf-8"))
    routes = json.loads((nav / "config/main_server_routes.json").read_text(encoding="utf-8"))
    bindings = json.loads((main / "backend/config/field-bindings.json").read_text(encoding="utf-8"))

    blocked = {
        "inbound": False,
        "outbound": False,
        "status": "BLOCKED_PENDING_PER_MAP_FIELD_BINDINGS",
    }
    commissioned_tb2 = {
        "inbound": True,
        "outbound": True,
        "status": "COMMISSIONED_TB2_PHYSICAL_LEVEL1",
    }
    for document in (production, nohardware):
        robot1 = next(robot for robot in document["robots"] if robot["robot_id"] == "tb3_burger_01")
        robot2 = next(robot for robot in document["robots"] if robot["robot_id"] == "tb3_burger_02")
        assert robot1["active_map_yaml"] == "map/robot2_map.yaml"
        assert robot1["localization"]["map_id"] == "robot2_map"
        assert robot1["localization"]["map_metadata_identity"] == "map/robot2_map.yaml"
        assert robot1["field_dispatch"] == blocked
        assert (robot1["ros_domain_id"], robot1["api_port"]) == (2, 8001)
        assert (robot2["ros_domain_id"], robot2["api_port"]) == (5, 8002)
        assert robot2["active_map_yaml"] == "map/robot2_map.yaml"
        assert robot2["field_dispatch"] == (commissioned_tb2 if document is production else blocked)

    robot1_route = next(route for route in routes["robots"] if route["robot_id"] == "tb3_burger_01")
    robot2_route = next(route for route in routes["robots"] if route["robot_id"] == "tb3_burger_02")
    assert (robot1_route["ros_domain_id"], robot1_route["nav_api_url"].rsplit(":", 1)[-1]) == (2, "8001")
    assert (robot2_route["ros_domain_id"], robot2_route["nav_api_url"].rsplit(":", 1)[-1]) == (5, "8002")
    assert bindings["map_dispatch"]["robot2_map"] == {
        "inbound": True,
        "outbound": True,
        "status": "COMMISSIONED",
    }
    assert bindings["map_dispatch"]["robot1_map"]["inbound"] is False
    assert bindings["map_dispatch"]["robot1_map"]["outbound"] is False
    assert (nav / "map/robot2_map.yaml").read_text(encoding="utf-8").splitlines()[0] == "image: robot2_map.pgm"
    assert 'os.getenv("LMS_MOVEMENT_ACTIVE_MAP_ID", "robot2_map")' in (
        main / "backend/app/core/config.py"
    ).read_text(encoding="utf-8")


def test_root_runner_returns_nonzero_without_field_config_passed_after_validation_failure(tmp_path):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    root_runner = scripts / "test-nohardware.sh"
    shutil.copy2(ROOT / "scripts/test-nohardware.sh", root_runner)
    (scripts / "test-nohardware-config.sh").write_text(
        "#!/usr/bin/env bash\necho '[field-config] FAILED: forced failure' >&2\nexit 17\n",
        encoding="utf-8",
    )
    (scripts / "test-nohardware-config.sh").chmod(0o755)

    result = subprocess.run(["bash", str(root_runner)], text=True, capture_output=True, check=False)

    output = result.stdout + result.stderr
    assert result.returncode != 0
    assert "[nohardware] field-config: FAILED (17)" in output
    assert "[nohardware] field-config: PASSED" not in output
