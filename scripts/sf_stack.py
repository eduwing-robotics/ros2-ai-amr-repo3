#!/usr/bin/env python3
"""Profile-driven Main/Nav process bundle for field and integration hosts."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import time
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "config" / "runtime_profiles" / "stack" / "manifest.json"
DEFAULT_STATE_ROOT = Path(os.getenv("XDG_RUNTIME_DIR", "/tmp")) / "smartfactory" / "stack"
COMPONENT_ORDER = ("bridge", "nav", "main")
STOP_ORDER = tuple(reversed(COMPONENT_ORDER))
OWNED_POPEN: dict[int, subprocess.Popen[bytes]] = {}


class StackError(RuntimeError):
    pass


class TerminationRequested(BaseException):
    def __init__(self, signum: int):
        self.signum = signum


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_write(path: Path, payload: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.{secrets.token_hex(4)}.tmp")
    temporary.write_text(payload, encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write(path, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")


def load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StackError(f"invalid JSON: {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise StackError(f"JSON root must be an object: {path}")
    return payload


def manifest_path() -> Path:
    return Path(os.getenv("SF_STACK_MANIFEST", str(DEFAULT_MANIFEST))).resolve()


def state_root() -> Path:
    return Path(os.getenv("SF_STACK_STATE_DIR", str(DEFAULT_STATE_ROOT))).resolve()


def load_manifest() -> tuple[Path, dict[str, Any]]:
    path = manifest_path()
    manifest = load_json(path)
    if manifest.get("schema_version") != 1:
        raise StackError("stack manifest schema_version must be 1")
    profiles = manifest.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise StackError("stack manifest must define profiles")
    return path, manifest


def local_ipv4_addresses() -> list[str]:
    configured = os.getenv("SF_STACK_LOCAL_IPS", "").strip()
    if configured:
        return sorted({value.strip() for value in configured.split(",") if value.strip()})
    try:
        result = subprocess.run(
            ["ip", "-o", "-4", "addr", "show"],
            text=True,
            capture_output=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise StackError("unable to inspect local IPv4 addresses") from exc
    addresses = {
        field.split("/", 1)[0]
        for line in result.stdout.splitlines()
        for field in line.split()
        if "/" in field and field[0].isdigit()
    }
    return sorted(addresses)


def selected_profile_name(requested: str | None, manifest: dict[str, Any], local_ips: list[str]) -> str:
    if requested:
        return requested
    defaults = manifest.get("host_defaults") or {}
    selected = {defaults[ip] for ip in local_ips if ip in defaults}
    if len(selected) != 1:
        observed = ",".join(local_ips) or "<none>"
        raise StackError(f"no unambiguous default stack profile for local IPs: {observed}; use --profile")
    return selected.pop()


def load_profile(requested: str | None) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    path, manifest = load_manifest()
    local_ips = local_ipv4_addresses()
    profile_name = selected_profile_name(requested, manifest, local_ips)
    relative = (manifest.get("profiles") or {}).get(profile_name)
    if not isinstance(relative, str) or not relative:
        raise StackError(f"unknown stack profile: {profile_name}")
    profile_path = (path.parent / relative).resolve()
    if path.parent not in profile_path.parents:
        raise StackError(f"profile path escapes manifest directory: {relative}")
    profile = load_json(profile_path)
    validate_profile(profile_name, profile)
    profile["_profile_path"] = str(profile_path)
    return profile, manifest, local_ips


def validate_profile(name: str, profile: dict[str, Any]) -> None:
    if profile.get("schema_version") != 1:
        raise StackError(f"profile={name} schema_version must be 1")
    if profile.get("profile_id") != name:
        raise StackError(f"profile identity mismatch: manifest={name} file={profile.get('profile_id')}")
    execution_class = profile.get("execution_class")
    if execution_class not in {"live", "synthetic_hil"}:
        raise StackError(f"profile={name} execution_class must be live or synthetic_hil")
    site = profile.get("site")
    if not isinstance(site, dict) or not isinstance(site.get("hostname"), str):
        raise StackError(f"profile={name} must define site.hostname")
    allowed = site.get("allowed_local_ips")
    if not isinstance(allowed, list) or not allowed or not all(isinstance(value, str) for value in allowed):
        raise StackError(f"profile={name} must define site.allowed_local_ips")
    components = profile.get("components")
    if not isinstance(components, dict) or not any(
        isinstance(components.get(component), dict) and components[component].get("enabled") is True
        for component in COMPONENT_ORDER
    ):
        raise StackError(f"profile={name} must enable at least one component")
    unknown = set(components) - set(COMPONENT_ORDER)
    if unknown:
        raise StackError(f"profile={name} has unknown components: {', '.join(sorted(unknown))}")
    ports = profile.get("ports", [])
    if not isinstance(ports, list) or any(not isinstance(port, int) or not 1 <= port <= 65535 for port in ports):
        raise StackError(f"profile={name} ports must be TCP port integers")
    if len(set(ports)) != len(ports):
        raise StackError(f"profile={name} contains duplicate ports")
    main = components.get("main") or {}
    if main.get("enabled"):
        if main.get("site_profile") not in {"field", "integration"}:
            raise StackError(f"profile={name} has unsupported Main site profile")
        env = main.get("env", {})
        if not isinstance(env, dict) or any(
            not isinstance(key, str)
            or not isinstance(value, str)
            or not key.startswith(("LMS_", "SF_MAIN_"))
            or "SECRET" in key
            or "PASSWORD" in key
            for key, value in env.items()
        ):
            raise StackError(f"profile={name} Main env may contain only non-secret LMS_/SF_MAIN_ strings")
        expected_nonphysical = "true" if execution_class == "synthetic_hil" else "false"
        if env.get("LMS_NONPHYSICAL_TASK_ADMISSION_ENABLED") != expected_nonphysical:
            raise StackError(
                f"profile={name} must set LMS_NONPHYSICAL_TASK_ADMISSION_ENABLED={expected_nonphysical}"
            )
    if execution_class == "synthetic_hil":
        nav = components.get("nav") or {}
        main_env = main.get("env") or {}
        if nav.get("enabled") is not True or nav.get("profile") != "tb1-synthetic-hil":
            raise StackError(f"profile={name} synthetic_hil must select the tb1-synthetic-hil Nav profile")
        if main.get("enabled") is not True or main_env.get("LMS_NONPHYSICAL_TASK_ADMISSION_ENABLED") != "true":
            raise StackError(f"profile={name} synthetic_hil must explicitly admit nonphysical Main tasks")


def validate_host(profile: dict[str, Any], local_ips: list[str]) -> None:
    site = profile["site"]
    allowed = set(site["allowed_local_ips"])
    local = set(local_ips)
    if not allowed.intersection(local):
        raise StackError(
            f"profile={profile['profile_id']} is not allowed on this host; "
            f"local={','.join(sorted(local)) or '<none>'} allowed={','.join(sorted(allowed))}"
        )
    hostname = site["hostname"]
    try:
        resolved = {
            item[4][0]
            for item in socket.getaddrinfo(hostname, None, family=socket.AF_INET, type=socket.SOCK_STREAM)
        }
    except socket.gaierror as exc:
        raise StackError(f"site hostname does not resolve: {hostname}") from exc
    if not resolved or not resolved.issubset(allowed):
        raise StackError(
            f"site hostname mismatch: {hostname} resolves to {','.join(sorted(resolved))}, "
            f"expected one of {','.join(sorted(allowed))}"
        )


def listener_for_port(port: int) -> str | None:
    if shutil.which("ss"):
        result = subprocess.run(
            ["ss", "-H", "-ltnp", f"sport = :{port}"],
            text=True,
            capture_output=True,
            check=False,
        )
        line = next((line.strip() for line in result.stdout.splitlines() if line.strip()), "")
        if line:
            return line
    for host in ("127.0.0.1", "0.0.0.0"):
        probe = socket.socket()
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            probe.bind((host, port))
        except OSError as exc:
            return str(exc)
        finally:
            probe.close()
    return None


def validate_ports(profile: dict[str, Any]) -> None:
    for port in profile.get("ports", []):
        listener = listener_for_port(port)
        if listener:
            raise StackError(f"port {port} is already listening; refusing to stop or replace it: {listener}")


def process_start_ticks(pid: int) -> str | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    fields = raw.rsplit(") ", 1)
    if len(fields) != 2:
        return None
    values = fields[1].split()
    return values[19] if len(values) > 19 else None


def process_state(pid: int) -> str | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")
    except OSError:
        return None
    fields = raw.rsplit(") ", 1)
    return fields[1].split()[0] if len(fields) == 2 and fields[1].split() else None


def boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"


def process_has_token(pid: int, token: str) -> bool:
    try:
        entries = Path(f"/proc/{pid}/environ").read_bytes().split(b"\0")
    except OSError:
        return False
    expected = f"SF_STACK_OWNERSHIP_TOKEN={token}".encode()
    return expected in entries


def component_alive(component: dict[str, Any], token: str, expected_boot_id: str) -> bool:
    pid = component.get("pid")
    pgid = component.get("process_group")
    if not isinstance(pid, int) or not isinstance(pgid, int):
        return False
    if expected_boot_id != boot_id() or process_state(pid) in {None, "Z"}:
        return False
    if process_start_ticks(pid) != str(component.get("start_ticks")):
        return False
    try:
        observed_pgid = os.getpgid(pid)
    except ProcessLookupError:
        return False
    return observed_pgid == pgid == pid and process_has_token(pid, token)


def latest_run_dir(profile_id: str) -> Path | None:
    latest = state_root() / profile_id / "latest"
    if not latest.is_file():
        return None
    try:
        run_dir = Path(latest.read_text(encoding="utf-8").strip()).resolve()
    except OSError:
        return None
    expected_root = (state_root() / profile_id).resolve()
    if expected_root not in run_dir.parents:
        raise StackError(f"invalid latest run path for profile={profile_id}")
    return run_dir


def state_observed_running(state: dict[str, Any]) -> bool:
    token = str(state.get("ownership_token") or "")
    expected_boot_id = str(state.get("boot_id") or "")
    components = state.get("components") or {}
    return bool(components) and all(
        component_alive(component, token, expected_boot_id) for component in components.values()
    )


def state_has_live_component(state: dict[str, Any]) -> bool:
    token = str(state.get("ownership_token") or "")
    expected_boot_id = str(state.get("boot_id") or "")
    components = state.get("components") or {}
    return any(component_alive(component, token, expected_boot_id) for component in components.values())


def refuse_active_stack() -> None:
    root = state_root()
    if not root.is_dir():
        return
    for latest in root.glob("*/latest"):
        try:
            run_dir = Path(latest.read_text(encoding="utf-8").strip())
            state = load_json(run_dir / "runtime-state.json")
        except (OSError, StackError):
            continue
        if state.get("status") in {"starting", "running", "degraded"} and state_has_live_component(state):
            raise StackError(
                f"active stack profile={state.get('profile_id')} run_id={state.get('run_id')} already owns local components"
            )


def runner_path(component: str, config: dict[str, Any]) -> Path:
    override = os.getenv(f"SF_STACK_{component.upper()}_RUNNER", "").strip()
    if override:
        path = Path(override)
    elif component == "bridge":
        path = ROOT / str(config.get("runner") or "")
    elif component == "nav":
        path = ROOT / "nav-server" / "scripts" / "sf_nav.sh"
    else:
        path = ROOT / "main-server" / "scripts" / "real.sh"
    path = path.resolve()
    if not path.is_file() or not os.access(path, os.X_OK):
        raise StackError(f"{component} runner is missing or not executable: {path}")
    return path


def component_command(component: str, config: dict[str, Any]) -> list[str]:
    runner = runner_path(component, config)
    if component == "bridge":
        return [str(runner)]
    if component == "nav":
        profile = str(config.get("profile") or "")
        if not profile:
            raise StackError("enabled Nav component must select a Nav profile")
        return [str(runner), "--profile", profile, "foreground"]
    command = [str(runner)]
    if config.get("dev") is True:
        command.append("--dev")
    return command


def component_env(profile: dict[str, Any], component: str, token: str, run_id: str) -> dict[str, str]:
    env = dict(os.environ)
    for key in (
        "SF_NAV_ALLOW_SYNTHETIC_HIL",
        "LMS_NONPHYSICAL_TASK_ADMISSION_ENABLED",
        "LMS_NOHARDWARE_CALLBACK_ALLOWLIST",
        "NAV_NOHARDWARE_CALLBACK_ALLOWLIST",
    ):
        env.pop(key, None)
    env.update(
        {
            "SF_STACK_OWNERSHIP_TOKEN": token,
            "SF_STACK_RUN_ID": run_id,
            "SF_STACK_PROFILE": profile["profile_id"],
            "SIMULATION_MODE": "0",
            "DRY_RUN_MISSION": "0",
            "LMS_NOHARDWARE": "false",
            "NAV_NOHARDWARE": "false",
        }
    )
    if component == "nav" and profile["execution_class"] == "synthetic_hil":
        env["SF_NAV_ALLOW_SYNTHETIC_HIL"] = "1"
    if component == "main":
        config = profile["components"]["main"]
        env["SF_MAIN_SITE_PROFILE"] = str(config["site_profile"])
        env.update(config.get("env") or {})
    return env


def http_ready(url: str, timeout: float = 1.0) -> bool:
    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    try:
        with urlopen(request, timeout=timeout) as response:
            return 200 <= response.status < 300
    except (HTTPError, URLError, TimeoutError, OSError):
        return False


def nav_runtime_ready(config: dict[str, Any], env: dict[str, str]) -> bool:
    runner = runner_path("nav", config)
    profile = str(config["profile"])
    result = subprocess.run(
        [str(runner), "--profile", profile, "status"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        return False
    try:
        state = json.loads(result.stdout)
    except json.JSONDecodeError:
        return False
    return state.get("status") == "running" and state.get("observed_status") == "running"


def wait_component_ready(
    profile: dict[str, Any],
    component_name: str,
    component: dict[str, Any],
    env: dict[str, str],
    state: dict[str, Any],
) -> None:
    settle = float(os.getenv("SF_STACK_START_SETTLE_SEC", "0.2"))
    time.sleep(max(0.0, settle))
    token = str(state["ownership_token"])
    if not component_alive(component, token, str(state["boot_id"])):
        raise StackError(f"{component_name} exited during startup; see {component['log_path']}")
    if os.getenv("SF_STACK_READINESS_MODE", "full") == "process-only":
        return
    timeout = float(
        profile["components"][component_name].get(
            "readiness_timeout_sec", os.getenv("SF_STACK_READINESS_TIMEOUT_SEC", "60")
        )
    )
    urls = list((profile.get("health") or {}).get(component_name) or [])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if not component_alive(component, token, str(state["boot_id"])):
            raise StackError(f"{component_name} exited before readiness; see {component['log_path']}")
        runtime_ready = component_name != "nav" or nav_runtime_ready(profile["components"]["nav"], env)
        if runtime_ready and all(http_ready(url) for url in urls):
            return
        time.sleep(0.25)
    raise StackError(f"{component_name} readiness timed out after {timeout:g}s; see {component['log_path']}")


def enabled_components(profile: dict[str, Any]) -> list[str]:
    return [
        component
        for component in COMPONENT_ORDER
        if (profile.get("components") or {}).get(component, {}).get("enabled") is True
    ]


def create_initial_state(profile: dict[str, Any], run_id: str, run_dir: Path, token: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "profile_id": profile["profile_id"],
        "profile_path": profile["_profile_path"],
        "run_id": run_id,
        "run_dir": str(run_dir),
        "status": "starting",
        "message": "",
        "started_at": now_iso(),
        "stopped_at": None,
        "boot_id": boot_id(),
        "ownership_token": token,
        "components": {},
        "stop_order": [],
        "operator_urls": profile.get("operator_urls", []),
    }


def start_component(
    profile: dict[str, Any],
    component_name: str,
    run_dir: Path,
    token: str,
    run_id: str,
) -> tuple[dict[str, Any], dict[str, str]]:
    config = profile["components"][component_name]
    command = component_command(component_name, config)
    env = component_env(profile, component_name, token, run_id)
    log_path = run_dir / f"{component_name}.log"
    with log_path.open("ab", buffering=0) as log:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    OWNED_POPEN[process.pid] = process
    ticks = None
    for _ in range(50):
        ticks = process_start_ticks(process.pid)
        if ticks:
            break
        time.sleep(0.01)
    if not ticks:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        process.wait(timeout=2)
        OWNED_POPEN.pop(process.pid, None)
        raise StackError(f"unable to record {component_name} process identity")
    return (
        {
            "pid": process.pid,
            "process_group": process.pid,
            "start_ticks": ticks,
            "status": "starting",
            "command": command,
            "log_path": str(log_path),
            "started_at": now_iso(),
        },
        env,
    )


def stop_component(component: dict[str, Any], token: str, expected_boot_id: str) -> bool:
    pid = component.get("pid")
    if not component_alive(component, token, expected_boot_id):
        process = OWNED_POPEN.pop(pid, None) if isinstance(pid, int) else None
        if process is not None:
            try:
                process.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                pass
        component["status"] = "stopped"
        return False
    pgid = int(component["process_group"])
    for sig, timeout in ((signal.SIGINT, 10.0), (signal.SIGTERM, 5.0), (signal.SIGKILL, 2.0)):
        os.killpg(pgid, sig)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if not component_alive(component, token, expected_boot_id):
                process = OWNED_POPEN.pop(pid, None) if isinstance(pid, int) else None
                if process is not None:
                    try:
                        process.wait(timeout=0.5)
                    except subprocess.TimeoutExpired:
                        pass
                component["status"] = "stopped"
                component["stopped_at"] = now_iso()
                return True
            time.sleep(0.05)
    raise StackError(f"owned process group did not stop: pgid={pgid}")


def rollback(state_path: Path, state: dict[str, Any], message: str) -> None:
    token = str(state["ownership_token"])
    expected_boot_id = str(state["boot_id"])
    stopped: list[str] = []
    failures: list[str] = []
    for name in STOP_ORDER:
        component = state["components"].get(name)
        if not component:
            continue
        try:
            if stop_component(component, token, expected_boot_id):
                stopped.append(name)
        except StackError as exc:
            failures.append(str(exc))
    state["stop_order"] = stopped
    state["status"] = "degraded" if failures else "failed"
    state["message"] = message + ("; " + "; ".join(failures) if failures else "")
    state["stopped_at"] = now_iso()
    write_json(state_path, state)


def startup_static_checks(profile: dict[str, Any], local_ips: list[str]) -> None:
    validate_host(profile, local_ips)
    validate_ports(profile)
    for component in enabled_components(profile):
        runner_path(component, profile["components"][component])


def do_up(profile: dict[str, Any], local_ips: list[str]) -> tuple[Path, dict[str, Any]]:
    root = state_root()
    root.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(root, 0o700)
    lock_path = root / ".startup.lock"
    with lock_path.open("w", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise StackError("another stack startup is in progress") from exc
        refuse_active_stack()
        startup_static_checks(profile, local_ips)
        run_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{os.getpid()}-{secrets.token_hex(3)}"
        run_dir = root / profile["profile_id"] / run_id
        run_dir.mkdir(parents=True, mode=0o700)
        token = secrets.token_hex(16)
        state = create_initial_state(profile, run_id, run_dir, token)
        state_path = run_dir / "runtime-state.json"
        write_json(run_dir / "resolved-profile.json", {key: value for key, value in profile.items() if not key.startswith("_")})
        write_json(state_path, state)
        atomic_write(root / profile["profile_id"] / "latest", str(run_dir) + "\n")
        try:
            for component_name in enabled_components(profile):
                component, env = start_component(profile, component_name, run_dir, token, run_id)
                state["components"][component_name] = component
                write_json(state_path, state)
                wait_component_ready(profile, component_name, component, env, state)
                component["status"] = "running"
                write_json(state_path, state)
        except (OSError, StackError, subprocess.SubprocessError) as exc:
            rollback(state_path, state, f"startup rollback: {exc}")
            raise StackError(str(exc)) from exc
        state["status"] = "running"
        state["message"] = "all selected components are ready"
        write_json(state_path, state)
    print(f"[sf_stack] started profile={profile['profile_id']} run_id={state['run_id']}")
    print_operator_urls(state)
    return state_path, state


def load_latest_state(profile_id: str) -> tuple[Path, dict[str, Any]] | None:
    run_dir = latest_run_dir(profile_id)
    if run_dir is None:
        return None
    state_path = run_dir / "runtime-state.json"
    return state_path, load_json(state_path)


def do_down(profile: dict[str, Any]) -> None:
    found = load_latest_state(profile["profile_id"])
    if found is None:
        print(f"[sf_stack] no recorded run for profile={profile['profile_id']}")
        return
    state_path, state = found
    if state.get("status") == "stopped":
        print(f"[sf_stack] profile={profile['profile_id']} already stopped")
        return
    token = str(state.get("ownership_token") or "")
    expected_boot_id = str(state.get("boot_id") or "")
    stopped: list[str] = []
    failures: list[str] = []
    for name in STOP_ORDER:
        component = (state.get("components") or {}).get(name)
        if not component:
            continue
        try:
            if stop_component(component, token, expected_boot_id):
                stopped.append(name)
        except StackError as exc:
            failures.append(f"{name}: {exc}")
        write_json(state_path, state)
    state["stop_order"] = stopped
    state["stopped_at"] = now_iso()
    state["status"] = "degraded" if failures else "stopped"
    state["message"] = "; ".join(failures) if failures else "owned components stopped"
    write_json(state_path, state)
    if failures:
        raise StackError(state["message"])
    print(f"[sf_stack] stopped profile={profile['profile_id']} run_id={state.get('run_id')}")


def print_operator_urls(state: dict[str, Any]) -> None:
    for url in state.get("operator_urls") or []:
        print(f"  {url}")


def do_status(profile: dict[str, Any]) -> None:
    found = load_latest_state(profile["profile_id"])
    if found is None:
        print(f"[sf_stack] profile={profile['profile_id']} has no recorded run")
        return
    _, state = found
    token = str(state.get("ownership_token") or "")
    expected_boot_id = str(state.get("boot_id") or "")
    rows: list[tuple[str, str, Any]] = []
    for name, component in (state.get("components") or {}).items():
        observed = "running" if component_alive(component, token, expected_boot_id) else "stopped"
        rows.append((name, observed, component.get("pid")))
    observed_stack = "running" if rows and all(row[1] == "running" for row in rows) else "stopped"
    if state.get("status") == "running" and observed_stack != "running":
        observed_stack = "degraded"
    print(
        f"[sf_stack] profile={profile['profile_id']} stored={state.get('status')} "
        f"observed={observed_stack} run_id={state.get('run_id')}"
    )
    for name, observed, pid in rows:
        print(f"  {name:<7} {observed:<8} pid={pid}")
    print_operator_urls(state)


def do_logs(profile: dict[str, Any]) -> None:
    found = load_latest_state(profile["profile_id"])
    if found is None:
        raise StackError(f"profile={profile['profile_id']} has no recorded run")
    _, state = found
    for name, component in (state.get("components") or {}).items():
        path = Path(str(component.get("log_path") or ""))
        print(f"===== {name}: {path} =====")
        if path.is_file():
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
            print("\n".join(lines[-120:]))


def run_check_command(command: list[str], env: dict[str, str] | None = None) -> None:
    result = subprocess.run(command, cwd=ROOT, env=env, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise StackError(f"check failed: {' '.join(command)}: {detail}")
    output = (result.stdout or "").strip()
    if output:
        print(output)


def do_check(profile: dict[str, Any], local_ips: list[str]) -> None:
    startup_static_checks(profile, local_ips)
    for name in enabled_components(profile):
        config = profile["components"][name]
        runner = runner_path(name, config)
        if name == "bridge":
            run_check_command([str(runner), "--check"])
        elif name == "nav":
            run_check_command([str(runner), "--profile", str(config["profile"]), "print-config"])
        elif name == "main":
            env = component_env(profile, "main", "check-only", "check-only")
            command = [str(runner), "--check"]
            if config.get("dev") is True:
                command.append("--dev")
            run_check_command(command, env=env)
    print(f"[sf_stack] check OK profile={profile['profile_id']}")


def do_smoke(profile: dict[str, Any]) -> None:
    found = load_latest_state(profile["profile_id"])
    if found is None:
        raise StackError(f"profile={profile['profile_id']} has no recorded run")
    _, state = found
    if not state_observed_running(state):
        raise StackError("smoke requires every selected component to be running and owned")
    health = profile.get("health") or {}
    for component in enabled_components(profile):
        for url in health.get(component) or []:
            if not http_ready(url, timeout=2.0):
                raise StackError(f"smoke health failed: {url}")
            print(f"  [ok] {component} {url}")
    nav = profile["components"].get("nav") or {}
    if nav.get("enabled"):
        runner = runner_path("nav", nav)
        env = component_env(profile, "nav", "smoke-only", "smoke-only")
        run_check_command([str(runner), "--profile", str(nav["profile"]), "smoke"], env=env)
    for dependency in health.get("external") or []:
        url = str(dependency.get("url") or "")
        label = str(dependency.get("label") or url)
        ready = bool(url) and http_ready(url, timeout=2.0)
        if dependency.get("required") is True and not ready:
            raise StackError(f"required external health failed: {label} {url}")
        print(f"  [{'ok' if ready else 'warn'}] {label} {url}")
    print(f"[sf_stack] smoke OK profile={profile['profile_id']} (no robot motion)")


def do_foreground(profile: dict[str, Any], local_ips: list[str]) -> int:
    state_path, state = do_up(profile, local_ips)
    log_paths = [str(component["log_path"]) for component in state["components"].values()]
    tail: subprocess.Popen[bytes] | None = None
    if log_paths and os.getenv("SF_STACK_FOREGROUND_TAIL", "1") != "0" and shutil.which("tail"):
        tail = subprocess.Popen(["tail", "-n", "+1", "-F", *log_paths])

    def request_stop(signum: int, _frame: Any) -> None:
        raise TerminationRequested(signum)

    signal.signal(signal.SIGTERM, request_stop)
    print(f"[sf_stack] foreground attached profile={profile['profile_id']}; Ctrl+C stops owned components")
    exit_code = 0
    try:
        while True:
            current = load_json(state_path)
            if not state_observed_running(current):
                raise StackError("an owned component stopped unexpectedly")
            time.sleep(0.5)
    except KeyboardInterrupt:
        exit_code = 130
    except TerminationRequested as exc:
        exit_code = 128 + exc.signum
    finally:
        if tail is not None and tail.poll() is None:
            tail.terminate()
            try:
                tail.wait(timeout=2)
            except subprocess.TimeoutExpired:
                tail.kill()
        do_down(profile)
    return exit_code


def print_profiles(manifest: dict[str, Any], local_ips: list[str]) -> None:
    defaults = manifest.get("host_defaults") or {}
    host_default = next((defaults[ip] for ip in local_ips if ip in defaults), None)
    for name in manifest["profiles"]:
        suffix = " (default on this host)" if name == host_default else ""
        print(f"{name}{suffix}")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Start and stop the SmartFactory Main/Nav host bundle")
    result.add_argument("--profile", help="stack profile; otherwise select by this host's 192.168.30.x address")
    result.add_argument(
        "command",
        choices=("profiles", "print-config", "check", "up", "foreground", "status", "logs", "smoke", "down"),
    )
    return result


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "profiles":
            _, manifest = load_manifest()
            print_profiles(manifest, local_ipv4_addresses())
            return 0
        profile, _, local_ips = load_profile(args.profile)
        if args.command == "print-config":
            print(json.dumps({key: value for key, value in profile.items() if not key.startswith("_")}, indent=2, ensure_ascii=False))
        elif args.command == "check":
            do_check(profile, local_ips)
        elif args.command == "up":
            do_up(profile, local_ips)
        elif args.command == "foreground":
            return do_foreground(profile, local_ips)
        elif args.command == "status":
            do_status(profile)
        elif args.command == "logs":
            do_logs(profile)
        elif args.command == "smoke":
            do_smoke(profile)
        elif args.command == "down":
            do_down(profile)
        return 0
    except StackError as exc:
        print(f"[sf_stack] ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
