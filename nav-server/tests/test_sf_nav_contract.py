import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "sf_nav.sh"


def run_sf(*args, env=None):
    merged = os.environ.copy()
    merged.pop("SF_NAV_PROFILE", None)
    if env:
        merged.update(env)
    return subprocess.run([str(SCRIPT), *args], cwd=ROOT, env=merged, text=True, capture_output=True, check=True)


def test_profiles_and_print_config_are_profile_first():
    profiles = run_sf("profiles").stdout.splitlines()
    assert profiles[0] == "tb1-live (default)"
    default = json.loads(run_sf("print-config").stdout)
    tb2 = json.loads(run_sf("--profile", "tb2-live", "print-config").stdout)
    assert [robot["robot_id"] for robot in default["robots"]] == ["tb3_burger_01"]
    assert [robot["robot_id"] for robot in tb2["robots"]] == ["tb3_burger_02"]


def test_cli_beats_environment_and_print_config_is_stable():
    env = {"SF_NAV_PROFILE": "tb2-live"}
    assert json.loads(run_sf("print-config", env=env).stdout)["profile_id"] == "tb2-live"
    first = run_sf("--profile", "tb1-live", "print-config", env=env)
    second = run_sf("--profile", "tb1-live", "print-config", env=env)
    assert first.stdout == second.stdout
    assert first.stderr == ""


