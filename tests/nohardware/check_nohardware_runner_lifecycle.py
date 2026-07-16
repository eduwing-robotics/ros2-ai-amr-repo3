#!/usr/bin/env python3
"""Adversarial lifecycle proof for the real no-hardware TCP runner."""
from __future__ import annotations

import argparse
import glob
import os
import queue
import re
import signal
import socket
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path


CONTAINER_PREFIX = "nohardware-fullstack-"
TEMP_GLOB = "/tmp/nohardware-tcp.*"
SECRET_KEYS = {
    "NAV_MAIN_HMAC_SECRET",
    "LMS_MOVEMENT_HMAC_SECRET",
    "MAIN_HMAC_SECRET",
    "VISION_GATEWAY_HMAC_SECRET",
    "LMS_VISION_HMAC_SECRET",
    "POSTGRES_PASSWORD",
}
URL_PORT = re.compile(r"http://127\.0\.0\.1:(\d+)")
NAMED_PORT = re.compile(r"\bport=([0-9]{2,5})\b")
READY = re.compile(
    r"^\[nohardware-tcp] READY (?P<service>postgres|nav|ai|main)"
    r"(?: pid=(?P<pid>[1-9][0-9]*))?"
)
SECRET_MARKER = "secret value appeared in fixture logs"
SERVICE_MARKERS = (
    "nav_app.app:app",
    "tests/nohardware/serve_ai_person_fixture.py",
    "uvicorn app.main:app --host 127.0.0.1",
)
ROOT = Path(__file__).resolve().parents[2]


@dataclass
class Capture:
    lines: list[str] = field(default_factory=list)
    ports: set[int] = field(default_factory=set)
    processes: dict[int, str] = field(default_factory=dict)
    secrets: set[str] = field(default_factory=set)
    containers: set[str] = field(default_factory=set)
    temp_dirs: set[str] = field(default_factory=set)


def _containers() -> dict[str, str]:
    result = subprocess.run(
        ["docker", "ps", "-a", "--format", "{{.ID}} {{.Names}}"],
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    rows: dict[str, str] = {}
    for line in result.stdout.splitlines():
        container_id, _, name = line.partition(" ")
        if name.startswith(CONTAINER_PREFIX):
            rows[container_id] = name
    return rows


def _container_facts(container_ids: set[str], capture: Capture) -> None:
    for container_id in container_ids:
        result = subprocess.run(
            ["docker", "inspect", container_id],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        )
        for match in re.finditer(r'POSTGRES_PASSWORD=([^"\\]+)', result.stdout):
            if match.group(1):
                capture.secrets.add(match.group(1))
        port = subprocess.run(
            ["docker", "port", container_id, "5432/tcp"],
            text=True,
            capture_output=True,
            check=False,
            timeout=10,
        ).stdout.strip()
        if port:
            try:
                capture.ports.add(int(port.rsplit(":", 1)[-1]))
            except ValueError:
                pass


def _process_rows() -> dict[int, tuple[int, int]]:
    result = subprocess.run(
        ["ps", "-eo", "pid=,ppid=,pgid="],
        text=True,
        capture_output=True,
        check=True,
        timeout=5,
    )
    rows: dict[int, tuple[int, int]] = {}
    for line in result.stdout.splitlines():
        try:
            pid, ppid, pgid = (int(part) for part in line.split())
        except ValueError:
            continue
        rows[pid] = (ppid, pgid)
    return rows


def _start_time(pid: int) -> str | None:
    try:
        fields = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8").rsplit(") ", 1)[1].split()
    except (OSError, IndexError):
        return None
    return fields[19] if len(fields) > 19 else None


def _process_command(pid: int) -> str:
    try:
        return Path(f"/proc/{pid}/cmdline").read_bytes().replace(b"\0", b" ").decode(
            errors="replace"
        )
    except OSError:
        return ""


def _matching_service_processes() -> dict[tuple[int, str], str]:
    matches: dict[tuple[int, str], str] = {}
    for pid in _process_rows():
        command = _process_command(pid)
        if not any(marker in command for marker in SERVICE_MARKERS):
            continue
        started = _start_time(pid)
        if started:
            matches[(pid, started)] = command
    return matches


def _capture_descendants(root_pid: int, capture: Capture) -> None:
    rows = _process_rows()
    descendants = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, (ppid, _pgid) in rows.items():
            if ppid in descendants and pid not in descendants:
                descendants.add(pid)
                changed = True
    for pid in descendants:
        start_time = _start_time(pid)
        if start_time:
            capture.processes[pid] = start_time
        try:
            raw = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
        except OSError:
            continue
        for entry in raw:
            key, sep, value = entry.partition(b"=")
            if sep and key.decode(errors="ignore") in SECRET_KEYS and value:
                capture.secrets.add(value.decode(errors="ignore"))


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _reader(process: subprocess.Popen[str], lines: list[str], events: queue.Queue[str]) -> None:
    assert process.stdout is not None
    for line in process.stdout:
        lines.append(line)
        sys.stdout.write(f"[nohardware-lifecycle] {line}")
        sys.stdout.flush()
        events.put(line)


