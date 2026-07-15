"""G003 production-bind target plus retained no-hardware harness contracts."""

from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
REAL_LAUNCHER = ROOT / "main-server" / "scripts" / "real.sh"
NOHARDWARE_RUNNER = ROOT / "scripts" / "test-nohardware-tcp.sh"
PROCESS_GROUPS = ROOT / "scripts" / "lib" / "nohardware-process-groups.sh"
MAIN_CONFIG = ROOT / "main-server" / "backend" / "app" / "core" / "config.py"
VISION_PROXY = ROOT / "main-server" / "backend" / "app" / "services" / "vision_proxy.py"
ENV_EXAMPLE = ROOT / "main-server" / ".env.example"
BOOTSTRAP = ROOT / "main-server" / "scripts" / "bootstrap.sh"


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
    assert re.search(
        r"pick_port\(\)\s*\{.*?\.bind\(\(\"127\.0\.0\.1\", 0\)\)",
        runner,
        re.DOTALL,
    )
    assert "http://127.0.0.1:${NAV_PORT}" in runner
    assert "http://127.0.0.1:${AI_PORT}" in runner
    assert "trap cleanup EXIT" in runner
    assert "trap 'exit 130' INT TERM" in runner
    assert runner.count("wait_http ") >= 3
    assert runner.count("nohardware_register_process_group") >= 3
    assert "nohardware_stop_all_process_groups" in runner
    assert "kill -TERM -- \"-${pid}\"" in process_groups
    assert "expected_start_time" in process_groups
    assert "current_start_time" in process_groups
    assert "pkill" not in runner + process_groups
    assert "killall" not in runner + process_groups


def test_production_service_identity_has_no_endpoint_fallback_mode() -> None:
    source = "\n".join(
        _source(path)
        for path in (REAL_LAUNCHER, MAIN_CONFIG, VISION_PROXY, ENV_EXAMPLE)
    )
    for obsolete in (
        "LMS_VISION_API_FALLBACK_BASE_URL",
        "LMS_VISION_STREAM_FALLBACK_BASE_URL",
        "vision_api_fallback_base_url",
        "vision_stream_fallback_base_url",
    ):
        assert obsolete not in source


def test_dev_launcher_owns_and_reaps_vite_and_api_children() -> None:
    source = _source(REAL_LAUNCHER)

    assert 'VITE_PID=""' in source
    assert 'API_PID=""' in source
    assert 'trap cleanup EXIT INT TERM' in source
    assert source.count('for pid in "$API_PID" "$VITE_PID"; do') >= 2
    assert 'kill -TERM "$pid"' in source
    assert 'wait "$pid"' in source
    assert "exec ./node_modules/.bin/vite" in source
    assert 'VITE_API_PROXY_TARGET="http://smartfactory-main.local:$PORT"' in source
    assert 'http://127.0.0.1:${PORT}' not in source
    assert re.search(
        r'if \[\[ "\$DEV" -eq 1 \]\]; then'
        r'.*VITE_PID=\$!'
        r'.*API_PID=\$!'
        r'.*wait "\$API_PID"'
        r'.*else'
        r'.*exec \./\.venv/bin/python -m uvicorn'
        r'.*fi',
        source,
        re.DOTALL,
    )


def test_bootstrap_restores_db_only_for_explicit_local_snapshot_request() -> None:
    source = _source(BOOTSTRAP)
    restore_command = '"$ROOT/scripts/restore_current_db.sh"'
    restore_index = source.index(restore_command)

    local_only_guard = source.rfind(
        'if [[ "$LOCAL_DEV" -ne 1 ]]; then', 0, restore_index
    )
    explicit_restore_guard = source.rfind(
        'if [[ "$FORCE_DB_RESTORE" -eq 1 ]]; then', 0, restore_index
    )
    snapshot_guard = source.rfind(
        'if [[ ! -f "$DB_SNAPSHOT" ]]; then', 0, restore_index
    )

    assert source.count(restore_command) == 1
    assert 0 <= local_only_guard < explicit_restore_guard < snapshot_guard < restore_index
    assert '[[ "$FORCE" -eq 1 || "$FORCE_DB_RESTORE" -eq 1 ]]' not in source
    assert 'stamp_matches "$DB_SNAPSHOT_STAMP" "$DB_SNAPSHOT"' not in source
