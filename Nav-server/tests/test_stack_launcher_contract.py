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


def test_detector_camera_probe_runs_inside_generated_pane():
    script = (ROOT / "scripts/start_all_tb3_2.sh").read_text()

    command_start = script.index("cmd_detector2()")
    command_end = script.index("cmd_nav_servers()", command_start)
    command = script[command_start:command_end]
    assert '\\$(timeout --signal=INT --kill-after=2s 4s ros2 topic info /camera/image_raw/compressed' in command
    assert "{print \\$3}" in command
    assert 'until [[ "$(timeout ' not in command


def test_nav2_startup_activates_once_after_nodes_are_inactive():
    script = (ROOT / "scripts/run_nav2_with_initial_pose.sh").read_text()

    assert script.count("/lifecycle_manager_navigation/manage_nodes") == 1
    assert 'ManageLifecycleNodes "{command: 3}"' not in script
    assert 'ros2 lifecycle get "/$node"' in script
    assert 'all_inactive" == "1"' in script
    assert "startup_requested=1" in script
    assert 'NAV2_AUTOSTART_GRACE_SEC="${NAV2_AUTOSTART_GRACE_SEC:-30}"' in script
    retry = script[script.index("retry_navigation_startup()"):script.index("while (($# > 0))")]
    assert retry.count('publish_initial_pose "$INITIAL_X" "$INITIAL_Y" "$INITIAL_YAW"') == 1


def test_navigation_goals_require_readiness_and_handle_rejection():
    navigator = (ROOT / "scripts/logistics_navigator.py").read_text()
    robot_context = (ROOT / "nav_app/services/robot_context.py").read_text()
    server_core = (ROOT / "nav_app/server_core.py").read_text()

    assert 'os.getenv("NAV2_SKIP_ACTIVE_WAIT", "0")' in navigator
    assert "if not self.nav.goToPose(pose):" in navigator
    assert "Nav2 goal rejected (navigation lifecycle not ready)" in navigator
    assert 'getattr(runtime.navigator, "nav2_ready", False)' in robot_context
    assert 'NAV2_REQUIRED_LIFECYCLE_NODES' in server_core
    for node in ("map_server", "amcl", "controller_server", "planner_server", "behavior_server", "bt_navigator"):
        assert f'"{node}"' in server_core
    assert "consecutive_probe_failures < 3" in server_core
    assert "runtime.nav2_readiness_stop.wait(2.0)" in server_core
    assert 'nav._waitForNodeToActivate("bt_navigator")' not in server_core
    assert "waitUntilNav2Active(" not in server_core


def test_robot_bringup_has_nav_pc_static_peer():
    script = (ROOT / "scripts/start_all_tb3_2.sh").read_text()

    bringup_start = script.index("ssh_robot_bringup_body()")
    bringup_end = script.index("ssh_robot_camera_body()", bringup_start)


def test_detector_and_relay_consume_robot_raw_compressed_camera_topic():
    runner = (ROOT / "scripts/run_pi_camera_aruco.sh").read_text()

    assert 'RAW_COMPRESSED_TOPIC="${RAW_COMPRESSED_TOPIC:-/camera/image_raw/compressed}"' in runner
    assert 'DETECTOR_IMAGE_TOPIC="${DETECTOR_IMAGE_TOPIC:-$RAW_COMPRESSED_TOPIC}"' in runner
    assert '-p "input_topic:=${DETECTOR_IMAGE_TOPIC}"' in runner
    assert 'DETECTOR_IMAGE_TOPIC="${DETECTOR_IMAGE_TOPIC:-$CAMERA_TOPIC}"' not in runner

def test_robot1_launcher_stays_scoped_and_does_not_mask_failed_panes():
    script = (ROOT / "scripts/start_all_tb3_1.sh").read_text()

    status_start = script.index("status_stack()")
    status_end = script.index("case ", status_start)
    status = script[status_start:status_end]
    assert "for p in 8001 8002" not in status
    assert "for p in 8001" in status

    pane_check_start = script.index("verify_terminator_panes()")
    pane_check_end = script.index("local tlog=", pane_check_start)
    pane_check = script[pane_check_start:pane_check_end]
    assert "detector1_fallback.log" not in pane_check
    assert "nohup bash" not in pane_check

def test_robot1_uses_verified_five_centimeter_aruco_markers():
    script = (ROOT / "scripts/start_all_tb3_1.sh").read_text()

    assert "export ARUCO_MARKER_SIZE_M=0.05" in script
    assert "export ARUCO_MARKER_SIZE_M=0.04" not in script
