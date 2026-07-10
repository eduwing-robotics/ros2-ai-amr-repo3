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


def test_accepts_non_loopback_ipv4_for_field_endpoint():
    checker = _load_checker()

    checker.require_network_host("192.168.30.102", "robot address")


def test_rejects_invalid_host_for_field_endpoint():
    checker = _load_checker()

    with pytest.raises(AssertionError, match="valid DNS hostname or IPv4 address"):
        checker.require_network_host("nav host/invalid", "nav endpoint")


def test_rejects_loopback_ipv4_for_field_endpoint():
    checker = _load_checker()

    with pytest.raises(AssertionError, match="must not use a loopback address"):
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
