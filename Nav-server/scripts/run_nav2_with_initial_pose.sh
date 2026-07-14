#!/usr/bin/env bash
#
# Launch Nav2 for one robot and optionally seed AMCL with an initial pose.
#
# This helper mirrors the manual workflow:
#   1) start the robot bringup
#   2) launch navigation2.launch.py
#   3) publish an approximate 2D initial pose
#
# It does not replace RViz map checking, but it removes the repetitive
# launch + initial-pose steps when the start pose is already known.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
TURTLEBOT3_SETUP="${TURTLEBOT3_SETUP:-/home/lucas/turtlebot3_ws/install/setup.bash}"
MAP_YAML="${MAP_YAML:-$ROOT/map/robot1_map.yaml}"
NAV2_PARAMS_FILE="${NAV2_PARAMS_FILE:-$ROOT/config/nav2/burger_smartfactory.yaml}"
EKF_PARAMS_FILE="${EKF_PARAMS_FILE:-$ROOT/config/robot_localization/ekf_tb3_burger.yaml}"
WITH_EKF="${WITH_EKF:-0}"
TURTLEBOT3_MODEL="${TURTLEBOT3_MODEL:-burger}"
INITIAL_POSE_DELAY_SEC="${INITIAL_POSE_DELAY_SEC:-8}"
INITIAL_POSE_REPEAT_SEC="${INITIAL_POSE_REPEAT_SEC:-6}"
NAV2_STARTUP_RETRY_SEC="${NAV2_STARTUP_RETRY_SEC:-180}"
ROS_LOCALHOST_ONLY="${ROS_LOCALHOST_ONLY:-0}"

ROBOT_NAME="tb3_2"
ROS_DOMAIN_ID_VALUE=""
INITIAL_X=""
INITIAL_Y=""
INITIAL_YAW=""
POSE_FILE=""
# 기본 OFF: start_all이 넘긴 approach 고정좌표(--x/--y/--yaw)만 사용.
# 저장 pose 자동복원은 위치가 어긋나면 경로가 이상해지므로 쓰지 않음.
# 필요 시 USE_SAVED_POSE=1 또는 --pose-file 로만 켠다.
USE_SAVED_POSE="${USE_SAVED_POSE:-0}"
POSE_DIR="${POSE_DIR:-$ROOT/logs/last_poses}"

usage() {
  cat <<'EOF'
Usage:
  scripts/run_nav2_with_initial_pose.sh [options]

Options:
  --robot NAME        Robot bridge name. Default: tb3_2
  --domain ID         ROS_DOMAIN_ID for the robot. Default: 5 for tb3_2, 2 for tb3_1
  --map PATH          Nav2 map YAML. Default: map/robot1_map.yaml
  --params PATH       Nav2 params YAML. Default: config/nav2/burger_smartfactory.yaml
  --x VALUE           Initial pose X in map frame
  --y VALUE           Initial pose Y in map frame
  --yaw VALUE         Initial pose yaw in radians
  --pose-file PATH    JSON with x/y/yaw (from scripts/save_robot_pose.sh)
  --delay SEC         Seconds to wait after launch before publishing initial pose. Default: 8
  --repeat SEC        Seconds to repeat initial pose publication. Default: 6
  --startup-retry SEC Seconds to retry Nav2 lifecycle startup after launch. Default: 180
  --with-ekf          Enable robot_localization EKF (wheel odom + IMU)
  --no-ekf            Disable EKF (default unless WITH_EKF=1)

Pose (default):
  --x/--y/--yaw from start_all (approach 고정좌표). Saved-pose auto restore is OFF.
  Optional: USE_SAVED_POSE=1 or --pose-file PATH

Examples:
  scripts/run_nav2_with_initial_pose.sh --robot tb3_2 --x 0.816 --y 0.006 --yaw 1.571
  USE_SAVED_POSE=1 scripts/run_nav2_with_initial_pose.sh --robot tb3_2 --domain 5

If --x/--y/--yaw are omitted, the script only launches navigation2.
EOF
}

default_pose_file_for_robot() {
  echo "$POSE_DIR/last_pose_${1}.json"
}

load_pose_file() {
  local path="$1"
  [[ -f "$path" ]] || return 1
  python3 - "$path" <<'PY'
import json, sys
with open(sys.argv[1], encoding="utf-8") as f:
    d = json.load(f)
for k in ("x", "y", "yaw"):
    if k not in d:
        raise SystemExit(1)
print(f"{d['x']} {d['y']} {d['yaw']}")
PY
}

