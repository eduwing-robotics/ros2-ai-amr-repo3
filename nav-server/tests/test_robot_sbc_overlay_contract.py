"""Executable fail-closed contracts for robot SBC workspace overlays."""

from __future__ import annotations

import os
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
CAMERA_SCRIPT = ROOT / "scripts" / "robot_sbc" / "start_camera.sh"
LIFT_SCRIPT = ROOT / "scripts" / "robot_sbc" / "start_lift_bridge.sh"


def _run(script: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(script)],
        cwd=ROOT,
        env=os.environ | env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("script", "setup_variable"),
    [
        (CAMERA_SCRIPT, "WS_SETUP"),
        (LIFT_SCRIPT, "LIFT_WS_SETUP"),
    ],
)
def test_robot_sbc_scripts_require_explicit_overlay_environment(script: Path, setup_variable: str) -> None:
    result = _run(script, {setup_variable: ""})

    assert result.returncode != 0
    assert f"{setup_variable} must point" in result.stderr


@pytest.mark.parametrize(
    ("script", "setup_variable", "error"),
    [
        (CAMERA_SCRIPT, "WS_SETUP", "TurtleBot3 workspace overlay not found"),
        (LIFT_SCRIPT, "LIFT_WS_SETUP", "lift workspace overlay not found"),
    ],
)
def test_robot_sbc_scripts_fail_when_explicit_overlay_is_missing(
    script: Path, setup_variable: str, error: str, tmp_path: Path
) -> None:
    result = _run(script, {setup_variable: str(tmp_path / "missing-setup.bash")})

    assert result.returncode == 1
    assert error in result.stderr


def test_camera_sources_a_valid_explicit_overlay(tmp_path: Path) -> None:
    marker = tmp_path / "camera-overlay-sourced"
    setup = tmp_path / "camera-setup.bash"
    setup.write_text('printf sourced > "$OVERLAY_MARKER"\n', encoding="utf-8")

    result = _run(
        CAMERA_SCRIPT,
        {
            "WS_SETUP": str(setup),
            "OVERLAY_MARKER": str(marker),
            "BRINGUP_WAIT_SEC": "0",
            "CAMERA_BACKEND": "legacy",
            "CAMERA_START_RETRIES": "0",
        },
    )

    assert result.returncode == 1
    assert marker.read_text(encoding="utf-8") == "sourced"


def test_lift_sources_a_valid_explicit_overlay_before_running_bridge(tmp_path: Path) -> None:
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ros2 = fake_bin / "ros2"
    ros2.write_text(
        '#!/usr/bin/env bash\n'
        '[[ "${OVERLAY_SOURCED:-}" == "1" ]]\n'
        'printf "%s\\n" "$*"\n',
        encoding="utf-8",
    )
    ros2.chmod(0o755)
    setup = tmp_path / "lift-setup.bash"
    setup.write_text(
        'export OVERLAY_SOURCED=1\n'
        'export PATH="$FAKE_BIN:$PATH"\n',
        encoding="utf-8",
    )

    result = _run(
        LIFT_SCRIPT,
        {
            "LIFT_WS_SETUP": str(setup),
            "FAKE_BIN": str(fake_bin),
            "LIFT_SERIAL_PORT": "/dev/ttyACM0",
        },
    )

    assert result.returncode == 0, result.stderr
    assert "run lift_bridge lift_bridge --ros-args -p port:=/dev/ttyACM0" in result.stdout
