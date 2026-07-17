from __future__ import annotations

import importlib.util
import json
import os
import signal
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "sf_stack.sh"
MANIFEST = ROOT / "config" / "runtime_profiles" / "stack" / "manifest.json"


def _load_stack_module():
    spec = importlib.util.spec_from_file_location("sf_stack_under_test", ROOT / "scripts" / "sf_stack.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fake_runner(path: Path, *, fail: bool = False) -> Path:
    path.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        "if [[ -n \"${SF_STACK_TEST_ENV_LOG:-}\" ]]; then\n"
        "  printf '%s|%s|%s|%s\\n' \"$(basename \"$0\")\" \"${SF_NAV_ALLOW_SYNTHETIC_HIL:-}\" "
        "\"${LMS_NONPHYSICAL_TASK_ADMISSION_ENABLED:-}\" \"${SF_NAV_READINESS_MODE:-}\" "
        ">> \"$SF_STACK_TEST_ENV_LOG\"\n"
        "fi\n"
        "case \" ${*:-} \" in\n"
        "  *\" --check \"*|*\" check \"*|*\" smoke \"*) exit 0 ;;\n"
        "esac\n"
        + ("exit 9\n" if fail else "")
        + "trap 'exit 0' INT TERM\n"
        "while :; do sleep 0.05; done\n",
        encoding="utf-8",
    )
    path.chmod(0o755)
    return path


def _stack_fixture(
    tmp_path: Path,
    *,
    ports: list[int] | None = None,
    fail_main: bool = False,
    local_ip: str = "127.0.0.1",
    execution_class: str = "live",
) -> tuple[dict[str, str], Path]:
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    profile = {
        "schema_version": 1,
        "profile_id": "test-stack",
        "execution_class": execution_class,
        "site": {
            "hostname": "localhost",
            "allowed_local_ips": [local_ip],
        },
        "ports": ports or [],
        "components": {
            "bridge": {"enabled": True, "runner": "unused"},
            "nav": {
                "enabled": True,
                "profile": "tb1-synthetic-hil" if execution_class == "synthetic_hil" else "tb1-live",
                "readiness_mode": "http",
            },
            "main": {
                "enabled": True,
                "site_profile": "integration",
                "dev": True,
                "env": {
                    "LMS_NONPHYSICAL_TASK_ADMISSION_ENABLED": (
                        "true" if execution_class == "synthetic_hil" else "false"
                    )
                },
            },
        },
        "health": {},
        "operator_urls": ["http://localhost:5173/operate/control"],
    }
    (profile_dir / "test-stack.json").write_text(json.dumps(profile), encoding="utf-8")
    manifest = {
        "schema_version": 1,
        "default_profile": "test-stack",
        "host_defaults": {local_ip: "test-stack"},
        "profiles": {"test-stack": "test-stack.json"},
    }
    manifest_path = profile_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    bridge = _fake_runner(tmp_path / "bridge.sh")
    nav = _fake_runner(tmp_path / "nav.sh")
    main = _fake_runner(tmp_path / "main.sh", fail=fail_main)
    state_root = tmp_path / "state"
    env = {
        **os.environ,
        "SF_STACK_MANIFEST": str(manifest_path),
        "SF_STACK_STATE_DIR": str(state_root),
        "SF_STACK_BRIDGE_RUNNER": str(bridge),
        "SF_STACK_NAV_RUNNER": str(nav),
        "SF_STACK_MAIN_RUNNER": str(main),
        "SF_STACK_LOCAL_IPS": local_ip,
        "SF_STACK_READINESS_MODE": "process-only",
        "SF_STACK_START_SETTLE_SEC": "0.05",
    }
    return env, state_root


def _latest_state(state_root: Path) -> tuple[Path, dict]:
    run_dir = Path((state_root / "test-stack" / "latest").read_text(encoding="utf-8").strip())
    state_path = run_dir / "runtime-state.json"
    return state_path, json.loads(state_path.read_text(encoding="utf-8"))


def _wait_for_running(state_root: Path) -> tuple[Path, dict]:
    for _ in range(120):
        latest = state_root / "test-stack" / "latest"
        if latest.is_file():
            state_path, state = _latest_state(state_root)
            if state.get("status") == "running":
                return state_path, state
        time.sleep(0.05)
    raise AssertionError("stack did not become running")


