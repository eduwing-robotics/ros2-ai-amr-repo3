#!/usr/bin/env bash
# Convenience entry point for common Nav server / ArUco operations.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
MARKER_ID="${MARKER_ID:-0}"

usage() {
  cat <<'EOF'
Usage:
  scripts/nav_ops.sh start             # start both Movement/Nav API servers in background
  scripts/nav_ops.sh dry-run           # start both API servers in dry-run mode
  scripts/nav_ops.sh stop              # stop background Nav servers
  scripts/nav_ops.sh restart           # restart background Nav servers
  scripts/nav_ops.sh status            # HTTP/process/ROS readiness summary
  scripts/nav_ops.sh quick             # start Nav servers, then show status

  scripts/nav_ops.sh bridges           # run domain bridges in this terminal
  scripts/nav_ops.sh nav2-1            # run robot1 Nav2/RViz with automatic no-motion localization
  scripts/nav_ops.sh nav2-2            # run robot2 Nav2 with automatic no-motion localization
  scripts/nav_ops.sh detector1         # run robot1 ArUco detector in this terminal
  scripts/nav_ops.sh detector2         # run robot2 ArUco detector in this terminal
  scripts/nav_ops.sh camera1           # run robot1 Pi camera launch in this terminal
  scripts/nav_ops.sh camera2           # run robot2 Pi camera launch in this terminal

  scripts/nav_ops.sh check1            # robot1 topic/API readiness checks
  scripts/nav_ops.sh check2            # robot2 topic/API readiness checks
  scripts/test_lift_tb3_2.sh status    # lift bridge subscriber check (tb3_2)
  scripts/nav_ops.sh aruco1            # local robot1 ArUco align test, MARKER_ID=0 by default
  scripts/nav_ops.sh aruco2            # local robot2 ArUco align test, MARKER_ID=0 by default
  scripts/nav_ops.sh robot-commands    # print commands to run on TurtleBot SBCs

Common overrides:
  MARKER_ID=0
  START_CAMERA_LAUNCH=0
  ROS_SETUP=/opt/ros/jazzy/setup.bash

Typical Nav PC flow:
  scripts/nav_ops.sh start
  scripts/nav_ops.sh detector1
  scripts/nav_ops.sh status
  MARKER_ID=0 scripts/nav_ops.sh aruco1
EOF
}

source_ros() {
  if [[ ! -f "$ROS_SETUP" ]]; then
    echo "[nav_ops] missing ROS setup: $ROS_SETUP" >&2
    exit 1
  fi
  set +u
  # shellcheck source=/dev/null
  source "$ROS_SETUP"
  set -u
  export ROS_LOCALHOST_ONLY="${ROS_LOCALHOST_ONLY:-0}"
}

robot_domain() {
  case "$1" in
    1|tb3_1|tb3_burger_01) echo 2 ;;
    2|tb3_2|tb3_burger_02) echo 5 ;;
    *) echo "[nav_ops] unknown robot: $1" >&2; exit 2 ;;
  esac
}

robot_id() {
  case "$1" in
    1|tb3_1|tb3_burger_01) echo tb3_burger_01 ;;
    2|tb3_2|tb3_burger_02) echo tb3_burger_02 ;;
    *) echo "[nav_ops] unknown robot: $1" >&2; exit 2 ;;
  esac
}

base_url() {
  case "$1" in
    1|tb3_1|tb3_burger_01) echo "${TB3_1_URL:-http://127.0.0.1:8001}" ;;
    2|tb3_2|tb3_burger_02) echo "${TB3_2_URL:-http://127.0.0.1:8002}" ;;
    *) echo "[nav_ops] unknown robot: $1" >&2; exit 2 ;;
  esac
}

check_robot() {
  local robot="$1"
  local domain url
  domain="$(robot_domain "$robot")"
  url="$(base_url "$robot")"

  echo "== robot${robot} API =="
  curl -fsS --max-time 2 "$url/movement-api/v1/health" | python3 -m json.tool || true

  echo
  echo "== robot${robot} ROS_DOMAIN_ID=${domain} topics =="
  source_ros
  ROS_DOMAIN_ID="$domain" timeout 3 ros2 topic info /cmd_vel -v || true
  echo
  ROS_DOMAIN_ID="$domain" timeout 3 ros2 topic info /scan -v || true
  echo
  ROS_DOMAIN_ID="$domain" timeout 3 ros2 topic info /camera/image_raw/compressed -v || true
  echo
  echo "== robot${robot} lift topics (ROS_DOMAIN_ID=${domain}) =="
  for topic in /lift/cmd_move /lift/position /lift/direction /lift/limit_lower; do
    ROS_DOMAIN_ID="$domain" timeout 3 ros2 topic info "$topic" -v 2>/dev/null || echo "$topic: (none)"
    echo
  done
}

run_camera() {
  local robot="$1"
  local domain
  domain="$(robot_domain "$robot")"
  source_ros
  export ROS_DOMAIN_ID="$domain"
  echo "[nav_ops] starting Pi camera for robot${robot} in ROS_DOMAIN_ID=$ROS_DOMAIN_ID"
  exec ros2 launch turtlebot3_bringup camera_low_bandwidth.launch.py
}

