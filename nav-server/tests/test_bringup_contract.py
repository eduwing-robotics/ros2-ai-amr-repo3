"""Config-driven Nav bringup contract tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN_SCRIPT = ROOT / "scripts" / "run_nav_servers.sh"


def _write_config(tmp_path: Path, robots: list[dict]) -> Path:
    config_path = tmp_path / "robots.json"
    config_path.write_text(json.dumps({"robots": robots}, indent=2), encoding="utf-8")
    return config_path


def _robot(tmp_path: Path, robot_id: str, domain: int, port: int, *, enabled: bool = True) -> dict:
    map_path = tmp_path / f"{robot_id}.yaml"
    map_path.write_text("image: map.pgm\nresolution: 0.05\norigin: [0, 0, 0]\n", encoding="utf-8")
    return {
        "robot_id": robot_id,
        "bridge_robot_id": robot_id.replace("tb3_burger_", "tb3_"),
        "ros_domain_id": domain,
        "center_domain_id": 1,
        "namespace": f"/{robot_id}",
        "teleop_command_topic": f"/mission/{robot_id}/teleop_cmd",
        "camera_topic": f"/mission/{robot_id}/camera/compressed",
        "capabilities": ["navigate"],
        "enabled": enabled,
        "active_map_yaml": str(map_path),
        "aruco_detection_topic": f"/mission/{robot_id}/aruco/detections",
        "api_port": port,
        "localization": {
            "map_id": robot_id,
            "map_metadata_identity": str(map_path),
            "base_frame": "base_footprint",
            "scan_topic": "/scan",
            "max_scan_age_sec": 1.0,
            "max_tf_age_sec": 1.0,
            "max_covariance_x": 0.25,
            "max_covariance_y": 0.25,
            "max_covariance_yaw": 0.35,
            "consecutive_samples": 3,
            "convergence_timeout_sec": 30.0,
            "persisted_seed_max_age_sec": 3600.0,
            "kidnapped_jump_distance_m": 1.5,
        },
    }


def _run(args: list[str], *, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    merged_env = os.environ.copy()
    merged_env.update(
        {
            "PYTHON_BIN": sys.executable,
            "ROS_SETUP": str(ROOT / "tests" / "missing_ros_setup_for_print_plan.bash"),
        }
    )
    if env:
        merged_env.update(env)
    return subprocess.run(
        [str(RUN_SCRIPT), *args],
        cwd=ROOT,
        env=merged_env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def test_print_plan_uses_enabled_robots_from_config_without_hardcoded_ports(tmp_path: Path):
    config = _write_config(
        tmp_path,
        [
            _robot(tmp_path, "tb3_burger_10", 10, 8100),
            _robot(tmp_path, "tb3_burger_11", 11, 8110),
            _robot(tmp_path, "tb3_burger_12", 12, 8120, enabled=False),
        ],
    )

    result = _run(["--print-plan"], env={"ROBOTS_CONFIG_PATH": str(config), "HOST": "127.0.0.1"})

    assert result.returncode == 0, result.stderr
    plan = json.loads(result.stdout)
    assert [item["robot_id"] for item in plan["robots"]] == ["tb3_burger_10", "tb3_burger_11"]
    assert [item["ros_domain_id"] for item in plan["robots"]] == [10, 11]
    assert [item["nav_local_domain_id"] for item in plan["robots"]] == [10, 11]
    assert [item["api_port"] for item in plan["robots"]] == [8100, 8110]
    assert all(Path(item["active_map_yaml"]).is_file() for item in plan["robots"])
    assert plan["python_bin"] == sys.executable
    assert plan["host"] == "127.0.0.1"


def test_repository_plan_preserves_robot_ownership_on_confirmed_map():
    result = _run(["--print-plan"])

    assert result.returncode == 0, result.stderr
    plan = {robot["robot_id"]: robot for robot in json.loads(result.stdout)["robots"]}
    robot1 = plan["tb3_burger_01"]
    robot2 = plan["tb3_burger_02"]
    assert (robot1["ros_domain_id"], robot1["nav_local_domain_id"], robot1["api_port"]) == (2, 42, 8001)
    assert (robot2["ros_domain_id"], robot2["nav_local_domain_id"], robot2["api_port"]) == (5, 5, 8002)
    expected_map = (ROOT / "map" / "robot2_map.yaml").resolve()
    assert Path(robot1["active_map_yaml"]).resolve() == expected_map
    assert Path(robot2["active_map_yaml"]).resolve() == expected_map


def test_print_plan_fails_fast_on_duplicate_ports(tmp_path: Path):
    config = _write_config(
        tmp_path,
        [
            _robot(tmp_path, "tb3_burger_20", 20, 8200),
            _robot(tmp_path, "tb3_burger_21", 21, 8200),
        ],
    )

    result = _run(["--print-plan"], env={"ROBOTS_CONFIG_PATH": str(config)})

    assert result.returncode != 0
    assert "api_port duplicate" in result.stderr


def test_check_mode_runs_preflight_without_starting_uvicorn(tmp_path: Path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    ros2 = fake_bin / "ros2"
    ros2.write_text("#!/usr/bin/env bash\necho fake ros2\n", encoding="utf-8")
    ros2.chmod(0o755)
    ros_setup = tmp_path / "setup.bash"
    ros_setup.write_text(f'export PATH="{fake_bin}:$PATH"\n', encoding="utf-8")

    result = _run(["--check"], env={"ROS_SETUP": str(ros_setup)})

    assert result.returncode == 0, result.stderr
    assert "preflight OK" in result.stdout
    assert "uvicorn" not in result.stdout.lower()


def test_shell_script_has_no_legacy_hardcoded_topology_or_pythonpath_injection():
    script = RUN_SCRIPT.read_text(encoding="utf-8")

    assert "TB3_1_PORT" not in script
    assert "TB3_2_PORT" not in script
    assert "VENV_SITE_PACKAGES" not in script
    assert "PYTHONPATH" not in script
    assert 'start_nav_server "tb3_burger_01"' not in script
    assert 'start_nav_server "tb3_burger_02"' not in script
    assert 'RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"' in script
    assert 'source "$SCRIPT_DIR/configure_cyclonedds_lan.sh"' in script
    assert 'source "$SCRIPT_DIR/configure_cyclonedds_local_domain.sh"' in script


def test_nav2_helper_defaults_to_confirmed_map_and_auto_pose_has_no_stale_defaults():
    helper = (ROOT / "scripts" / "run_nav2_with_initial_pose.sh").read_text(encoding="utf-8")
    nav_ops = (ROOT / "scripts" / "nav_ops.sh").read_text(encoding="utf-8")

    assert 'MAP_YAML="${MAP_YAML:-$ROOT/map/robot2_map.yaml}"' in helper
    assert "map/robot1_map.yaml" not in helper
    assert "NAV2_INITIAL_X:-0.066" not in nav_ops
    assert "NAV2_INITIAL_Y:-0.402" not in nav_ops
    assert "NAV2_INITIAL_YAW:--0.02" not in nav_ops
    for variable in ("NAV2_INITIAL_X", "NAV2_INITIAL_Y", "NAV2_INITIAL_YAW"):
        assert f"${{{variable}:?" in nav_ops
    assert "wait_for_automatic_localization" in helper
    assert "LOCALIZATION_FAILED" in helper
    assert helper.index("wait_for_automatic_localization") < helper.index("navigation-ready")
    assert "manage_nodes" not in helper
    start_all = (ROOT / "scripts" / "start_all_tb3_2.sh").read_text(encoding="utf-8")
    assert '--x "$INIT_X"' not in start_all
    assert '--y "$INIT_Y"' not in start_all
    assert '--yaw "$INIT_YAW"' not in start_all
