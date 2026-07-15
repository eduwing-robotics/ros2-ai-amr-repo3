"""Black-box regression tests for the read-only operator preflight."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "operator-preflight.sh"
CREDENTIAL_LIBRARY = ROOT / "scripts" / "lib" / "site_credentials.sh"


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _environment(temp: Path) -> dict[str, str]:
    bin_dir = temp / "bin"
    bin_dir.mkdir()
    ros_setup = temp / "ros-setup.bash"
    ros_setup.write_text("# test ROS setup\n", encoding="utf-8")
    _write_executable(bin_dir / "ros2", "#!/usr/bin/env bash\nexit 0\n")
    _write_executable(bin_dir / "docker", "#!/usr/bin/env bash\n[ \"$1\" = info ] && exit 0\nexit 1\n")
    _write_executable(bin_dir / "ss", "#!/usr/bin/env bash\nexit 0\n")
    env = os.environ.copy()
    env.update(
        {
            "PATH": f"{bin_dir}:{env['PATH']}",
            "ROS_SETUP": str(ros_setup),
            "OPERATOR_PREFLIGHT_REQUIRED_PORTS": "65501,65502",
        }
    )
    return env


def _checkout(temp: Path, *, with_credentials: bool) -> tuple[Path, dict[str, str]]:
    checkout = temp / "checkout"
    (checkout / "scripts/lib").mkdir(parents=True)
    shutil.copy2(SCRIPT, checkout / "scripts/operator-preflight.sh")
    shutil.copy2(CREDENTIAL_LIBRARY, checkout / "scripts/lib/site_credentials.sh")
    _write_executable(checkout / "scripts/test-nohardware-config.sh", "#!/usr/bin/env bash\nexit 0\n")
    for service in ("ai-server", "main-server", "nav-server"):
        bin_dir = checkout / service / ".venv/bin"
        bin_dir.mkdir(parents=True)
        _write_executable(bin_dir / "python", "#!/usr/bin/env bash\nexit 0\n")
        _write_executable(bin_dir / "pip", "#!/usr/bin/env bash\nexit 0\n")
    nav_scripts = checkout / "nav-server/scripts"
    nav_scripts.mkdir(parents=True)
    _write_executable(nav_scripts / "run_nav_servers.sh", "#!/usr/bin/env bash\nexit 0\n")
    for relative in (
        "config/robots.json",
        "config/main_server_routes.json",
        "map/robot1_map.yaml",
        "map/robot2_map.yaml",
        "map/robot1_map.pgm",
        "map/robot2_map.pgm",
    ):
        path = checkout / "nav-server" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{}\n", encoding="utf-8")
    if not with_credentials:
        return checkout / "scripts/operator-preflight.sh", {}
    result = subprocess.run(
        [
            "bash",
            "-c",
            f'source "{checkout}/scripts/lib/site_credentials.sh"; sf_ensure_site_credentials "{checkout}"',
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    values = {}
    for line in (checkout / ".secrets/service-hmac.env").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            key, value = line.split("=", 1)
            values[key] = value
    return checkout / "scripts/operator-preflight.sh", values


def _run(
    *args: str,
    env: dict[str, str] | None = None,
    script: Path = SCRIPT,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(script), *args], cwd=script.parents[1], env=env, text=True, capture_output=True, check=False
    )


def test_help_is_available():
    result = _run("--help")
    assert result.returncode == 0
    assert "--software" in result.stdout
    assert "no motion" in result.stdout.lower()


def test_software_json_does_not_leak_hmac_secrets_and_uses_no_motion_commands():
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        env = _environment(temp)
        script, values = _checkout(temp, with_credentials=True)
        result = _run("--software", "--json", env=env, script=script)

    assert result.returncode == 0, result.stderr
    for key, value in values.items():
        if key == "SMARTFACTORY_CREDENTIAL_SET_ID":
            continue
        assert value not in result.stdout
        assert value not in result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert next(item for item in payload["checks"] if item["name"] == "site_credential_bundle")["status"] == "PASS"
    assert all("motion" not in item["message"].lower() for item in payload["checks"])


def test_software_fails_clearly_when_hmac_secrets_are_missing():
    with tempfile.TemporaryDirectory() as directory:
        temp = Path(directory)
        env = _environment(temp)
        script, _ = _checkout(temp, with_credentials=False)
        env.pop("NAV_MAIN_HMAC_SECRET", None)
        env.pop("LMS_MOVEMENT_HMAC_SECRET", None)
        env.pop("MAIN_HMAC_SECRET", None)
        env.pop("LMS_VISION_HMAC_SECRET", None)
        env.pop("VISION_GATEWAY_HMAC_SECRET", None)
        result = _run("--software", "--json", env=env, script=script)

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    bundle_check = next(item for item in payload["checks"] if item["name"] == "site_credential_bundle")
    assert bundle_check["status"] == "FAIL"
    assert "bundle" in bundle_check["message"].lower()
    secret_checks = [item for item in payload["checks"] if item["name"] in {"movement_hmac_secret", "vision_hmac_secret", "vision_gateway_hmac_secret"}]
    assert [item["status"] for item in secret_checks] == ["FAIL", "FAIL", "FAIL"]
    assert all("credential" in item["message"].lower() or "hmac" in item["message"].lower() for item in secret_checks)


def test_script_contains_no_motion_or_service_start_commands():
    text = SCRIPT.read_text(encoding="utf-8")
    prohibited = ("ros2 topic pub", "ros2 action send_goal", "docker run", "docker compose up", "systemctl start")
    assert not any(command in text for command in prohibited)