cmd="${1:-help}"
case "$cmd" in
  start|dry-run|stop|restart|status)
    exec "$SCRIPT_DIR/start_nav_servers.sh" "$cmd"
    ;;
  quick)
    "$SCRIPT_DIR/start_nav_servers.sh" start
    exec "$SCRIPT_DIR/start_nav_servers.sh" status
    ;;
  bridges)
    exec "$SCRIPT_DIR/run_domain_bridges.sh"
    ;;
  detector1)
    exec env START_CAMERA_LAUNCH="${START_CAMERA_LAUNCH:-0}" ROBOT_ID=tb3_burger_01 "$SCRIPT_DIR/run_pi_camera_aruco.sh"
    ;;
  detector2)
    exec env START_CAMERA_LAUNCH="${START_CAMERA_LAUNCH:-0}" ROBOT_ID=tb3_burger_02 "$SCRIPT_DIR/run_pi_camera_aruco.sh"
    ;;
  camera1)
    run_camera 1
    ;;
  camera2)
    run_camera 2
    ;;
  check1)
    check_robot 1
    ;;
  check2)
    check_robot 2
    ;;
  aruco1)
    exec env MARKER_ID="$MARKER_ID" ROBOT_ID=tb3_burger_01 "$SCRIPT_DIR/local_aruco_parking_test.sh"
    ;;
  aruco2)
    exec env MARKER_ID="$MARKER_ID" ROBOT_ID=tb3_burger_02 "$SCRIPT_DIR/local_aruco_parking_test.sh"
    ;;
  nav2-1)
    if [[ "${NAV2_MANUAL_INITIAL_POSE:-0}" == "1" ]]; then
      : "${NAV2_INITIAL_X:?NAV2_INITIAL_X is required for the confirmed field map}"
      : "${NAV2_INITIAL_Y:?NAV2_INITIAL_Y is required for the confirmed field map}"
      : "${NAV2_INITIAL_YAW:?NAV2_INITIAL_YAW is required for the confirmed field map}"
      exec "$SCRIPT_DIR/run_nav2_with_initial_pose.sh" --robot tb3_1 --domain 2 --x "$NAV2_INITIAL_X" --y "$NAV2_INITIAL_Y" --yaw "$NAV2_INITIAL_YAW" --delay "${NAV2_INITIAL_DELAY:-12}" --repeat "${NAV2_INITIAL_REPEAT:-8}"
    fi
    exec "$SCRIPT_DIR/run_nav2_with_initial_pose.sh" --robot tb3_1 --domain 2
    ;;
  nav2-2)
    if [[ "${NAV2_MANUAL_INITIAL_POSE:-0}" == "1" ]]; then
      : "${NAV2_INITIAL_X:?NAV2_INITIAL_X is required for the confirmed field map}"
      : "${NAV2_INITIAL_Y:?NAV2_INITIAL_Y is required for the confirmed field map}"
      : "${NAV2_INITIAL_YAW:?NAV2_INITIAL_YAW is required for the confirmed field map}"
      exec "$SCRIPT_DIR/run_nav2_with_initial_pose.sh" --robot tb3_2 --domain 5 --x "$NAV2_INITIAL_X" --y "$NAV2_INITIAL_Y" --yaw "$NAV2_INITIAL_YAW" --delay "${NAV2_INITIAL_DELAY:-12}" --repeat "${NAV2_INITIAL_REPEAT:-8}"
    fi
    exec "$SCRIPT_DIR/run_nav2_with_initial_pose.sh" --robot tb3_2 --domain 5
    ;;
  robot-commands)
    cat <<'EOF'
Run these on the TurtleBot SBCs, not on the Nav PC.

Robot1 SBC:
  source /opt/ros/jazzy/setup.bash
  export ROS_DOMAIN_ID=2
  export TURTLEBOT3_MODEL=burger
  ros2 launch turtlebot3_bringup robot.launch.py

Robot1 SBC camera, second terminal:
  source /opt/ros/jazzy/setup.bash
  export ROS_DOMAIN_ID=2
  ros2 launch turtlebot3_bringup camera_low_bandwidth.launch.py

Robot2 SBC:
  source /opt/ros/jazzy/setup.bash
  export ROS_DOMAIN_ID=5
  export TURTLEBOT3_MODEL=burger
  ros2 launch turtlebot3_bringup robot.launch.py \
    usb_port:=/dev/serial/by-id/usb-ROBOTIS_OpenCR_Virtual_ComPort_in_FS_Mode_FFFFFFFEFFFF-if00

  # 로봇2는 리프트 우노와 OpenCR의 ttyACM 번호가 바뀔 수 있으므로
  # 기본 robot.launch.py만 실행하지 말고 OpenCR by-id를 반드시 지정한다.

Robot2 SBC camera, second terminal:
  source /opt/ros/jazzy/setup.bash
  export ROS_DOMAIN_ID=5
  ros2 launch turtlebot3_bringup camera_low_bandwidth.launch.py
EOF
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "[nav_ops] unknown command: $cmd" >&2
    usage >&2
    exit 2
    ;;
esac
