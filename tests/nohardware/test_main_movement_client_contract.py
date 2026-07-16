"""Regression tests for the assembled no-hardware Main→Nav TCP path."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "tests/nohardware/check_full_stack_tcp.py"
TCP_RUNNER = ROOT / "scripts/test-nohardware-tcp.sh"


def test_full_stack_checker_uses_the_running_main_api_for_nav_commands():
    source = CHECKER.read_text(encoding="utf-8")

    assert "/api/v1/robot-commands" in source
    assert "/api/v1/movement/commands/" in source
    assert "HttpMovementClient" not in source


def test_tcp_runner_does_not_export_movement_fallback_routes():
    source = TCP_RUNNER.read_text(encoding="utf-8")
    assert "LMS_MOVEMENT_FALLBACK_BASE_URLS" not in source
    assert "LMS_MOVEMENT_BASE_URL=" not in source


def test_tcp_runner_starts_the_unmodified_main_application():
    source = TCP_RUNNER.read_text(encoding="utf-8")
    checker = CHECKER.read_text(encoding="utf-8")

    assert "-m uvicorn app.main:app" in source
    assert "serve_main_fixture.py" not in source
    assert "/__nohardware/person-hazard/arm" not in checker
    assert "/__nohardware/assigned-inbound" not in checker
    assert "/__nohardware/evidence/" not in checker
