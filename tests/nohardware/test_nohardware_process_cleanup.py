"""Regression coverage for no-hardware fixture cleanup isolation."""

from __future__ import annotations

import os
import signal
import subprocess
import time
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


def test_cleanup_force_kills_an_owned_group_that_ignores_term(tmp_path):
    harness = tmp_path / "stubborn-cleanup.sh"
    harness.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
source {str(PROCESS_HELPER)!r}
setsid bash -c 'trap "" TERM; sleep 60 & wait' &
owned_pid=$!
nohardware_register_process_group "${{owned_pid}}"
nohardware_stop_all_process_groups
if kill -0 "${{owned_pid}}" 2>/dev/null; then
  echo "stubborn process survived cleanup" >&2
  exit 1
fi
echo "stubborn-stopped"
""",
        encoding="utf-8",
    )
    harness.chmod(0o755)

    result = subprocess.run(
        ["bash", str(harness)],
        text=True,
        capture_output=True,
        check=False,
        timeout=8,
    )

    assert result.returncode == 0, result.stderr
    assert "stubborn-stopped" in result.stdout


def test_cleanup_kills_term_ignoring_descendant_after_leader_exits(tmp_path):
    child_pid_file = tmp_path / "stubborn-child.pid"
    child = tmp_path / "stubborn-child.sh"
    child.write_text(
        """#!/usr/bin/env bash
trap '' TERM
printf '%s\n' "$BASHPID" > "$1"
while true; do sleep 1; done
""",
        encoding="utf-8",
    )
    child.chmod(0o755)
    harness = tmp_path / "descendant-cleanup.sh"
    harness.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
source {str(PROCESS_HELPER)!r}
setsid bash -c 'trap "exit 0" TERM; "$1" "$2" & wait' leader {str(child)!r} {str(child_pid_file)!r} &
owned_pid=$!
nohardware_register_process_group "${{owned_pid}}"
for _ in {{1..100}}; do
  [[ -s {str(child_pid_file)!r} ]] && break
  sleep 0.01
done
child_pid="$(cat {str(child_pid_file)!r})"
nohardware_stop_all_process_groups
for _ in {{1..100}}; do
  [[ ! -e "/proc/${{child_pid}}" ]] && break
  sleep 0.02
done
if [[ -e "/proc/${{child_pid}}" ]]; then
  echo "TERM-ignoring descendant survived cleanup" >&2
  exit 1
fi
echo "descendant-stopped"
""",
        encoding="utf-8",
    )
    harness.chmod(0o755)

    result = subprocess.run(
        ["bash", str(harness)],
        text=True,
        capture_output=True,
        check=False,
        timeout=8,
    )

    assert result.returncode == 0, result.stderr
    assert "descendant-stopped" in result.stdout


def test_cleanup_reaps_group_when_registered_leader_died_before_cleanup(tmp_path):
    child_pid_file = tmp_path / "orphan-child.pid"
    release_file = tmp_path / "release-leader"
    child = tmp_path / "orphan-child.sh"
    child.write_text(
        """#!/usr/bin/env bash
trap '' TERM
printf '%s\n' "$BASHPID" > "$1"
while true; do sleep 1; done
""",
        encoding="utf-8",
    )
    child.chmod(0o755)
    leader = tmp_path / "short-lived-leader.sh"
    leader.write_text(
        """#!/usr/bin/env bash
"$1" "$2" &
while [[ ! -e "$3" ]]; do sleep 0.01; done
exit 0
""",
        encoding="utf-8",
    )
    leader.chmod(0o755)
    harness = tmp_path / "orphan-cleanup.sh"
    harness.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
source {str(PROCESS_HELPER)!r}
setsid {str(leader)!r} {str(child)!r} {str(child_pid_file)!r} {str(release_file)!r} &
owned_pid=$!
nohardware_register_process_group "${{owned_pid}}"
for _ in {{1..100}}; do
  [[ -s {str(child_pid_file)!r} ]] && break
  sleep 0.01
done
child_pid="$(cat {str(child_pid_file)!r})"
touch {str(release_file)!r}
wait "${{owned_pid}}"
[[ -e "/proc/${{child_pid}}" ]]
nohardware_stop_all_process_groups
for _ in {{1..100}}; do
  [[ ! -e "/proc/${{child_pid}}" ]] && break
  sleep 0.02
done
if [[ -e "/proc/${{child_pid}}" ]]; then
  echo "orphaned descendant survived cleanup" >&2
  exit 1
fi
echo "orphaned-descendant-stopped"
""",
        encoding="utf-8",
    )
    harness.chmod(0o755)

    result = subprocess.run(
        ["bash", str(harness)],
        text=True,
        capture_output=True,
        check=False,
        timeout=8,
    )

    assert result.returncode == 0, result.stderr
    assert "orphaned-descendant-stopped" in result.stdout


def test_exit_failure_reaps_the_registered_group(tmp_path):
    child_pid_file = tmp_path / "child.pid"
    harness = tmp_path / "failure-cleanup.sh"
    harness.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
source {str(PROCESS_HELPER)!r}
cleanup() {{ nohardware_stop_all_process_groups; }}
trap cleanup EXIT
setsid bash -c 'trap "exit 0" TERM; sleep 60 & wait' &
owned_pid=$!
nohardware_register_process_group "${{owned_pid}}"
printf '%s\n' "${{owned_pid}}" > {str(child_pid_file)!r}
exit 23
""",
        encoding="utf-8",
    )
    harness.chmod(0o755)

    result = subprocess.run(
        ["bash", str(harness)],
        text=True,
        capture_output=True,
        check=False,
        timeout=8,
    )
    child_pid = int(child_pid_file.read_text(encoding="utf-8"))

    assert result.returncode == 23
    assert not Path(f"/proc/{child_pid}").exists()


def test_interrupt_reaps_the_registered_group(tmp_path):
    child_pid_file = tmp_path / "interrupt-child.pid"
    harness = tmp_path / "interrupt-cleanup.sh"
    harness.write_text(
        f"""#!/usr/bin/env bash
set -euo pipefail
source {str(PROCESS_HELPER)!r}
cleanup() {{
  trap - EXIT INT TERM
  nohardware_stop_all_process_groups
  exit 130
}}
trap cleanup EXIT INT TERM
setsid bash -c 'trap "exit 0" TERM; sleep 60 & wait' &
owned_pid=$!
nohardware_register_process_group "${{owned_pid}}"
printf '%s\n' "${{owned_pid}}" > {str(child_pid_file)!r}
printf 'ready\n'
while true; do sleep 1; done
""",
        encoding="utf-8",
    )
    harness.chmod(0o755)

    process = subprocess.Popen(
        ["bash", str(harness)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        start_new_session=True,
    )
    assert process.stdout is not None
    assert process.stdout.readline().strip() == "ready"
    child_pid = int(child_pid_file.read_text(encoding="utf-8"))
    process.send_signal(signal.SIGINT)
    process.wait(timeout=8)

    deadline = time.monotonic() + 2
    while Path(f"/proc/{child_pid}").exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    if process.poll() is None:
        os.killpg(process.pid, signal.SIGKILL)
    assert process.returncode == 130
    assert not Path(f"/proc/{child_pid}").exists()
