from unittest.mock import MagicMock

from nav_app.runtime import runtime
from nav_app.services import robot_context


def test_ekf_cmd_vel_subscription_does_not_make_off_robot_online(monkeypatch):
    navigator = MagicMock()
    navigator.cmd_vel_subscribers.return_value = [
        {"node_name": "ekf_filter_node", "node_namespace": "/", "topic_type": "geometry_msgs/msg/TwistStamped"}
    ]
    navigator.topic_publishers.return_value = []
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(runtime, "mission_manager", MagicMock(dry_run=False))
    monkeypatch.setattr(robot_context, "is_simulation_mode", lambda: False)

    assert robot_context.active_robot_online() is False


def test_robot_online_requires_odom_and_scan_hardware_publishers(monkeypatch):
    navigator = MagicMock()
    navigator.topic_publishers.side_effect = lambda topic: (
        [{"node_name": "turtlebot3_node"}] if topic == "/odom" else [{"node_name": "lds_laser_publisher"}]
    )
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(runtime, "mission_manager", MagicMock(dry_run=False))
    monkeypatch.setattr(robot_context, "is_simulation_mode", lambda: False)

    assert robot_context.active_robot_online() is True
