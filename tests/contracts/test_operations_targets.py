"""G003 production-bind target plus retained no-hardware harness contracts."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REAL_LAUNCHER = ROOT / "main-server" / "scripts" / "real.sh"
NOHARDWARE_RUNNER = ROOT / "scripts" / "test-nohardware-tcp.sh"
PROCESS_GROUPS = ROOT / "scripts" / "lib" / "nohardware-process-groups.sh"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_production_launcher_binds_only_the_canonical_site_interface() -> None:
    source = _source(REAL_LAUNCHER)
    host_assignment = next(
        line.strip()
        for line in source.splitlines()
        if line.startswith("HOST=")
    )
    required_markers = {
        "canonical hostname": "smartfactory-main.local",
        "canonical hosts file": "config/network/smartfactory-hosts",
        "hosts-file validator": "install-smartfactory-hosts.sh",
        "validation mode": "--check",
        "field subnet": "192.168.30.",
    }
    missing = [label for label, marker in required_markers.items() if marker not in source]

    assert not missing, (
        "G003 target gap: production launcher lacks canonical bind checks: "
        + ", ".join(missing)
    )
    assert "0.0.0.0" not in host_assignment
    assert "10." not in host_assignment
    assert "192.168.10." not in host_assignment
    assert '--host "$HOST"' in source


def test_nohardware_runner_is_loopback_ready_and_cleanup_safe() -> None:
    runner = _source(NOHARDWARE_RUNNER)
    process_groups = _source(PROCESS_GROUPS)
    uvicorn_hosts = re.findall(r"-m uvicorn .*? --host ([^ ]+)", runner)

    assert uvicorn_hosts
    assert set(uvicorn_hosts) == {"127.0.0.1"}
    assert 's.bind(("127.0.0.1", 0))' in runner
    assert "http://127.0.0.1:${NAV_PORT}" in runner
    assert "http://127.0.0.1:${AI_PORT}" in runner
    assert 'trap cleanup EXIT INT TERM' in runner
    assert runner.count("wait_http ") >= 3
    assert runner.count("nohardware_register_process_group") >= 3
    assert "nohardware_stop_all_process_groups" in runner
    assert "kill -TERM -- \"-${pid}\"" in process_groups
    assert "expected_start_time" in process_groups
    assert "current_start_time" in process_groups
    assert "pkill" not in runner + process_groups
    assert "killall" not in runner + process_groups
