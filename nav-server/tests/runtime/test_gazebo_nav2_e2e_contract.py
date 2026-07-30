"""Static contract for the opt-in headless Gazebo/Nav2 acceptance harness."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tests.support import NAV_SERVER_ROOT


ROOT = NAV_SERVER_ROOT
SCRIPT = ROOT / "scripts" / "verify_gazebo_nav2_e2e.sh"
CLIENT = ROOT / "scripts" / "verify_gazebo_nav2_e2e_client.py"
RUNBOOK = ROOT / "docs" / "runbook" / "OPERATIONS.md"


def test_headless_gazebo_acceptance_has_safe_orchestration_contract():
    script = SCRIPT.read_text(encoding="utf-8")
    client = CLIENT.read_text(encoding="utf-8")
    main = client[client.index("def main()") :]
    legacy_home = "/" + "home" + "/" + "lucas"

    assert "set -euo pipefail" in script
    assert "mktemp -d /tmp/gazebo-nav2-e2e." in script
    assert "rm -rf \"$RUN_DIR\"" in script
    assert 'setsid env TMPDIR="$RUN_DIR" ros2 launch' in script
    assert 'kill -TERM -- "-$LAUNCH_PID"' in script
    assert "E2E_ROS_DOMAIN_ID" in script
    assert "ros2 pkg prefix --share" in script
    assert "nav2_bringup nav2_minimal_tb3_sim ros_gz_sim" in script
    assert "ros2 launch nav2_bringup tb3_simulation_launch.py" in script
    assert "headless:=True use_rviz:=False" in script
    assert "--check" in script and "--help" in script
    assert "FINAL_ERROR_THRESHOLD_M" in script
    assert legacy_home not in script
    assert "lifecycle_manager_localization/is_active" in client
    assert "lifecycle_manager_navigation/is_active" in client
    assert main.index("node.localization_lifecycle") < main.index("wait_for_localization(node")
    assert main.index("wait_for_localization(node") < main.index("node.navigation_lifecycle")
    assert "PoseWithCovarianceStamped" in client
    assert "MAX_COVARIANCE_X = 0.25" in client
    assert "MAX_COVARIANCE_Y = 0.25" in client
    assert "MAX_COVARIANCE_YAW = 0.35" in client
    assert "REQUIRED_CONSECUTIVE_LOCALIZED_SAMPLES = 3" in client
    assert "GoalStatus.STATUS_SUCCEEDED" in client
    assert '"status_name": "SUCCEEDED"' in client
    assert "feedback_callback=node.navigation_feedback" in client
    assert "NavigateToPose SUCCEEDED but" in client
    assert 'lookup_transform(\n                "map",\n                "base_link"' in client
    assert '"final_pose_source": "map_to_base_link_tf"' in client
    assert "final_error_m" in client
    assert "makes no\nclaim about ArUco, lift" in script


def test_headless_gazebo_acceptance_help_and_python_syntax_are_available():
    help_result = subprocess.run(
        [str(SCRIPT), "--help"],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert help_result.returncode == 0, help_result.stderr
    assert "NavigateToPose" in help_result.stdout

    syntax_result = subprocess.run(
        [sys.executable, "-m", "py_compile", str(CLIENT)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert syntax_result.returncode == 0, syntax_result.stderr


def test_gazebo_runbook_documents_the_current_headless_acceptance_command():
    runbook = RUNBOOK.read_text(encoding="utf-8")
    legacy_home = "/" + "home" + "/" + "lucas"
    assert "verify_gazebo_nav2_e2e.sh --check" in runbook
    assert "verify_gazebo_nav2_e2e.sh" in runbook
    assert "nav2_minimal_tb3_sim" in runbook
    assert legacy_home not in runbook
    assert "lift" in runbook.lower()