def test_run_nav_servers_consumes_resolved_plan(tmp_path):
    config_path = tmp_path / "resolved.json"
    config_path.write_text(run_sf("--profile", "tb2-live", "print-config").stdout)
    result = subprocess.run(
        [str(ROOT / "scripts" / "run_nav_servers.sh"), "--resolved-profile", str(config_path), "--print-plan"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=True,
        env={**os.environ, "PYTHON_BIN": sys.executable},
    )
    assert json.loads(result.stdout) == json.loads(config_path.read_text())


def test_generic_launcher_rejects_missing_resolved_profile():
    result = subprocess.run(
        [str(ROOT / "scripts" / "run_nav_servers.sh")],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHON_BIN": sys.executable},
    )
    assert result.returncode != 0
    assert "process start is owned by sf_nav.sh" in result.stderr


def test_generic_launcher_rejects_direct_run_even_with_resolved_profile(tmp_path):
    config_path = tmp_path / "resolved.json"
    config_path.write_text(run_sf("--profile", "tb1-live", "print-config").stdout)
    result = subprocess.run(
        [str(ROOT / "scripts" / "run_nav_servers.sh"), "--resolved-profile", str(config_path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        env={**os.environ, "PYTHON_BIN": sys.executable},
    )
    assert result.returncode != 0
    assert "process start is owned by sf_nav.sh" in result.stderr


def test_resolved_profile_preflight_still_validates_canonical_domains():
    script = (ROOT / "scripts" / "run_nav_servers.sh").read_text()
    validator_call = '"$PYTHON_BIN" "$VALIDATOR" --config "$ROBOTS_CONFIG_PATH" --bridge-dir "$ROOT/config/domain_bridge"'
    assert validator_call in script
    assert 'if [[ -z "$RESOLVED_PROFILE_PATH" ]]; then\n    "$PYTHON_BIN" "$VALIDATOR"' not in script
    assert "sf_nav_supervise" in script
    sf_nav = (ROOT / "scripts" / "sf_nav.sh").read_text()
    assert "source \"$RUN_SCRIPT\"; sf_nav_supervise" in sf_nav


def test_tb2_compatibility_wrapper_is_an_explicit_profile_alias():
    script = (ROOT / "scripts" / "start_all_tb3_2.sh").read_text()
    assert 'env SF_NAV_PROFILE=tb2-live "$SCRIPT_DIR/start_nav_servers.sh" foreground' in script
    assert 'env SF_NAV_PROFILE=tb2-live "$SCRIPT_DIR/start_nav_servers.sh" stop' in script
    assert 'pkill -f "run_nav_servers.sh"' not in script
    assert 'pkill -f "turtlebot3_navigation2"' not in script
    wrapper = (ROOT / "scripts" / "start_nav_servers.sh").read_text()
    assert 'foreground) exec "$SF_NAV" foreground' in wrapper
    assert '"$SCRIPT_DIR/run_nav_servers.sh" --resolved-profile' not in wrapper
    nohardware_smoke = (ROOT / "scripts" / "smoke_movement_api.sh").read_text()
    assert 'scripts/test-nohardware-tcp.sh' in nohardware_smoke
    assert '"$SCRIPT_DIR/run_nav_servers.sh"' not in nohardware_smoke


def test_every_profile_declares_base_component():
    for name in ("tb1-live", "tb2-live", "all-live", "tb1-synthetic-hil"):
        resolved = json.loads(run_sf("--profile", name, "print-config").stdout)
        assert resolved["components"]["base"]["enabled"] is True
        assert resolved["components"]["base"]["ownership"] == "external"
        assert resolved["components"]["nav2"] == {
            "enabled": True,
            "ownership": "managed-script",
            "readiness_probe": "lifecycle-active",
            "required": True,
            "start_script": "scripts/run_nav2_with_initial_pose.sh",
        }


def test_live_profiles_manage_the_local_aruco_detector_with_the_nav_stack():
    for name in ("tb1-live", "tb2-live", "all-live"):
        resolved = json.loads(run_sf("--profile", name, "print-config").stdout)
        assert resolved["components"]["detector"] == {
            "enabled": True,
            "ownership": "managed-script",
            "readiness_probe": "aruco-topic",
            "required": True,
            "start_script": "scripts/run_pi_camera_aruco.sh",
        }

    launcher = (ROOT / "scripts" / "run_nav_servers.sh").read_text()
    assert "start_aruco_detector" in launcher
    assert 'START_CAMERA_LAUNCH="0"' in launcher
    assert 'START_CAMERA_RELAY="0"' in launcher


def test_smoke_uses_current_health_and_endpoint_contract(tmp_path):
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    config = json.loads(run_sf("--profile", "tb1-live", "print-config").stdout)
    config["robots"][0]["api_port"] = port
    resolved = tmp_path / "resolved.json"
    resolved.write_text(json.dumps(config))
    server = tmp_path / "server.py"
    server.write_text(
        "from http.server import BaseHTTPRequestHandler,HTTPServer\n"
        "import json,sys\n"
        "class H(BaseHTTPRequestHandler):\n"
        " def do_GET(self):\n"
        "  if self.path=='/movement-api/v1/health': body={'ok':True,'active_robot_id':'tb3_burger_01','ros_domain_id':2,'process_ros_domain_id':42}\n"
        "  elif self.path=='/movement-api/v1/endpoints': body={'nav_api_url':'http://smartfactory-nav.local:8001'}\n"
        "  else: self.send_response(404); self.end_headers(); return\n"
        "  payload=json.dumps(body).encode(); self.send_response(200); self.send_header('Content-Length',str(len(payload))); self.end_headers(); self.wfile.write(payload)\n"
        " def log_message(self,*args): pass\n"
        "HTTPServer(('127.0.0.1',int(sys.argv[1])),H).serve_forever()\n"
    )
    process = subprocess.Popen([sys.executable, str(server), str(port)])
    try:
        for _ in range(50):
            with socket.socket() as client:
                if client.connect_ex(("127.0.0.1", port)) == 0:
                    break
            time.sleep(0.02)
        result = subprocess.run(
            [str(ROOT / "scripts" / "smoke_nav_servers.sh")],
            cwd=ROOT,
            env={**os.environ, "SF_NAV_RESOLVED_PROFILE_PATH": str(resolved)},
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, result.stderr
        assert "PASS tb3_burger_01" in result.stdout
        assert "/mission/start" not in (ROOT / "scripts" / "smoke_nav_servers.sh").read_text()
    finally:
        process.terminate()
        process.wait(timeout=5)
