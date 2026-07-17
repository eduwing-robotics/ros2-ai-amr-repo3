import json
import os
import signal
import socket
import subprocess
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sf_nav.sh"


def _isolated_profile(tmp_path: Path, port: int) -> dict[str, str]:
    robots = json.loads((ROOT / "config/robots.json").read_text())
    robots["robots"] = [robots["robots"][0]]
    robots["robots"][0]["api_port"] = port
    robots_path = tmp_path / "robots.json"
    robots_path.write_text(json.dumps(robots))
    profile_dir = tmp_path / "profiles"
    profile_dir.mkdir()
    profile = {
        "profile_id": "isolated-live",
        "enabled": True,
        "execution_class": "live",
        "evidence_class": "physical",
        "robot_selector": {"robot_ids": ["tb3_burger_01"]},
        "components": {
            "movement_api": {
                "enabled": True,
                "required": True,
                "ownership": "managed-script",
                "start_script": "scripts/run_nav_servers.sh",
                "readiness_probe": "/movement-api/v1/health",
            }
        },
    }
    (profile_dir / "isolated.json").write_text(json.dumps(profile))
    manifest = {"schema_version": 1, "default_profile": "isolated-live", "profiles": {"isolated-live": "isolated.json"}}
    manifest_path = profile_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))
    return {"SF_NAV_MANIFEST": str(manifest_path), "ROBOTS_CONFIG_PATH": str(robots_path)}


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _health_server_script(path: Path, *, response_delay: float = 0.0) -> Path:
    path.write_text(
        "#!/usr/bin/env bash\n"
        "exec python3 - \"$SF_NAV_RESOLVED_PROFILE_PATH\" <<'PY'\n"
        "from http.server import BaseHTTPRequestHandler,HTTPServer\n"
        "import json,sys,time\n"
        "import os\n"
        "cfg=json.load(open(sys.argv[1])); robot=cfg['robots'][0]; lift_ready=os.getenv('FAKE_LIFT_READY','0')=='1'; nav2_ready=os.getenv('FAKE_NAV2_READY','1')=='1'\n"
        "class H(BaseHTTPRequestHandler):\n"
        " def do_GET(self):\n"
        f"  time.sleep({response_delay!r})\n"
        "  if self.path=='/movement-api/v1/health': body={'ok':True,'active_robot_id':robot['robot_id'],'ros_domain_id':robot['ros_domain_id'],'process_ros_domain_id':robot['nav_local_domain_id'],'nav2_ready':nav2_ready,'localized':nav2_ready,'lift':{'ready':lift_ready}}\n"
        "  elif self.path=='/movement-api/v1/endpoints': body={'nav_api_url':'http://smartfactory-nav.local:8001'}\n"
        "  else: self.send_response(404); self.end_headers(); return\n"
        "  payload=json.dumps(body).encode(); self.send_response(200); self.send_header('Content-Length',str(len(payload))); self.end_headers(); self.wfile.write(payload)\n"
        " def log_message(self,*args): pass\n"
        "HTTPServer(('127.0.0.1',robot['api_port']),H).serve_forever()\n"
        "PY\n"
    )
    path.chmod(0o755)
    return path


