from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
def test_robot_topic_probe_uses_non_blocking_publisher_counts():
    script = (ROOT / "scripts/wait_for_robot_topics.sh").read_text()

    assert "ros2 topic info" in script
    assert "Publisher count:" in script
    assert "timeout --kill-after=2" in script
    assert "topic echo /odom" not in script


def test_robot2_pane_wrapper_survives_exec_commands():
    script = (ROOT / "scripts/start_all_tb3_2.sh").read_text()

    wrapper_start = script.index("add_pane()")
    wrapper_end = script.index('if [[ "$WITH_ROBOT"', wrapper_start)
    wrapper = script[wrapper_start:wrapper_end]
    assert "printf '(\\n'" in wrapper
    assert "printf ')\\n'" in wrapper


def test_nav2_uses_internal_lifecycle_autostart():
    script = (ROOT / "scripts/run_nav2_with_initial_pose.sh").read_text()

    assert "autostart:=false" not in script
    assert "/lifecycle_manager_localization/manage_nodes" not in script
    assert 'map:="$MAP_YAML"' in script


def test_nav2_waits_for_robot_topics_instead_of_starting_blank():
    script = (ROOT / "scripts/start_all_tb3_2.sh").read_text()

    command_start = script.index("cmd_nav2_rviz()")
    command_end = script.index("cmd_detector2()", command_start)
    command = script[command_start:command_end]
    assert "until '$SCRIPT_DIR/wait_for_robot_topics.sh'" in command
    assert "WARNING: odom/scan 미수신 — Nav2 계속 시도" not in command


def test_robot2_defaults_to_wheel_odom_tf():
    script = (ROOT / "scripts/start_all_tb3_2.sh").read_text()

    assert 'WITH_EKF="${WITH_EKF:-0}"' in script
    assert 'WITH_EKF="${WITH_EKF:-1}"' not in script


def test_robot_bringup_has_nav_pc_static_peer():
    script = (ROOT / "scripts/start_all_tb3_2.sh").read_text()

    bringup_start = script.index("ssh_robot_bringup_body()")
    bringup_end = script.index("ssh_robot_camera_body()", bringup_start)
