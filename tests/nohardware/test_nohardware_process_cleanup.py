"""Regression coverage for no-hardware fixture cleanup isolation."""

from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PROCESS_HELPER = ROOT / 'scripts/lib/nohardware-process-groups.sh'
TCP_RUNNER = ROOT / 'scripts/test-nohardware-tcp.sh'


def test_cleanup_stops_only_registered_process_groups(tmp_path):
    """Cleanup terminates owned groups without touching an outside sentinel."""
    harness = tmp_path / 'cleanup-harness.sh'
    harness.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
source {str(PROCESS_HELPER)!r}

setsid bash -c 'trap "exit 0" TERM; sleep 60 & wait' &
sentinel_pid=$!
setsid bash -c 'trap "exit 0" TERM; sleep 60 & wait' &
owned_pid=$!

cleanup_test() {{
  kill -TERM -- "-${{sentinel_pid}}" 2>/dev/null || true
  wait "${{sentinel_pid}}" 2>/dev/null || true
  nohardware_stop_all_process_groups
}}
trap cleanup_test EXIT

nohardware_register_process_group "${{owned_pid}}"
nohardware_stop_all_process_groups
kill -0 "${{sentinel_pid}}"
if kill -0 "${{owned_pid}}" 2>/dev/null; then
  echo "owned process survived cleanup" >&2
  exit 1
fi

# Cleanup is idempotent and an unregistered Nav/API-like sentinel still lives.
nohardware_stop_all_process_groups
kill -0 "${{sentinel_pid}}"
echo "sentinel-survived"
""",
        encoding='utf-8',
    )
    harness.chmod(0o755)

    result = subprocess.run(
        ['bash', str(harness)],
        text=True,
        capture_output=True,
        check=False,
        timeout=10,
    )

    assert result.returncode == 0, result.stderr
    assert 'sentinel-survived' in result.stdout


def test_nohardware_cleanup_has_no_name_based_process_kills():
    """Cleanup never matches unrelated processes by executable name."""
    cleanup_sources = (
        PROCESS_HELPER.read_text(encoding='utf-8')
        + TCP_RUNNER.read_text(encoding='utf-8')
    )

    assert 'pkill' not in cleanup_sources
    assert 'killall' not in cleanup_sources