default_domain_for_robot() {
  case "$1" in
    tb3_1) echo "2" ;;
    tb3_2) echo "5" ;;
    *)
      echo ""
      ;;
  esac
}

publish_initial_pose() {
  local x="$1"
  local y="$2"
  local yaw="$3"

  local payload
  payload="$(
    python3 - "$x" "$y" "$yaw" <<'PY'
import math
import sys

x = float(sys.argv[1])
y = float(sys.argv[2])
yaw = float(sys.argv[3])
qz = math.sin(yaw / 2.0)
qw = math.cos(yaw / 2.0)
cov = [0.0] * 36
cov[0] = 0.25
cov[7] = 0.25
cov[35] = 0.0685

def fmt(value):
    text = f"{value:.6f}"
    text = text.rstrip("0").rstrip(".")
    return text if text else "0"

covariance = ", ".join(fmt(value) for value in cov)
print(
    "{header: {frame_id: map}, "
    "pose: {pose: {position: {x: %s, y: %s, z: 0.0}, "
    "orientation: {x: 0.0, y: 0.0, z: %s, w: %s}}, "
    "covariance: [%s]}}"
    % (fmt(x), fmt(y), fmt(qz), fmt(qw), covariance)
)
PY
  )"

  echo "[nav2_helper] publishing initial pose: robot=${ROBOT_NAME} x=${x} y=${y} yaw=${yaw}"
  timeout "$INITIAL_POSE_REPEAT_SEC" ros2 topic pub -r 2 /initialpose geometry_msgs/msg/PoseWithCovarianceStamped "$payload" || true
}

retry_navigation_startup() {
  local deadline output
  deadline=$((SECONDS + NAV2_STARTUP_RETRY_SEC))

  while (( SECONDS < deadline )); do
    output="$(
      timeout 4 ros2 service call /lifecycle_manager_navigation/is_active \
        std_srvs/srv/Trigger "{}" 2>&1 || true
    )"

    if grep -q "success=True" <<<"$output"; then
      echo "[nav2_helper] navigation lifecycle already active"
      return 0
    fi

    output="$(
      timeout 8 ros2 service call /lifecycle_manager_navigation/manage_nodes \
        nav2_msgs/srv/ManageLifecycleNodes "{command: 0}" 2>&1 || true
    )"

    if grep -q "success=True" <<<"$output"; then
      echo "[nav2_helper] navigation lifecycle active"
      return 0
    fi

    sleep 4
  done

  echo "[nav2_helper] navigation lifecycle not active yet. Set 2D Pose Estimate in RViz, then retry Nav2 Goal." >&2
}

while (($# > 0)); do
  case "$1" in
    --robot)
      ROBOT_NAME="${2:-}"
      shift 2
      ;;
    --domain)
      ROS_DOMAIN_ID_VALUE="${2:-}"
      shift 2
      ;;
    --map)
      MAP_YAML="${2:-}"
      shift 2
      ;;
    --params)
      NAV2_PARAMS_FILE="${2:-}"
      shift 2
      ;;
    --x)
      INITIAL_X="${2:-}"
      shift 2
      ;;
    --y)
      INITIAL_Y="${2:-}"
      shift 2
      ;;
    --yaw)
      INITIAL_YAW="${2:-}"
      shift 2
      ;;
    --yaw=*)
      INITIAL_YAW="${1#*=}"
      shift
      ;;
    --x=*)
      INITIAL_X="${1#*=}"
      shift
      ;;
    --y=*)
      INITIAL_Y="${1#*=}"
      shift
      ;;
    --pose-file)
      POSE_FILE="${2:-}"
      shift 2
      ;;
    --pose-file=*)
      POSE_FILE="${1#*=}"
      shift
      ;;
    --delay)
      INITIAL_POSE_DELAY_SEC="${2:-}"
      shift 2
      ;;
    --repeat)
      INITIAL_POSE_REPEAT_SEC="${2:-}"
      shift 2
      ;;
    --startup-retry)
      NAV2_STARTUP_RETRY_SEC="${2:-}"
      shift 2
      ;;
    --with-ekf)
      WITH_EKF=1
      shift
      ;;
    --no-ekf)
      WITH_EKF=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[nav2_helper] unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$ROS_DOMAIN_ID_VALUE" ]]; then
  ROS_DOMAIN_ID_VALUE="$(default_domain_for_robot "$ROBOT_NAME")"
fi

if [[ -z "$ROS_DOMAIN_ID_VALUE" ]]; then
  echo "[nav2_helper] ROS domain is required for robot: $ROBOT_NAME" >&2
  exit 2
fi

