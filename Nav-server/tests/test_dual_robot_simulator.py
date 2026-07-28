import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SIMULATOR = ROOT / "Simulator"
SCRIPTS = SIMULATOR / "scripts"
sys.path.insert(0, str(SCRIPTS))

from dual_robot_geometry import load_layout, marker_distance_from_progress
from generate_dual_robot_assets import _bridge_yaml
from run_dual_robot_safety_scenarios import capture_final_approach_poses, command_payload


def test_dual_layout_starts_at_20cm_and_reverses_to_configured_40cm_approach():
    layout = load_layout()
    assert layout["hold_marker_distance_m"] == 0.20
    assert layout["approach_marker_distance_m"] == 0.40
    assert layout["reverse_distance_m"] == 0.20
    assert len(layout["robots"]) == 2
    assert {robot["ros_domain_id"] for robot in layout["robots"]} == {2, 5}
    assert {robot["api_port"] for robot in layout["robots"]} == {8001, 8002}
    for robot in layout["robots"]:
        hold = robot["hold_pose"]
        approach = robot["approach_pose"]
        assert math.hypot(hold["x"] - approach["x"], hold["y"] - approach["y"]) == pytest.approx(0.20)
        assert hold["yaw"] == approach["yaw"]


def test_marker_oracle_reports_20_to_40cm_progress():
    assert marker_distance_from_progress(0.20, 0.0) == 0.20
    assert marker_distance_from_progress(0.20, 0.20) == 0.40


def test_traffic_scenario_holds_corridor_through_nav_and_wait():
    layout = load_layout()
    for robot in layout["robots"]:
        payload = command_payload(robot, "test-command")
        assert [step["action"] for step in payload["steps"]] == ["leave_dock", "nav2_pose", "wait"]
        goal = payload["steps"][1]["payload"]["goal"]
        assert goal["waypoint"] == robot["approach_waypoint"]
        assert goal["x"] == robot["approach_pose"]["x"]
        assert goal["y"] == robot["approach_pose"]["y"]
        assert goal["soft_xy_tolerance_m"] == 0.08
        assert payload["steps"][2]["duration"] == 2.0


def test_final_approach_evidence_uses_settled_health_map_pose(monkeypatch):
    layout = load_layout()
    health_by_port = {
        8001: {"localized": True, "pose": {"x": 0.527, "y": 0.016}},
        8002: {"localized": True, "pose": {"x": 0.816, "y": -0.004}},
    }

    def fake_request(url, payload=None, timeout=5.0):
        del payload, timeout
        port = int(url.split(":")[2].split("/")[0])
        return health_by_port[port]

    monkeypatch.setattr(
        "run_dual_robot_safety_scenarios.request_json", fake_request
    )
    snapshots = capture_final_approach_poses(layout, timeout_sec=0.1)
    assert snapshots["tb3_1"]["approach_pose_error_m"] == pytest.approx(0.01)
    assert snapshots["tb3_2"]["approach_pose_error_m"] == pytest.approx(0.01)
    assert all(item["tolerance_m"] == 0.05 for item in snapshots.values())
    errors = [item["approach_pose_error_m"] for item in snapshots.values()]
    assert max(errors) - min(errors) <= 0.03


def test_generated_bridges_isolate_gazebo_topics_but_keep_root_ros_contract():
    gazebo_scan_topics = set()
    for name in ("tb3_1", "tb3_2"):
        text = _bridge_yaml(name)
        assert f"gz_topic_name: \"/{name}/scan\"" in text
        assert "ros_topic_name: \"scan\"" in text
        assert f"gz_topic_name: \"/{name}/cmd_vel\"" in text
        assert "ros_topic_name: \"cmd_vel\"" in text
        gazebo_scan_topics.add(f"/{name}/scan")
    assert gazebo_scan_topics == {"/tb3_1/scan", "/tb3_2/scan"}


def test_sim_stack_uses_sim_clock_xvfb_and_collision_monitor_chain():
    start = (SCRIPTS / "start_dual_robot_standby.sh").read_text()
    navigator = (ROOT / "scripts" / "logistics_navigator.py").read_text()
    probe = (SCRIPTS / "sim_collision_stop_probe.py").read_text()
    initialpose = (SCRIPTS / "pub_initialpose.sh").read_text()
    launch = (SIMULATOR / "launch" / "dual_robot_warehouse.launch.py").read_text()
    assert "NAV_USE_SIM_TIME=1" in start
    assert "GAZEBO_USE_XVFB" in start
    assert 'export GZ_PARTITION="${DUAL_SIM_GZ_PARTITION:-nav_server_dual_$$}"' in start
    assert 'PARTITION_FILE="$GENERATED/gz_partition"' in start
    assert "Gazebo transport partition: $GZ_PARTITION" in start
    assert 'grep -zFqx -- "GZ_PARTITION=$partition"' in start
    assert 'kill -TERM "$pid"' in start
    assert 'kill -TERM -- "-$pid"' not in start
    assert "now_sec = float(self.get_clock().now().nanoseconds)" in navigator
    assert '"/cmd_vel_nav"' in probe
    assert '"/cmd_vel_smoothed"' in probe
    assert '"/cmd_vel"' in probe
    assert "twist.twist.angular.z = 0.0" in navigator
    assert "max_abs_angular_z_rps" in (
        SCRIPTS / "sim_standby_marker_oracle.py"
    ).read_text()
    assert "INITIALPOSE_XY_VARIANCE:-0.0004" in initialpose
    assert "GAZEBO_HEADLESS_RENDERING" in launch


def test_sim_amcl_updates_within_the_20cm_standby_leave():
    params = (ROOT / "config" / "nav2" / "burger_smartfactory_sim.yaml").read_text()
    assert "update_min_d: 0.03" in params
    assert "update_min_a: 0.03" in params