def test_http_readiness_probe_does_not_force_json_for_html_frontend() -> None:
    class HtmlHandler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.headers.get("Accept") == "application/json":
                self.send_response(406)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<!doctype html><title>ready</title>")

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), HtmlHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        stack = _load_stack_module()
        assert stack.http_ready(f"http://127.0.0.1:{server.server_port}/") is True
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_owned_stack_stops_in_reverse_without_touching_unrelated_process(tmp_path: Path) -> None:
    env, state_root = _stack_fixture(tmp_path)
    sentinel = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        up = subprocess.run(
            [str(SCRIPT), "--profile", "test-stack", "up"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        assert "profile=test-stack" in up.stdout
        state_path, state = _latest_state(state_root)
        assert state["status"] == "running"
        assert list(state["components"]) == ["bridge", "nav", "main"]
        for component in state["components"].values():
            os.kill(component["pid"], 0)

        repeated = subprocess.run(
            [str(SCRIPT), "--profile", "test-stack", "up"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
        )
        assert repeated.returncode != 0
        assert "active stack" in repeated.stderr

        down = subprocess.run(
            [str(SCRIPT), "--profile", "test-stack", "down"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        assert "stopped profile=test-stack" in down.stdout
        assert sentinel.poll() is None
        stopped = json.loads(state_path.read_text(encoding="utf-8"))
        assert stopped["status"] == "stopped"
        assert stopped["stop_order"] == ["main", "nav", "bridge"]

        again = subprocess.run(
            [str(SCRIPT), "--profile", "test-stack", "down"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        assert "already stopped" in again.stdout
    finally:
        if sentinel.poll() is None:
            os.killpg(sentinel.pid, signal.SIGTERM)
            sentinel.wait(timeout=5)


def test_restart_is_refused_while_any_owned_component_is_still_alive(tmp_path: Path) -> None:
    env, state_root = _stack_fixture(tmp_path)
    subprocess.run(
        [str(SCRIPT), "--profile", "test-stack", "up"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    state_path, state = _latest_state(state_root)
    main_pid = state["components"]["main"]["pid"]
    os.killpg(main_pid, signal.SIGTERM)
    for _ in range(100):
        try:
            os.kill(main_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.02)

    try:
        repeated = subprocess.run(
            [str(SCRIPT), "--profile", "test-stack", "up"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
        )
        assert repeated.returncode != 0
        assert "active stack" in repeated.stderr
    finally:
        subprocess.run(
            [str(SCRIPT), "--profile", "test-stack", "down"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
            check=True,
        )
        assert json.loads(state_path.read_text(encoding="utf-8"))["status"] == "stopped"


def test_foreground_ctrl_c_stops_every_owned_component(tmp_path: Path) -> None:
    env, state_root = _stack_fixture(tmp_path)
    process = subprocess.Popen(
        [str(SCRIPT), "--profile", "test-stack", "foreground"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    try:
        state_path, state = _wait_for_running(state_root)
        pids = [component["pid"] for component in state["components"].values()]
        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=15)
        assert process.returncode == 130, (stdout, stderr)
        assert json.loads(state_path.read_text(encoding="utf-8"))["status"] == "stopped"
        for pid in pids:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def test_synthetic_profile_opens_only_the_two_explicit_admission_gates(tmp_path: Path) -> None:
    env, _ = _stack_fixture(tmp_path, execution_class="synthetic_hil")
    env_log = tmp_path / "component-env.log"
    env["SF_STACK_TEST_ENV_LOG"] = str(env_log)
    env["SF_NAV_ALLOW_SYNTHETIC_HIL"] = "stale-parent-value"
    env["LMS_NONPHYSICAL_TASK_ADMISSION_ENABLED"] = "stale-parent-value"

    subprocess.run(
        [str(SCRIPT), "--profile", "test-stack", "up"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    observed = {line.split("|", 1)[0]: line for line in env_log.read_text(encoding="utf-8").splitlines()}
    assert observed["bridge.sh"] == "bridge.sh|||"
    assert observed["nav.sh"] == "nav.sh|1||http"
    assert observed["main.sh"] == "main.sh||true|"

    env_log.write_text("", encoding="utf-8")
    subprocess.run(
        [str(SCRIPT), "--profile", "test-stack", "smoke"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )
    assert env_log.read_text(encoding="utf-8").splitlines() == ["nav.sh|1||http"]

    subprocess.run(
        [str(SCRIPT), "--profile", "test-stack", "down"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=True,
    )


def test_failed_late_component_rolls_back_previously_started_components(tmp_path: Path) -> None:
    env, state_root = _stack_fixture(tmp_path, fail_main=True)
    result = subprocess.run(
        [str(SCRIPT), "--profile", "test-stack", "up"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    state_path, state = _latest_state(state_root)
    assert state["status"] == "failed"
    assert state["stop_order"] == ["nav", "bridge"]
    for component in state["components"].values():
        with pytest.raises(ProcessLookupError):
            os.kill(component["pid"], 0)
    assert "startup rollback" in state["message"]


def test_occupied_port_is_reported_but_listener_is_not_killed(tmp_path: Path) -> None:
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    env, state_root = _stack_fixture(tmp_path, ports=[port])
    try:
        result = subprocess.run(
            [str(SCRIPT), "--profile", "test-stack", "up"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
        )
        assert result.returncode != 0
        assert f"port {port}" in result.stderr
        assert listener.fileno() >= 0
        assert not (state_root / "test-stack" / "latest").exists()
    finally:
        listener.close()


def test_profile_refuses_the_wrong_host(tmp_path: Path) -> None:
    env, _ = _stack_fixture(tmp_path, local_ip="192.0.2.10")
    env["SF_STACK_LOCAL_IPS"] = "192.0.2.11"
    result = subprocess.run(
        [str(SCRIPT), "--profile", "test-stack", "check"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    assert result.returncode != 0
    assert "not allowed on this host" in result.stderr


def test_repository_profiles_assign_one_safe_default_per_field_host() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["host_defaults"] == {
        "192.168.30.5": "tb1-local-e2e",
        "192.168.30.9": "main-field",
        "192.168.30.12": "nav-field-tb1",
    }

    profile_dir = MANIFEST.parent
    profiles = {
        name: json.loads((profile_dir / relative).read_text(encoding="utf-8"))
        for name, relative in manifest["profiles"].items()
    }
    assert profiles["tb1-local-e2e"]["components"]["main"]["enabled"] is True
    assert profiles["tb1-local-e2e"]["components"]["nav"]["profile"] == "tb1-live"
    assert profiles["tb1-local-e2e"]["components"]["nav"]["readiness_mode"] == "http"
    assert profiles["tb1-local-e2e"]["components"]["nav"]["readiness_timeout_sec"] == 60
    assert profiles["tb1-local-e2e"]["health"]["main"] == [
        "http://smartfactory-integration.local:8088/health",
        "http://smartfactory-integration.local:5173/",
    ]
    assert (
        profiles["tb1-local-e2e"]["components"]["main"]["env"]["LMS_NONPHYSICAL_TASK_ADMISSION_ENABLED"]
        == "false"
    )
    assert profiles["main-field"]["components"]["nav"]["enabled"] is False
    assert profiles["main-field"]["health"]["main"] == [
        "http://smartfactory-main.local:8088/health",
        "http://smartfactory-main.local:5173/",
    ]
    assert (
        profiles["main-field"]["components"]["main"]["env"]["LMS_NONPHYSICAL_TASK_ADMISSION_ENABLED"]
        == "false"
    )
    assert profiles["nav-field-tb1"]["components"]["main"]["enabled"] is False
    assert profiles["tb1-synthetic-e2e"]["execution_class"] == "synthetic_hil"
    assert profiles["tb1-synthetic-e2e"]["components"]["nav"]["profile"] == "tb1-synthetic-hil"
    assert (
        profiles["tb1-synthetic-e2e"]["components"]["main"]["env"]["LMS_NONPHYSICAL_TASK_ADMISSION_ENABLED"]
        == "true"
    )
    assert profiles["nav-field-tb2"]["components"]["nav"]["profile"] == "tb2-live"
    assert profiles["nav-field-all"]["components"]["nav"]["profile"] == "all-live"