def _wait_line(
    process: subprocess.Popen[str],
    events: queue.Queue[str],
    needle: str,
    timeout: float,
) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None and events.empty():
            break
        try:
            line = events.get(timeout=0.2)
        except queue.Empty:
            continue
        if needle in line:
            return line
    raise AssertionError(f"runner did not reach {needle!r}; rc={process.poll()}")


def _launch(runner: Path, env: dict[str, str]) -> tuple[subprocess.Popen[str], list[str], queue.Queue[str]]:
    process = subprocess.Popen(
        ["bash", str(runner)],
        cwd=runner.parent.parent,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
        bufsize=1,
    )
    lines: list[str] = []
    events: queue.Queue[str] = queue.Queue()
    threading.Thread(target=_reader, args=(process, lines, events), daemon=True).start()
    return process, lines, events


def _capture_live_state(process: subprocess.Popen[str], baseline_containers: set[str]) -> Capture:
    capture = Capture(temp_dirs=set(glob.glob(TEMP_GLOB)))
    _capture_descendants(process.pid, capture)
    current = set(_containers()) - baseline_containers
    capture.containers.update(current)
    _container_facts(current, capture)
    return capture


def _assert_clean(
    capture: Capture,
    output: str,
    baseline_containers: set[str],
    baseline_temp_dirs: set[str],
    baseline_processes: set[tuple[int, str]],
) -> None:
    capture.ports.update(int(match) for match in URL_PORT.findall(output))
    capture.ports.update(int(match) for match in NAMED_PORT.findall(output))
    for _ in range(40):
        live = [pid for pid, started in capture.processes.items() if _start_time(pid) == started]
        open_ports = [port for port in capture.ports if _port_open(port)]
        containers = set(_containers()) - baseline_containers
        temp_dirs = set(glob.glob(TEMP_GLOB)) - baseline_temp_dirs
        processes = set(_matching_service_processes()) - baseline_processes
        if not live and not open_ports and not containers and not temp_dirs and not processes:
            break
        time.sleep(0.1)
    assert not [pid for pid, started in capture.processes.items() if _start_time(pid) == started], capture.processes
    assert not [port for port in capture.ports if _port_open(port)], capture.ports
    assert not (set(_containers()) - baseline_containers), _containers()
    assert not (set(glob.glob(TEMP_GLOB)) - baseline_temp_dirs), glob.glob(TEMP_GLOB)
    assert not (set(_matching_service_processes()) - baseline_processes), _matching_service_processes()
    assert SECRET_MARKER not in output, "runner cleanup detected a secret-bearing fixture log"
    leaked = [secret for secret in capture.secrets if secret and secret in output]
    assert not leaked, "a generated credential appeared in runner output"


def _baselines() -> tuple[set[str], set[str], set[tuple[int, str]]]:
    return (
        set(_containers()),
        set(glob.glob(TEMP_GLOB)),
        set(_matching_service_processes()),
    )


def _assert_case_cleanup(
    *,
    capture: Capture,
    output: str,
    return_code: int,
    baseline_containers: set[str],
    baseline_temp_dirs: set[str],
    baseline_processes: set[tuple[int, str]],
) -> None:
    marker = f"[nohardware-tcp] CLEANUP PASSED exit_status={return_code}"
    assert marker in output, f"missing cleanup marker {marker!r}"
    assert "[nohardware-tcp] CLEANUP FAILED" not in output, output[-4000:]
    _assert_clean(
        capture,
        output,
        baseline_containers,
        baseline_temp_dirs,
        baseline_processes,
    )


def _signal_after_ready(
    runner: Path,
    base_env: dict[str, str],
    *,
    service: str,
    signal_number: int,
) -> None:
    baseline_containers, baseline_temp_dirs, baseline_processes = _baselines()
    process, lines, events = _launch(runner, base_env)
    try:
        ready_line = _wait_line(process, events, f"READY {service}", 90)
        assert READY.match(ready_line), ready_line
        capture = _capture_live_state(process, baseline_containers)
        assert capture.containers, f"{service}-ready run did not create disposable PostgreSQL"
        os.killpg(process.pid, signal_number)
        _wait_line(process, events, "CLEANUP PASSED", 30)
        process.wait(timeout=10)
    except BaseException:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGINT)
            process.wait(timeout=20)
        raise
    output = "".join(lines)
    assert process.returncode == 130, output[-4000:]
    _assert_case_cleanup(
        capture=capture,
        output=output,
        return_code=process.returncode,
        baseline_containers=baseline_containers,
        baseline_temp_dirs=baseline_temp_dirs,
        baseline_processes=baseline_processes,
    )