def test_owned_process_group_stops_without_touching_unselected_process(tmp_path):
    fake_run = tmp_path / "fake-run.sh"
    fake_run.write_text("#!/usr/bin/env bash\ntrap 'exit 0' TERM INT\nwhile :; do sleep 0.1; done\n")
    fake_run.chmod(0o755)
    sentinel = subprocess.Popen(["sleep", "30"], start_new_session=True)
    env = {
        **os.environ,
        "SF_NAV_STATE_DIR": str(tmp_path / "state"),
        "SF_NAV_RUN_SCRIPT": str(fake_run),
        "SF_NAV_START_SETTLE_SEC": "0.05",
        "SF_NAV_READINESS_MODE": "process-only",
    }
    try:
        up = subprocess.run([str(SCRIPT), "--profile", "tb1-live", "up"], cwd=ROOT, env=env, text=True, capture_output=True, check=True)
        assert "profile=tb1-live" in up.stdout
        latest = Path((tmp_path / "state" / "tb1-live" / "latest").read_text().strip())
        state = json.loads((latest / "runtime-state.json").read_text())
        managed_pid = state["components"]["movement_api"]["pid"]
        assert state["ownership_token"]
        assert os.kill(managed_pid, 0) is None

        repeated = subprocess.run(
            [str(SCRIPT), "--profile", "tb1-live", "up"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
        )
        assert repeated.returncode != 0
        assert "resources overlap active profile=tb1-live" in repeated.stderr
        assert Path((tmp_path / "state" / "tb1-live" / "latest").read_text().strip()) == latest
        assert os.kill(managed_pid, 0) is None

        down = subprocess.run([str(SCRIPT), "--profile", "tb1-live", "down"], cwd=ROOT, env=env, text=True, capture_output=True, check=True)
        assert "stopped profile=tb1-live" in down.stdout
        assert sentinel.poll() is None
        stopped = json.loads((latest / "runtime-state.json").read_text())
        assert stopped["status"] == "stopped"
        again = subprocess.run([str(SCRIPT), "--profile", "tb1-live", "down"], cwd=ROOT, env=env, text=True, capture_output=True, check=True)
        assert "already stopped" in again.stdout
    finally:
        if sentinel.poll() is None:
            os.killpg(sentinel.pid, signal.SIGTERM)
            sentinel.wait(timeout=5)


def test_foreground_ctrl_c_stops_owned_process_group(tmp_path):
    fake_run = tmp_path / "fake-run.sh"
    fake_run.write_text("#!/usr/bin/env bash\ntrap 'exit 0' TERM INT\nwhile :; do sleep 0.1; done\n")
    fake_run.chmod(0o755)
    state_root = tmp_path / "state"
    env = {
        **os.environ,
        "SF_NAV_STATE_DIR": str(state_root),
        "SF_NAV_RUN_SCRIPT": str(fake_run),
        "SF_NAV_START_SETTLE_SEC": "0.05",
        "SF_NAV_READINESS_MODE": "process-only",
    }
    process = subprocess.Popen(
        [str(SCRIPT), "--profile", "tb1-live", "foreground"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    latest_file = state_root / "tb1-live" / "latest"
    state_path = None
    try:
        for _ in range(100):
            if latest_file.is_file():
                state_path = Path(latest_file.read_text().strip()) / "runtime-state.json"
                if state_path.is_file() and json.loads(state_path.read_text()).get("status") == "running":
                    break
            time.sleep(0.05)
        else:
            raise AssertionError("foreground profile did not become running")
        managed_pid = json.loads(state_path.read_text())["components"]["movement_api"]["pid"]
        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 130, (stdout, stderr)
        assert json.loads(state_path.read_text())["status"] == "stopped"
        with pytest.raises(ProcessLookupError):
            os.kill(managed_pid, 0)
    finally:
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=5)


def test_failed_managed_start_records_failure(tmp_path):
    fake_run = tmp_path / "fail.sh"
    fake_run.write_text("#!/usr/bin/env bash\nexit 7\n")
    fake_run.chmod(0o755)
    env = {
        **os.environ,
        "SF_NAV_STATE_DIR": str(tmp_path / "state"),
        "SF_NAV_RUN_SCRIPT": str(fake_run),
        "SF_NAV_START_SETTLE_SEC": "0.05",
        "SF_NAV_READINESS_MODE": "process-only",
    }
    result = subprocess.run([str(SCRIPT), "up"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert result.returncode != 0
    latest = Path((tmp_path / "state" / "tb1-live" / "latest").read_text().strip())
    assert json.loads((latest / "runtime-state.json").read_text())["status"] == "failed"


def test_synthetic_hil_requires_explicit_admission_and_forces_live_mission_modes(tmp_path):
    observed_env = tmp_path / "observed-env"
    fake_run = tmp_path / "fake-run.sh"
    fake_run.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s %s\\n' \"$SIMULATION_MODE\" \"$DRY_RUN_MISSION\" > {observed_env!s}\n"
        "trap 'exit 0' TERM INT\n"
        "while :; do sleep 0.1; done\n"
    )
    fake_run.chmod(0o755)
    state_dir = tmp_path / "state"
    env = {
        **os.environ,
        "SF_NAV_STATE_DIR": str(state_dir),
        "SF_NAV_RUN_SCRIPT": str(fake_run),
        "SF_NAV_START_SETTLE_SEC": "0.05",
        "SIMULATION_MODE": "1",
        "DRY_RUN_MISSION": "1",
        "SF_NAV_READINESS_MODE": "process-only",
    }

    rejected = subprocess.run(
        [str(SCRIPT), "--profile", "tb1-synthetic-hil", "up"],
        cwd=ROOT,
        env=env,
        text=True,
        capture_output=True,
    )
    assert rejected.returncode != 0
    assert "SF_NAV_ALLOW_SYNTHETIC_HIL=1" in rejected.stderr
    assert not (state_dir / "tb1-synthetic-hil" / "latest").exists()

    admitted_env = {**env, "SF_NAV_ALLOW_SYNTHETIC_HIL": "1"}
    subprocess.run(
        [str(SCRIPT), "--profile", "tb1-synthetic-hil", "up"],
        cwd=ROOT,
        env=admitted_env,
        text=True,
        capture_output=True,
        check=True,
    )
    try:
        assert observed_env.read_text().strip() == "0 0"
    finally:
        subprocess.run(
            [str(SCRIPT), "--profile", "tb1-synthetic-hil", "down"],
            cwd=ROOT,
            env=admitted_env,
            text=True,
            capture_output=True,
            check=True,
        )


def test_tampered_process_identity_refuses_to_signal_unrelated_process(tmp_path):
    sentinel = subprocess.Popen(["sleep", "30"], start_new_session=True)
    state_dir = tmp_path / "state"
    run_dir = state_dir / "tb1-live" / "tampered"
    run_dir.mkdir(parents=True)
    (state_dir / "tb1-live" / "latest").write_text(str(run_dir))
    state = {
        "schema_version": 1,
        "run_id": "tampered",
        "ownership_token": "not-the-process-token",
        "status": "running",
        "started_at": "2026-01-01T00:00:00Z",
        "boot_id": "mismatch",
        "components": {
            "movement_api": {
                "ownership": "managed-script",
                "pid": sentinel.pid,
                "process_group": sentinel.pid,
                "process_start_ticks": "0",
                "identity": "fake-run.sh",
                "status": "running",
            }
        },
    }
    (run_dir / "runtime-state.json").write_text(json.dumps(state))
    env = {**os.environ, "SF_NAV_STATE_DIR": str(state_dir)}
    try:
        result = subprocess.run(
            [str(SCRIPT), "--profile", "tb1-live", "down"],
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
        )
        assert result.returncode != 0
        assert "ownership identity mismatch" in result.stderr
        assert sentinel.poll() is None
    finally:
        os.killpg(sentinel.pid, signal.SIGTERM)
        sentinel.wait(timeout=5)


def test_required_readiness_failure_rolls_back_managed_process(tmp_path):
    fake_run = tmp_path / "fake-run.sh"
    fake_run.write_text("#!/usr/bin/env bash\ntrap 'exit 0' TERM INT\nwhile :; do sleep 0.1; done\n")
    fake_run.chmod(0o755)
    env = {
        **os.environ,
        "SF_NAV_STATE_DIR": str(tmp_path / "state"),
        "SF_NAV_RUN_SCRIPT": str(fake_run),
        "SF_NAV_START_SETTLE_SEC": "0.02",
        "SF_NAV_READINESS_TIMEOUT_SEC": "0.1",
        "SF_NAV_READINESS_MODE": "http",
    }
    result = subprocess.run([str(SCRIPT), "up"], cwd=ROOT, env=env, text=True, capture_output=True)
    assert result.returncode != 0
    latest = Path((tmp_path / "state" / "tb1-live" / "latest").read_text().strip())
    state = json.loads((latest / "runtime-state.json").read_text())
    assert state["status"] == "failed"
    assert state["stop_result"]["exited"] is True
    with pytest.raises(ProcessLookupError):
        os.kill(state["components"]["movement_api"]["pid"], 0)


def test_full_readiness_requires_managed_nav2_localization(tmp_path):
    port = _free_port()
    robots = json.loads((ROOT / "config/robots.json").read_text())
    robots["robots"] = [robots["robots"][0]]
    robots["robots"][0]["api_port"] = port
    robots_path = tmp_path / "robots.json"
    robots_path.write_text(json.dumps(robots))
    fake_run = _health_server_script(tmp_path / "fake-run.sh")
    env = {
        **os.environ,
        "ROBOTS_CONFIG_PATH": str(robots_path),
        "SF_NAV_STATE_DIR": str(tmp_path / "state"),
        "SF_NAV_RUN_SCRIPT": str(fake_run),
        "SF_NAV_START_SETTLE_SEC": "0.02",
        "SF_NAV_READINESS_MODE": "full",
        "SF_NAV_READINESS_TIMEOUT_SEC": "0.3",
        "FAKE_NAV2_READY": "0",
    }

    result = subprocess.run(
        [str(SCRIPT), "--profile", "tb1-live", "up"], cwd=ROOT, env=env, capture_output=True, text=True
    )

    assert result.returncode != 0
    latest = Path((tmp_path / "state" / "tb1-live" / "latest").read_text().strip())
    state = json.loads((latest / "runtime-state.json").read_text())
    assert state["status"] == "failed"
    assert state["stop_result"]["exited"] is True


def test_http_readiness_exposes_service_before_localization(tmp_path):
    port = _free_port()
    robots = json.loads((ROOT / "config/robots.json").read_text())
    robots["robots"] = [robots["robots"][0]]
    robots["robots"][0]["api_port"] = port
    robots_path = tmp_path / "robots.json"
    robots_path.write_text(json.dumps(robots))
    fake_run = _health_server_script(tmp_path / "fake-run.sh")
    env = {
        **os.environ,
        "ROBOTS_CONFIG_PATH": str(robots_path),
        "SF_NAV_STATE_DIR": str(tmp_path / "state"),
        "SF_NAV_RUN_SCRIPT": str(fake_run),
        "SF_NAV_START_SETTLE_SEC": "0.02",
        "SF_NAV_READINESS_MODE": "http",
        "SF_NAV_READINESS_TIMEOUT_SEC": "1",
        "FAKE_NAV2_READY": "0",
    }

    result = subprocess.run(
        [str(SCRIPT), "--profile", "tb1-live", "up"], cwd=ROOT, env=env, capture_output=True, text=True
    )

    assert result.returncode == 0, result.stderr
    try:
        latest = Path((tmp_path / "state" / "tb1-live" / "latest").read_text().strip())
        state = json.loads((latest / "runtime-state.json").read_text())
        assert state["status"] == "running"
    finally:
        subprocess.run(
            [str(SCRIPT), "--profile", "tb1-live", "down"],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )


def test_cross_profile_resource_overlap_is_rejected(tmp_path):
    fake_run = tmp_path / "fake-run.sh"
    fake_run.write_text("#!/usr/bin/env bash\ntrap 'exit 0' TERM INT\nwhile :; do sleep 0.1; done\n")
    fake_run.chmod(0o755)
    env = {
        **os.environ,
        "SF_NAV_STATE_DIR": str(tmp_path / "state"),
        "SF_NAV_RUN_SCRIPT": str(fake_run),
        "SF_NAV_START_SETTLE_SEC": "0.02",
        "SF_NAV_READINESS_MODE": "process-only",
    }
    subprocess.run([str(SCRIPT), "--profile", "tb1-live", "up"], cwd=ROOT, env=env, check=True, capture_output=True, text=True)
    try:
        conflict = subprocess.run(
            [str(SCRIPT), "--profile", "all-live", "up"], cwd=ROOT, env=env, capture_output=True, text=True
        )
        assert conflict.returncode != 0
        assert "resources overlap active profile=tb1-live" in conflict.stderr
        assert not (tmp_path / "state" / "all-live" / "latest").exists()
    finally:
        subprocess.run([str(SCRIPT), "--profile", "tb1-live", "down"], cwd=ROOT, env=env, check=True, capture_output=True, text=True)


def test_live_stop_failed_run_keeps_resources_until_process_exits(tmp_path):
    fake_run = tmp_path / "fake-run.sh"
    fake_run.write_text("#!/usr/bin/env bash\ntrap 'exit 0' TERM INT\nwhile :; do sleep 0.1; done\n")
    fake_run.chmod(0o755)
    env = {
        **os.environ,
        "SF_NAV_STATE_DIR": str(tmp_path / "state"),
        "SF_NAV_RUN_SCRIPT": str(fake_run),
        "SF_NAV_START_SETTLE_SEC": "0.02",
        "SF_NAV_READINESS_MODE": "process-only",
    }
    subprocess.run([str(SCRIPT), "--profile", "tb1-live", "up"], cwd=ROOT, env=env, check=True, capture_output=True, text=True)
    latest = Path((tmp_path / "state/tb1-live/latest").read_text().strip())
    state_path = latest / "runtime-state.json"
    state = json.loads(state_path.read_text())
    state["status"] = "stop_failed"
    state_path.write_text(json.dumps(state))
    conflict = subprocess.run(
        [str(SCRIPT), "--profile", "all-live", "up"], cwd=ROOT, env=env, capture_output=True, text=True
    )
    assert conflict.returncode != 0
    assert "resources overlap active profile=tb1-live" in conflict.stderr

    os.killpg(state["components"]["movement_api"]["process_group"], signal.SIGTERM)
    for _ in range(50):
        try:
            os.kill(state["components"]["movement_api"]["pid"], 0)
        except ProcessLookupError:
            break
        time.sleep(0.02)
    observed = subprocess.run(
        [str(SCRIPT), "--profile", "tb1-live", "status"], cwd=ROOT, env=env, capture_output=True, text=True, check=True
    )
    assert json.loads(observed.stdout)["observed_status"] == "stopped"


def test_failure_immediately_after_spawn_rolls_back_without_state_file(tmp_path):
    observed_pid = tmp_path / "observed-pid"
    fake_run = tmp_path / "fake-run.sh"
    fake_run.write_text(
        f"#!/usr/bin/env bash\necho $$ > {observed_pid}\ntrap 'exit 0' TERM INT\nwhile :; do sleep 0.1; done\n"
    )
    fake_run.chmod(0o755)
    env = {
        **os.environ,
        "SF_NAV_STATE_DIR": str(tmp_path / "state"),
        "SF_NAV_RUN_SCRIPT": str(fake_run),
        "SF_NAV_FAIL_AFTER_SPAWN": "1",
        "SF_NAV_START_SETTLE_SEC": "0.02",
        "SF_NAV_READINESS_MODE": "process-only",
    }
    result = subprocess.run([str(SCRIPT), "up"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode != 0
    for _ in range(50):
        if observed_pid.is_file():
            break
        time.sleep(0.01)
    pid = int(observed_pid.read_text())
    for _ in range(50):
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.02)
    else:
        pytest.fail("spawned process survived pre-state rollback")


def _fake_ros2(tmp_path: Path, *, include_lift: bool, base_node: str = "turtlebot3_node") -> Path:
    fake_bin = tmp_path / ("ros-ok" if include_lift else "ros-missing-lift")
    fake_bin.mkdir()
    topics = [
        "/odom", "/scan",
        "/lift/cmd_move", "/lift/cmd_home", "/lift/cmd_stop",
        "/lift/position", "/lift/direction", "/lift/limit_lower",
    ]
    if not include_lift:
        topics.pop()
    script = fake_bin / "ros2"
    script.write_text(
        "#!/usr/bin/env bash\n"
        f"if [[ \"$1 $2 $3\" == 'topic info /cmd_vel' ]]; then printf '%s\\n' 'Subscription count: 1' 'Node name: {base_node}'; exit 0; fi\n"
        "if [[ \"$1 $2\" == 'lifecycle get' ]]; then echo active; exit 0; fi\n"
        "if [[ \"$1 $2\" == 'topic list' ]]; then printf '%s\\n' "
        + " ".join(f"'{topic}'" for topic in topics)
        + "; exit 0; fi\nexit 1\n"
    )
    script.chmod(0o755)
    return fake_bin


@pytest.mark.parametrize(
    "base_node, succeeds",
    [("tb3_1_hardware_nav_42", True), ("tb3_2_hardware_nav_42", False)],
)
def test_tb1_full_readiness_matches_selected_hardware_bridge(tmp_path, base_node, succeeds):
    port = _free_port()
    robots = json.loads((ROOT / "config/robots.json").read_text())
    robots["robots"] = [robots["robots"][0]]
    robots["robots"][0]["api_port"] = port
    robots_path = tmp_path / "robots.json"
    robots_path.write_text(json.dumps(robots))
    fake_run = _health_server_script(tmp_path / "fake-run.sh")
    env = {
        **os.environ,
        "PATH": f"{_fake_ros2(tmp_path, include_lift=True, base_node=base_node)}:{os.environ['PATH']}",
        "ROBOTS_CONFIG_PATH": str(robots_path),
        "SF_NAV_STATE_DIR": str(tmp_path / "state"),
        "SF_NAV_RUN_SCRIPT": str(fake_run),
        "SF_NAV_START_SETTLE_SEC": "0.02",
        "SF_NAV_READINESS_MODE": "full",
        "SF_NAV_READINESS_TIMEOUT_SEC": "1",
    }
    result = subprocess.run(
        [str(SCRIPT), "--profile", "tb1-live", "up"], cwd=ROOT, env=env, capture_output=True, text=True
    )
    assert (result.returncode == 0) is succeeds, result.stderr
    if succeeds:
        subprocess.run(
            [str(SCRIPT), "--profile", "tb1-live", "down"],
            cwd=ROOT,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
    else:
        latest = Path((tmp_path / "state" / "tb1-live" / "latest").read_text().strip())
        assert json.loads((latest / "runtime-state.json").read_text())["status"] == "failed"


@pytest.mark.parametrize("include_lift, succeeds", [(True, True), (False, False)])
def test_tb2_external_readiness_checks_lift_topics(tmp_path, include_lift, succeeds):
    fake_run = _health_server_script(tmp_path / "fake-run.sh")
    env = {
        **os.environ,
        "PATH": f"{_fake_ros2(tmp_path, include_lift=include_lift)}:{os.environ['PATH']}",
        "SF_NAV_STATE_DIR": str(tmp_path / "state"),
        "SF_NAV_RUN_SCRIPT": str(fake_run),
        "FAKE_LIFT_READY": "1" if include_lift else "0",
        "SF_NAV_START_SETTLE_SEC": "0.02",
        "SF_NAV_READINESS_MODE": "full",
        "SF_NAV_READINESS_TIMEOUT_SEC": "1",
    }
    result = subprocess.run(
        [str(SCRIPT), "--profile", "tb2-live", "up"], cwd=ROOT, env=env, capture_output=True, text=True
    )
    assert (result.returncode == 0) is succeeds, result.stderr
    if succeeds:
        subprocess.run([str(SCRIPT), "--profile", "tb2-live", "down"], cwd=ROOT, env=env, check=True, capture_output=True, text=True)
    else:
        latest = Path((tmp_path / "state" / "tb2-live" / "latest").read_text().strip())
        assert json.loads((latest / "runtime-state.json").read_text())["status"] == "failed"


def test_http_readiness_records_services_owned_by_spawned_process_group(tmp_path):
    port = _free_port()
    fake_run = _health_server_script(tmp_path / "health-run.sh")
    env = {
        **os.environ,
        **_isolated_profile(tmp_path, port),
        "SF_NAV_STATE_DIR": str(tmp_path / "state"),
        "SF_NAV_RUN_SCRIPT": str(fake_run),
        "SF_NAV_START_SETTLE_SEC": "0.02",
        "SF_NAV_READINESS_MODE": "http",
        "SF_NAV_READINESS_TIMEOUT_SEC": "2",
    }
    result = subprocess.run([str(SCRIPT), "up"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    try:
        latest = Path((tmp_path / "state/isolated-live/latest").read_text().strip())
        state = json.loads((latest / "runtime-state.json").read_text())
        identity = state["components"]["movement_api"]["service_identities"]["tb3_burger_01"]
        assert identity["api_port"] == port
        assert identity["process_group"] == state["components"]["movement_api"]["process_group"]
        assert identity["pids"]
    finally:
        subprocess.run([str(SCRIPT), "down"], cwd=ROOT, env=env, check=True, capture_output=True, text=True)


def test_http_readiness_accepts_bounded_slow_health_response(tmp_path):
    port = _free_port()
    fake_run = _health_server_script(tmp_path / "slow-health-run.sh", response_delay=0.4)
    env = {
        **os.environ,
        **_isolated_profile(tmp_path, port),
        "SF_NAV_STATE_DIR": str(tmp_path / "state"),
        "SF_NAV_RUN_SCRIPT": str(fake_run),
        "SF_NAV_START_SETTLE_SEC": "0.02",
        "SF_NAV_READINESS_MODE": "http",
        "SF_NAV_READINESS_TIMEOUT_SEC": "2",
    }
    result = subprocess.run([str(SCRIPT), "up"], cwd=ROOT, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    subprocess.run([str(SCRIPT), "down"], cwd=ROOT, env=env, check=True, capture_output=True, text=True)


def test_http_readiness_rejects_foreign_service_on_selected_port(tmp_path):
    port = _free_port()
    config_env = _isolated_profile(tmp_path, port)
    resolved = subprocess.run(
        [str(SCRIPT), "print-config"], cwd=ROOT, env={**os.environ, **config_env}, capture_output=True, text=True, check=True
    ).stdout
    resolved_path = tmp_path / "foreign-resolved.json"
    resolved_path.write_text(resolved)
    foreign_script = _health_server_script(tmp_path / "foreign.sh")
    foreign = subprocess.Popen(
        [str(foreign_script)], env={**os.environ, "SF_NAV_RESOLVED_PROFILE_PATH": str(resolved_path)}, start_new_session=True
    )
    fake_run = tmp_path / "idle-run.sh"
    fake_run.write_text("#!/usr/bin/env bash\ntrap 'exit 0' TERM INT\nwhile :; do sleep 0.1; done\n")
    fake_run.chmod(0o755)
    env = {
        **os.environ,
        **config_env,
        "SF_NAV_STATE_DIR": str(tmp_path / "state"),
        "SF_NAV_RUN_SCRIPT": str(fake_run),
        "SF_NAV_START_SETTLE_SEC": "0.02",
        "SF_NAV_READINESS_MODE": "http",
        "SF_NAV_READINESS_TIMEOUT_SEC": "0.3",
    }
    try:
        for _ in range(50):
            with socket.socket() as client:
                if client.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.02)
        result = subprocess.run([str(SCRIPT), "up"], cwd=ROOT, env=env, capture_output=True, text=True)
        assert result.returncode != 0
        latest = Path((tmp_path / "state/isolated-live/latest").read_text().strip())
        assert json.loads((latest / "runtime-state.json").read_text())["status"] == "failed"
        assert foreign.poll() is None
    finally:
        os.killpg(foreign.pid, signal.SIGTERM)
        foreign.wait(timeout=5)
