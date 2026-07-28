import ast
from pathlib import Path

import pytest
import yaml

from nav_app.settings import LEAVE_DOCK_CLEARANCE_MARGIN_M


ROOT = Path(__file__).resolve().parents[1]
PARAM_FILES = [
    "burger_smartfactory.yaml",
    "burger_smartfactory_ekf.yaml",
    "burger_smartfactory_sim.yaml",
]


def collision_params(filename):
    data = yaml.safe_load((ROOT / "config" / "nav2" / filename).read_text())
    return data["collision_monitor"]["ros__parameters"]


@pytest.mark.parametrize("filename", PARAM_FILES)
def test_collision_monitor_is_between_nav2_and_robot_driver(filename):
    params = collision_params(filename)

    assert params["cmd_vel_in_topic"] == "cmd_vel_smoothed"
    assert params["cmd_vel_out_topic"] == "cmd_vel"
    assert params["polygons"] == ["VelocityPolygonStop", "VelocityPolygonSlow"]
    assert params["observation_sources"] == ["scan"]
    assert params["scan"]["topic"] == "/scan"
    assert params["source_timeout"] <= 0.5
    assert params["scan"]["source_timeout"] <= 0.5


@pytest.mark.parametrize("filename", PARAM_FILES)
def test_collision_monitor_stops_before_robot_contact(filename):
    params = collision_params(filename)
    stop = params["VelocityPolygonStop"]
    slow = params["VelocityPolygonSlow"]

    assert stop["type"] == "velocity_polygon"
    assert stop["action_type"] == "stop"
    assert stop["enabled"] is True
    assert stop["min_points"] <= 3
    assert slow["type"] == "velocity_polygon"
    assert slow["action_type"] == "slowdown"
    assert slow["enabled"] is True
    assert slow["slowdown_ratio"] <= 0.35

    for polygon in (stop, slow):
        assert polygon["velocity_polygons"] == [
            "rotation", "translation_forward", "translation_backward", "stopped"
        ]
        forward = ast.literal_eval(polygon["translation_forward"]["points"])
        backward = ast.literal_eval(polygon["translation_backward"]["points"])
        assert max(x for x, _ in forward) >= (0.30 if polygon is stop else 0.48)
        assert min(x for x, _ in backward) <= (
            -LEAVE_DOCK_CLEARANCE_MARGIN_M if polygon is stop else -0.24
        )
        # Straight-line protection starts at the robot center plane so an
        # obstacle in the opposite direction cannot block departure.
        assert min(x for x, _ in forward) == 0.0
        assert max(x for x, _ in backward) == 0.0
        assert polygon["translation_backward"]["linear_max"] == 0.0
        assert polygon["translation_forward"]["linear_min"] == 0.0


@pytest.mark.parametrize("filename", PARAM_FILES)
def test_velocity_smoother_preserves_reverse_commands_for_safe_departure(filename):
    data = yaml.safe_load((ROOT / "config" / "nav2" / filename).read_text())
    params = data["velocity_smoother"]["ros__parameters"]

    assert params["min_velocity"][0] < 0.0
    assert params["min_velocity"][0] == pytest.approx(-params["max_velocity"][0])


def test_project_nav_launch_includes_nav2_bringup_collision_monitor():
    launch_text = (ROOT / "launch" / "navigation2_labeled.launch.py").read_text()

    assert 'get_package_share_directory("nav2_bringup")' in launch_text
    assert '"/bringup_launch.py"' in launch_text


def test_manual_aruco_and_distance_velocity_share_collision_monitor_input():
    navigator = (ROOT / "scripts" / "logistics_navigator.py").read_text()

    assert 'self.cmd_vel_pub = self.create_publisher(TwistStamped, "/cmd_vel_nav", 10)' in navigator
    assert 'self.create_publisher(TwistStamped, "/cmd_vel", 10)' not in navigator
    assert 'get_subscriptions_info_by_topic("/cmd_vel")' in navigator
    assert navigator.count("self.cmd_vel_pub.publish(") >= 5