def _request_timeout_after_main_ready(runner: Path, base_env: dict[str, str]) -> None:
    baseline_containers, baseline_temp_dirs, baseline_processes = _baselines()
    process, lines, events = _launch(runner, base_env)
    _wait_line(process, events, "READY main", 120)
    capture = _capture_live_state(process, baseline_containers)
    assert capture.containers, "Main-ready timeout run did not create disposable PostgreSQL"
    ai_pid: int | None = None
    for line in lines:
        match = READY.match(line)
        if match and match.group("service") == "ai" and match.group("pid"):
            ai_pid = int(match.group("pid"))
            break
    assert ai_pid is not None, "Main became ready before the AI process identity was recorded"
    os.killpg(ai_pid, signal.SIGSTOP)
    try:
        _wait_line(process, events, "CLEANUP PASSED", 45)
        process.wait(timeout=10)
    except BaseException:
        try:
            os.killpg(ai_pid, signal.SIGCONT)
        except ProcessLookupError:
            pass
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGINT)
            process.wait(timeout=20)
        raise
    output = "".join(lines)
    _assert_case_cleanup(
        capture=capture,
        output=output,
        return_code=process.returncode,
        baseline_containers=baseline_containers,
        baseline_temp_dirs=baseline_temp_dirs,
        baseline_processes=baseline_processes,
    )
    assert process.returncode not in {0, 130}, output[-4000:]
    assert "timeouterror" in output.lower() or "timed out" in output.lower(), output[-4000:]


def _dependency_environment(dependency_root: Path | None) -> dict[str, str]:
    env = os.environ.copy()
    relative_paths = {
        "NAV_PY": Path("nav-server/.venv/bin/python"),
        "MAIN_PY": Path("main-server/.venv/bin/python"),
        "AI_PY": Path("ai-server/.venv/bin/python"),
    }
    paths: dict[str, Path] = {}
    unresolved: list[str] = []
    for name, relative_path in relative_paths.items():
        inherited = env.get(name, "").strip()
        if inherited:
            paths[name] = Path(os.path.abspath(os.path.expanduser(inherited)))
        elif dependency_root is not None:
            paths[name] = (dependency_root / relative_path).absolute()
        else:
            unresolved.append(name)

    if unresolved:
        joined = ", ".join(unresolved)
        raise SystemExit(
            "missing no-hardware lifecycle dependency paths: "
            f"{joined}; set them in the environment or pass --dependency-root"
        )

    missing = [
        f"{name}={paths[name]}"
        for name in ("NAV_PY", "MAIN_PY", "AI_PY")
        if not paths[name].is_file() or not os.access(paths[name], os.X_OK)
    ]
    inherited_frontend = env.get("FRONTEND_DIR", "").strip()
    if inherited_frontend:
        frontend_dir = Path(os.path.abspath(os.path.expanduser(inherited_frontend)))
    elif dependency_root is not None:
        frontend_dir = (dependency_root / "main-server/frontend/web").absolute()
    else:
        raise SystemExit(
            "missing no-hardware lifecycle dependency path: FRONTEND_DIR; "
            "set it in the environment or pass --dependency-root"
        )
    if not frontend_dir.is_dir():
        missing.append(f"FRONTEND_DIR={frontend_dir}")
    node_modules = frontend_dir / "node_modules"
    if not node_modules.is_dir():
        missing.append(f"FRONTEND_NODE_MODULES={node_modules}")
    if missing:
        raise SystemExit("missing no-hardware lifecycle dependencies: " + ", ".join(missing))

    for name, path in paths.items():
        print(f"[nohardware-lifecycle] dependency {name}={path}")
        env[name] = str(path)
    print(f"[nohardware-lifecycle] dependency FRONTEND_DIR={frontend_dir}")
    env["FRONTEND_DIR"] = str(frontend_dir)
    env["PYTHONUNBUFFERED"] = "1"
    return env


CASES = ("nav-ready-term", "ai-ready-term", "main-ready-sigint", "main-ai-request-timeout")


def _run_named_case(name: str, runner: Path, base_env: dict[str, str]) -> None:
    if name == "nav-ready-term":
        _signal_after_ready(runner, base_env, service="nav", signal_number=signal.SIGTERM)
    elif name == "ai-ready-term":
        _signal_after_ready(runner, base_env, service="ai", signal_number=signal.SIGTERM)
    elif name == "main-ready-sigint":
        _signal_after_ready(runner, base_env, service="main", signal_number=signal.SIGINT)
    elif name == "main-ai-request-timeout":
        _request_timeout_after_main_ready(runner, base_env)
    else:  # pragma: no cover - argparse owns the public values
        raise AssertionError(f"unknown lifecycle case: {name}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runner", type=Path, required=True)
    parser.add_argument(
        "--dependency-root",
        type=Path,
        help="fallback root for dependency paths not supplied in the environment",
    )
    parser.add_argument("--case", action="append", choices=CASES)
    args = parser.parse_args()
    runner = args.runner.resolve()
    if not runner.is_file():
        raise SystemExit(f"runner does not exist: {runner}")
    dependency_root = args.dependency_root.resolve() if args.dependency_root else None
    base_env = _dependency_environment(dependency_root)
    selected = args.case or list(CASES)
    for name in selected:
        _run_named_case(name, runner, base_env)
        print(f"[nohardware-lifecycle] PASSED {name}")
    print(f"[nohardware-lifecycle] PASSED cases={len(selected)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
