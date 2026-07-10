"""Black-box regression tests for the read-only operator preflight."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "operator-preflight.sh"


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


def _run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(SCRIPT), *args], cwd=ROOT, env=env, text=True, capture_output=True, check=False
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
        movement_secret = "operator-preflight-movement-secret-must-not-appear"
        vision_secret = "operator-preflight-vision-secret-must-not-appear"
        gateway_secret = "operator-preflight-gateway-secret-must-not-appear"
        env["NAV_MAIN_HMAC_SECRET"] = movement_secret
        env["MAIN_HMAC_SECRET"] = vision_secret
        env["VISION_GATEWAY_HMAC_SECRET"] = gateway_secret
        result = _run("--software", "--json", env=env)

    assert result.returncode == 0, result.stderr
    assert movement_secret not in result.stdout
    assert movement_secret not in result.stderr
    assert vision_secret not in result.stdout
    assert vision_secret not in result.stderr
    assert gateway_secret not in result.stdout
    assert gateway_secret not in result.stderr
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert all("motion" not in item["message"].lower() for item in payload["checks"])


def test_software_fails_clearly_when_hmac_secrets_are_missing():
    with tempfile.TemporaryDirectory() as directory:
        env = _environment(Path(directory))
        env.pop("NAV_MAIN_HMAC_SECRET", None)
        env.pop("LMS_MOVEMENT_HMAC_SECRET", None)
        env.pop("MAIN_HMAC_SECRET", None)
        env.pop("LMS_VISION_HMAC_SECRET", None)
        env.pop("VISION_GATEWAY_HMAC_SECRET", None)
        result = _run("--software", "--json", env=env)

    assert result.returncode == 3
    payload = json.loads(result.stdout)
    secret_checks = [item for item in payload["checks"] if item["name"] in {"movement_hmac_secret", "vision_hmac_secret", "vision_gateway_hmac_secret"}]
    assert [item["status"] for item in secret_checks] == ["FAIL", "FAIL", "FAIL"]
    assert all("secret" in item["message"].lower() for item in secret_checks)


def test_script_contains_no_motion_or_service_start_commands():
    text = SCRIPT.read_text(encoding="utf-8")
    prohibited = ("ros2 topic pub", "ros2 action send_goal", "docker run", "docker compose up", "systemctl start")
    assert not any(command in text for command in prohibited)
