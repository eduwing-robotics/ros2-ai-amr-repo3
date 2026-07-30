"""Credential-handling contract tests for the tb3_2 startup script."""

from __future__ import annotations

import os
import secrets
import subprocess
from pathlib import Path

from tests.support import NAV_SERVER_ROOT

ROOT = NAV_SERVER_ROOT
SCRIPT = ROOT / "scripts" / "start_all_tb3_2.sh"


def _fake_tmux(tmp_path: Path) -> Path:
    tmux = tmp_path / "tmux"
    tmux.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ $1 == has-session ]]; then exit 1; fi\n"
        "exit 0\n",
        encoding="utf-8",
    )
    tmux.chmod(0o755)
    return tmux


def _fake_robot_commands(bin_dir: Path) -> None:
    ssh = bin_dir / "ssh"
    ssh.write_text(
        "#!/usr/bin/env bash\n"
        "if [[ -n ${FAKE_SSH_ARGS:-} ]]; then printf '%s\\n' \"$@\" >> \"$FAKE_SSH_ARGS\"; fi\n"
        "if [[ $* == *'echo ssh_ok'* ]]; then echo ssh_ok; fi\n"
        "cat >/dev/null\n"
        "exit 0\n",
        encoding="utf-8",
    )
    ssh.chmod(0o755)
    for name in ("scp", "sleep", "pkill"):
        command = bin_dir / name
        command.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        command.chmod(0o755)