# Saved-pose restore only when explicitly enabled (default OFF).
if [[ -n "$POSE_FILE" || "$USE_SAVED_POSE" == "1" ]]; then
  if [[ -z "$POSE_FILE" ]]; then
    POSE_FILE="$(default_pose_file_for_robot "$ROBOT_NAME")"
  fi
  if loaded="$(load_pose_file "$POSE_FILE" 2>/dev/null)"; then
    read -r INITIAL_X INITIAL_Y INITIAL_YAW <<<"$loaded"
    echo "[nav2_helper] using saved pose from $POSE_FILE -> x=$INITIAL_X y=$INITIAL_Y yaw=$INITIAL_YAW"
  else
    echo "[nav2_helper] no saved pose at ${POSE_FILE:-none} — using --x/--y/--yaw if set"
  fi
fi

if [[ ! -f "$ROS_SETUP" ]]; then
  echo "[nav2_helper] missing ROS setup: $ROS_SETUP" >&2
  exit 1
fi

if [[ ! -f "$TURTLEBOT3_SETUP" ]]; then
  echo "[nav2_helper] missing TurtleBot3 setup: $TURTLEBOT3_SETUP" >&2
  exit 1
fi

if [[ ! -f "$MAP_YAML" ]]; then
  echo "[nav2_helper] missing map yaml: $MAP_YAML" >&2
  exit 1
fi

if [[ "$WITH_EKF" == "1" && -z "${NAV2_PARAMS_FILE##*burger_smartfactory.yaml}" ]]; then
  NAV2_PARAMS_FILE="$ROOT/config/nav2/burger_smartfactory_ekf.yaml"
fi

if [[ ! -f "$NAV2_PARAMS_FILE" ]]; then
  echo "[nav2_helper] missing Nav2 params yaml: $NAV2_PARAMS_FILE" >&2
  exit 1
fi

if [[ "$WITH_EKF" == "1" && ! -f "$EKF_PARAMS_FILE" ]]; then
  echo "[nav2_helper] missing EKF params yaml: $EKF_PARAMS_FILE" >&2
  exit 1
fi

# shellcheck source=/dev/null
set +u
source "$ROS_SETUP"
source "$TURTLEBOT3_SETUP"
set -u
export TURTLEBOT3_MODEL
export ROS_DOMAIN_ID="$ROS_DOMAIN_ID_VALUE"
export ROS_LOCALHOST_ONLY

launch_pid=""
ekf_pid=""

cleanup() {
  if [[ -n "$launch_pid" ]]; then
    kill "$launch_pid" 2>/dev/null || true
    wait "$launch_pid" 2>/dev/null || true
  fi
  if [[ -n "$ekf_pid" ]]; then
    kill "$ekf_pid" 2>/dev/null || true
    wait "$ekf_pid" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

cd "$ROOT"

if [[ "$WITH_EKF" == "1" ]]; then
  echo "[nav2_helper] launching EKF: params=${EKF_PARAMS_FILE}"
  ros2 launch "$ROOT/launch/ekf_odom.launch.py" "params_file:=$EKF_PARAMS_FILE" &
  ekf_pid="$!"
  sleep 2
fi

echo "[nav2_helper] launching Nav2: robot=${ROBOT_NAME} domain=${ROS_DOMAIN_ID} ekf=${WITH_EKF} map=${MAP_YAML} params=${NAV2_PARAMS_FILE}"
case "$ROBOT_NAME" in
  tb3_1)
    RVIZ_TITLE="ROBOT1 | RViz | tb3_1 | :8001 | domain2"
    ;;
  tb3_2)
    RVIZ_TITLE="ROBOT2 | RViz | tb3_2 | :8002 | domain5"
    ;;
  *)
    RVIZ_TITLE="RViz | ${ROBOT_NAME} | domain${ROS_DOMAIN_ID}"
    ;;
esac
ros2 launch "$ROOT/launch/navigation2_labeled.launch.py" \
  map:="$MAP_YAML" \
  params_file:="$NAV2_PARAMS_FILE" \
  rviz_title:="$RVIZ_TITLE" &
launch_pid="$!"

sleep "$INITIAL_POSE_DELAY_SEC"

retry_navigation_startup &

if [[ -n "$INITIAL_X" && -n "$INITIAL_Y" && -n "$INITIAL_YAW" ]]; then
  publish_initial_pose "$INITIAL_X" "$INITIAL_Y" "$INITIAL_YAW"
else
  echo "[nav2_helper] initial pose skipped: provide --x/--y/--yaw to publish one"
fi

wait "$launch_pid"
