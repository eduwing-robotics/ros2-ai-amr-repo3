"""Regression tests for the no-hardware Main Movement TCP client setup."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CHECKER = ROOT / "tests/nohardware/check_main_movement_tcp.py"
TCP_RUNNER = ROOT / "scripts/test-nohardware-tcp.sh"


def test_movement_tcp_checker_constructs_client_with_primary_route_only():
    tree = ast.parse(CHECKER.read_text(encoding="utf-8"))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "HttpMovementClient"
    ]

    assert len(calls) == 1
    assert {keyword.arg for keyword in calls[0].keywords} == {
        "base_urls",
        "fallback_url",
        "timeout_sec",
    }
    fallback_url = next(keyword.value for keyword in calls[0].keywords if keyword.arg == "fallback_url")
    assert ast.unparse(fallback_url) == "args.base.rstrip('/')"


def test_tcp_runner_does_not_export_movement_fallback_routes():
    assert "LMS_MOVEMENT_FALLBACK_BASE_URLS" not in TCP_RUNNER.read_text(encoding="utf-8")