def _run_tmux_plan(
    tmp_path: Path,
    *,
    password: str | None,
    sshpass_available: bool,
    local_env_file: Path | None = None,
    extra_env: dict[str, str] | None = None,
    runtime_hardware_defaults: bool = True,
) -> subprocess.CompletedProcess[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_tmux(bin_dir)
    _fake_robot_commands(bin_dir)
    if sshpass_available:
        sshpass = bin_dir / "sshpass"
        sshpass.write_text(
            "#!/usr/bin/env bash\n"
            "[[ $1 == -e ]] && shift\n"
            "exec \"$@\"\n",
            encoding="utf-8",
        )
        sshpass.chmod(0o755)

    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    env = os.environ.copy()
    env.update({"PATH": f"{bin_dir}:{env['PATH']}", "LOG_DIR": str(log_dir)})
    if runtime_hardware_defaults:
        env.update(
            {
                "ROBOT_WS_SETUP": "/opt/tb3/install/setup.bash",
                "WITH_LIFT": "0",
            }
        )
    if local_env_file is not None:
        env["NAV_LOCAL_ENV_FILE"] = str(local_env_file)
    if extra_env:
        env.update(extra_env)
    if password is None:
        env.pop("ROBOT_PW", None)
    else:
        env["ROBOT_PW"] = password

    return subprocess.run(
        ["bash", str(SCRIPT), "tmux"],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_default_tracked_hardware_config_is_loaded_without_printing_password(tmp_path: Path) -> None:
    result = _run_tmux_plan(
        tmp_path,
        password=None,
        sshpass_available=True,
        extra_env={"WITH_LIFT": "1"},
        runtime_hardware_defaults=False,
    )

    assert result.returncode == 0, result.stderr
    pane = (tmp_path / "logs" / "pane_robot-bringup.sh").read_text(encoding="utf-8")
    output = result.stdout + result.stderr + pane
    assert "musk@192.168.30.102" in pane
    assert "/home/musk/turtlebot3_ws/install/setup.bash" in pane
    assert "/home/musk/lift_project/ros2_ws/install/setup.bash" in (
        tmp_path / "logs" / "pane_robot-lift.sh"
    ).read_text(encoding="utf-8")
    assert "1234" not in output


def test_process_environment_overrides_local_hardware_file(tmp_path: Path) -> None:
    local_env = tmp_path / "local-hardware.env"
    local_env.write_text(
        "ROBOT_SSH=file-user@file-host\n"
        "ROBOT_PW=file-password\n"
        "ROBOT_WS_SETUP=/file/tb3/setup.bash\n",
        encoding="utf-8",
    )
    password = f"process-{secrets.token_urlsafe(18)}"
    result = _run_tmux_plan(
        tmp_path,
        password=password,
        sshpass_available=True,
        local_env_file=local_env,
        extra_env={
            "ROBOT_SSH": "process-user@process-host",
            "ROBOT_WS_SETUP": "/process/tb3/setup.bash",
        },
    )

    assert result.returncode == 0, result.stderr
    pane = (tmp_path / "logs" / "pane_robot-bringup.sh").read_text(encoding="utf-8")
    combined_output = result.stdout + result.stderr + pane
    assert "process-user@process-host" in pane
    assert "/process/tb3/setup.bash" in pane
    assert "file-user@file-host" not in pane
    assert "/file/tb3/setup.bash" not in pane
    assert password not in combined_output
    assert "file-password" not in combined_output


def test_local_hardware_file_is_parsed_as_data_not_shell_code(tmp_path: Path) -> None:
    marker = tmp_path / "executed"
    local_env = tmp_path / "local-hardware.env"
    local_env.write_text(
        "ROBOT_SSH=file-user@file-host\n"
        f"ROBOT_PW=$(touch {marker})\n"
        "ROBOT_WS_SETUP=/file/tb3/setup.bash\n",
        encoding="utf-8",
    )

    result = _run_tmux_plan(
        tmp_path,
        password=None,
        sshpass_available=True,
        local_env_file=local_env,
    )

    assert result.returncode == 0, result.stderr
    assert not marker.exists()


def test_ssh_keys_are_used_when_robot_password_is_not_explicitly_supplied(tmp_path: Path) -> None:
    result = _run_tmux_plan(
        tmp_path,
        password="",
        sshpass_available=True,
    )

    assert result.returncode == 0, result.stderr
    pane = (tmp_path / "logs" / "pane_robot-bringup.sh").read_text(encoding="utf-8")
    assert "sshpass" not in pane
    assert "ssh -o StrictHostKeyChecking=accept-new" in pane


def test_explicit_password_uses_sshpass_without_exposing_the_secret(tmp_path: Path) -> None:
    password = f"secret-{secrets.token_urlsafe(24)}"
    result = _run_tmux_plan(tmp_path, password=password, sshpass_available=True)

    assert result.returncode == 0, result.stderr
    pane = (tmp_path / "logs" / "pane_robot-bringup.sh").read_text(encoding="utf-8")
    source = SCRIPT.read_text(encoding="utf-8")
    combined_output = result.stdout + result.stderr + pane
    assert "sshpass -e ssh" in pane
    assert password not in combined_output
    assert password not in source
    helper = (ROOT / "scripts" / "lib" / "local_hardware.sh").read_text(encoding="utf-8")
    assert 'ROBOT_PW="${ROBOT_PW:-}"' in helper
    assert "sshpass -p" not in source
    assert "SSH_ASKPASS" not in source


def test_pane_value_classes_are_quoted_before_execution(tmp_path: Path) -> None:
    marker = tmp_path / "injected"
    payload = f"; touch {marker}; #"
    result = _run_tmux_plan(
        tmp_path,
        password="",
        sshpass_available=False,
        extra_env={
            "DOMAIN": f"5{payload}",
            "DISPLAY": f":1{payload}",
            "MAP": f"/map{payload}",
            "INIT_X": f"0.0{payload}",
            "INIT_Y": f"0.1{payload}",
            "INIT_YAW": f"0.2{payload}",
            "ROBOT_TOPIC_WAIT_SEC": f"1{payload}",
            "STATUS_DELAY_SEC": f"1{payload}",
            "WITH_EKF": f"0{payload}",
            "WITH_LIFT": "0",
        },
    )

    assert result.returncode == 0, result.stderr
    for pane in ("nav2-rviz", "status"):
        pane_path = tmp_path / "logs" / f"pane_{pane}.sh"
        syntax = subprocess.run(["bash", "-n", str(pane_path)], check=False)
        assert syntax.returncode == 0
        subprocess.run(
            ["timeout", "3", "bash", str(pane_path)],
            cwd=ROOT,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    assert not marker.exists()


def test_named_launchers_use_shared_local_hardware_config_without_password_argv() -> None:
    scripts = (
        ROOT / "scripts" / "start_all_tb3_2.sh",
        ROOT / "scripts" / "restart_robot_camera_tb3_2.sh",
        ROOT / "scripts" / "scenarios" / "field" / "run_center_slot_l2_lift_test.sh",
    )
    approved_config = ROOT / "config" / "local-hardware.env"

    for script in scripts:
        source = script.read_text(encoding="utf-8")
        assert 'source "$SCRIPT_DIR/lib/local_hardware.sh"' in source
        assert "sshpass -p" not in source
        assert 'ROBOT_PW="${ROBOT_PW:-1234}"' not in source
    config = approved_config.read_text(encoding="utf-8")
    password = next(line.split("=", 1)[1] for line in config.splitlines() if line.startswith("ROBOT_PW="))
    assert password
    for path in (*scripts, ROOT / "worklog" / "commissioning" / "TB3_2_VALIDATION_STATUS_2026-07-03.md"):
        assert password not in path.read_text(encoding="utf-8")


def test_password_is_not_used_when_sshpass_is_unavailable(tmp_path: Path) -> None:
    password = f"secret-{secrets.token_urlsafe(24)}"
    result = _run_tmux_plan(tmp_path, password=password, sshpass_available=False)

    assert result.returncode == 0, result.stderr
    pane = (tmp_path / "logs" / "pane_robot-bringup.sh").read_text(encoding="utf-8")
    assert "sshpass" not in pane
    assert password not in result.stdout + result.stderr + pane
    assert "sshpass is unavailable; using SSH key authentication" in result.stdout


def test_generated_robot_panes_preserve_metacharacters_as_literal_arguments(tmp_path: Path) -> None:
    marker = tmp_path / "injected"
    ssh_args = tmp_path / "ssh-args.txt"
    payload = f"; touch {marker}; #"
    result = _run_tmux_plan(
        tmp_path,
        password=None,
        sshpass_available=False,
        extra_env={
            "ROBOT_SSH": f"robot{payload}",
            "ROBOT_WS_SETUP": f"/overlay{payload}",
            "LIFT_WS_SETUP": f"/lift-overlay{payload}",
            "LIFT_SERIAL_PORT": f"/dev/ttyUSB0{payload}",
            "LIFT_BRIDGE_PKG": f"lift_bridge{payload}",
            "CAMERA_LAUNCH": f"camera.launch.py{payload}",
            "WITH_LIFT": "1",
            "FAKE_SSH_ARGS": str(ssh_args),
        },
    )

    assert result.returncode == 0, result.stderr
    for pane in ("robot-bringup", "robot-camera", "robot-lift"):
        pane_result = subprocess.run(
            ["bash", str(tmp_path / "logs" / f"pane_{pane}.sh")],
            cwd=ROOT,
            env={**os.environ, "PATH": f"{tmp_path / 'bin'}:{os.environ['PATH']}", "FAKE_SSH_ARGS": str(ssh_args)},
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert pane_result.returncode == 0, pane_result.stderr

    assert not marker.exists()
    arguments = ssh_args.read_text(encoding="utf-8")
    assert f"robot{payload}" in arguments
    assert f"WS_SETUP=/overlay{payload}" in arguments
    assert f"LIFT_WS_SETUP=/lift-overlay{payload}" in arguments
    assert f"LIFT_SERIAL_PORT=/dev/ttyUSB0{payload}" in arguments
    assert f"LIFT_BRIDGE_PKG=lift_bridge{payload}" in arguments
    assert f"CAMERA_LAUNCH=camera.launch.py{payload}" in arguments


def test_robot_preflight_runs_once_for_each_start_mode(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_tmux(bin_dir)
    _fake_robot_commands(bin_dir)
    for name in ("terminator", "gnome-terminal"):
        command = bin_dir / name
        command.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        command.chmod(0o755)

    for mode in ("tmux", "windows", "terminator"):
        ssh_args = tmp_path / f"{mode}-ssh-args.txt"
        log_dir = tmp_path / f"{mode}-logs"
        log_dir.mkdir()
        result = subprocess.run(
            ["bash", str(SCRIPT), mode],
            cwd=ROOT,
            env={
                **os.environ,
                "PATH": f"{bin_dir}:{os.environ['PATH']}",
                "LOG_DIR": str(log_dir),
                "ROBOT_WS_SETUP": "/opt/tb3/install/setup.bash",
                "WITH_LIFT": "0",
                "FAKE_SSH_ARGS": str(ssh_args),
            },
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert ssh_args.read_text(encoding="utf-8").count("echo ssh_ok") == 1


def test_without_robot_skips_preflight_and_status_stop_remain_local(tmp_path: Path) -> None:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _fake_tmux(bin_dir)
    _fake_robot_commands(bin_dir)
    (bin_dir / "terminator").write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    (bin_dir / "terminator").chmod(0o755)
    (bin_dir / "ros2").write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
    (bin_dir / "ros2").chmod(0o755)
    ssh_args = tmp_path / "ssh-args.txt"
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    base_env = {
        **os.environ,
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "LOG_DIR": str(log_dir),
        "WITH_ROBOT": "0",
        "FAKE_SSH_ARGS": str(ssh_args),
    }

    for mode in ("tmux", "windows", "terminator"):
        terminal = bin_dir / "gnome-terminal"
        terminal.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
        terminal.chmod(0o755)
        result = subprocess.run(
            ["bash", str(SCRIPT), mode], cwd=ROOT, env=base_env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        assert result.returncode == 0, result.stderr

    for command in ("status", "stop"):
        result = subprocess.run(
            ["bash", str(SCRIPT), command], cwd=ROOT, env=base_env, text=True,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
        )
        assert result.returncode == 0, result.stderr
    assert not ssh_args.exists()
