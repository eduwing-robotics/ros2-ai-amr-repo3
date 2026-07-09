#!/usr/bin/env bash
#
# Start one Nav server API process per physical robot.
#
# Default topology:
#   tb3_burger_01 -> ROS_DOMAIN_ID=2 -> http://0.0.0.0:8001
#   tb3_burger_02 -> ROS_DOMAIN_ID=5 -> http://0.0.0.0:8002
#
# Keep these API processes in each robot domain. The center domain remains 1
# for domain_bridge/manual teleop command routing.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
ROS_LOCALHOST_ONLY="${ROS_LOCALHOST_ONLY:-0}"
ROBOTS_CONFIG_PATH="${ROBOTS_CONFIG_PATH:-$ROOT/config/robots.json}"
VALIDATOR="${VALIDATOR:-$SCRIPT_DIR/validate_robot_domains.py}"
HOST="${HOST:-0.0.0.0}"
TB3_1_PORT="${TB3_1_PORT:-8001}"
TB3_2_PORT="${TB3_2_PORT:-8002}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_SITE_PACKAGES="${VENV_SITE_PACKAGES:-$ROOT/venv/lib/python3.12/site-packages}"
DRY_RUN_MISSION="${DRY_RUN_MISSION:-0}"
DRY_RUN_STEP_DELAY_SEC="${DRY_RUN_STEP_DELAY_SEC:-0.2}"
# 2026-07-04 실측: 정렬 완료(마커 65px) 지점 기준. 출고2는 36.5cm 적정, 출고1은 34.5cm까지 후퇴 필요 → 안전값 34.5cm
FORK_INSERT_DISTANCE_M="${FORK_INSERT_DISTANCE_M:-0.345}"
FORK_INSERT_MAX_DURATION_SEC="${FORK_INSERT_MAX_DURATION_SEC:-15.0}"
NAV_GOAL_XY_TOLERANCE_M="${NAV_GOAL_XY_TOLERANCE_M:-0.02}"
NAV_GOAL_YAW_TOLERANCE_RAD="${NAV_GOAL_YAW_TOLERANCE_RAD:-0.035}"
NAV_APPROACH_XY_TOLERANCE_M="${NAV_APPROACH_XY_TOLERANCE_M:-0.02}"
NAV_APPROACH_YAW_TOLERANCE_RAD="${NAV_APPROACH_YAW_TOLERANCE_RAD:-0.035}"
NAV_APPROACH_SOFT_XY_TOLERANCE_M="${NAV_APPROACH_SOFT_XY_TOLERANCE_M:-0.07}"
NAV_APPROACH_SOFT_YAW_TOLERANCE_RAD="${NAV_APPROACH_SOFT_YAW_TOLERANCE_RAD:-0.25}"
RECORD_MAX_XY_ERROR_M="${RECORD_MAX_XY_ERROR_M:-0.02}"
ARUCO_DOCK_CENTER_TOLERANCE_NORM="${ARUCO_DOCK_CENTER_TOLERANCE_NORM:-0.03}"

pids=()

usage() {
  cat <<'EOF'
Usage:
  scripts/run_nav_servers.sh

Environment:
  ROS_SETUP           ROS setup path. Default: /opt/ros/jazzy/setup.bash
  ROS_LOCALHOST_ONLY  ROS localhost setting. Default: 0
  ROBOTS_CONFIG_PATH  robots.json path
  HOST                Bind host. Default: 0.0.0.0
  TB3_1_PORT          API port for tb3_burger_01. Default: 8001
  TB3_2_PORT          API port for tb3_burger_02. Default: 8002
  PYTHON_BIN          Python executable. Default: python3
  VENV_SITE_PACKAGES  FastAPI/uvicorn package path. Default: ./venv/lib/python3.12/site-packages
  DRY_RUN_MISSION     1 to accept missions without moving robots. Default: 0
  DRY_RUN_STEP_DELAY_SEC  Delay used by dry-run missions. Default: 0.2

Examples:
  scripts/run_nav_servers.sh
  TB3_1_PORT=8011 TB3_2_PORT=8012 scripts/run_nav_servers.sh
EOF
}

cleanup() {
  if ((${#pids[@]} > 0)); then
    echo
    echo "[nav_servers] stopping child processes..."
    kill "${pids[@]}" 2>/dev/null || true
    wait 2>/dev/null || true
  fi
}

require_file() {
  local path="$1"
  local label="$2"
  if [[ ! -f "$path" ]]; then
    echo "[nav_servers] missing ${label}: $path" >&2
    exit 1
  fi
}

start_nav_server() {
  local robot_id="$1"
  local domain_id="$2"
  local port="$3"
  local map_yaml="${4:-$ROOT/map/robot1_map.yaml}"

  echo "[nav_servers] starting ${robot_id}: ROS_DOMAIN_ID=${domain_id}, port=${port}, map=${map_yaml}"
  (
    cd "$ROOT/scripts"
    ROBOT_ID="$robot_id" \
    ROS_DOMAIN_ID="$domain_id" \
    ACTIVE_MAP_YAML="$map_yaml" \
    ROBOTS_CONFIG_PATH="$ROBOTS_CONFIG_PATH" \
    ROS_LOCALHOST_ONLY="$ROS_LOCALHOST_ONLY" \
    DRY_RUN_MISSION="$DRY_RUN_MISSION" \
    DRY_RUN_STEP_DELAY_SEC="$DRY_RUN_STEP_DELAY_SEC" \
    FORK_INSERT_DISTANCE_M="$FORK_INSERT_DISTANCE_M" \
    FORK_INSERT_MAX_DURATION_SEC="$FORK_INSERT_MAX_DURATION_SEC" \
    NAV_GOAL_XY_TOLERANCE_M="$NAV_GOAL_XY_TOLERANCE_M" \
    NAV_GOAL_YAW_TOLERANCE_RAD="$NAV_GOAL_YAW_TOLERANCE_RAD" \
    NAV_APPROACH_XY_TOLERANCE_M="$NAV_APPROACH_XY_TOLERANCE_M" \
    NAV_APPROACH_YAW_TOLERANCE_RAD="$NAV_APPROACH_YAW_TOLERANCE_RAD" \
    NAV_APPROACH_SOFT_XY_TOLERANCE_M="$NAV_APPROACH_SOFT_XY_TOLERANCE_M" \
    NAV_APPROACH_SOFT_YAW_TOLERANCE_RAD="$NAV_APPROACH_SOFT_YAW_TOLERANCE_RAD" \
    RECORD_MAX_XY_ERROR_M="$RECORD_MAX_XY_ERROR_M" \
    ARUCO_DOCK_CENTER_TOLERANCE_NORM="$ARUCO_DOCK_CENTER_TOLERANCE_NORM" \
    "$PYTHON_BIN" -m uvicorn nav_server:app --host "$HOST" --port "$port"
  ) &
  pids+=("$!")
}

while (($# > 0)); do
  case "$1" in
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[nav_servers] unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

trap cleanup EXIT INT TERM

require_file "$ROS_SETUP" "ROS setup"
require_file "$ROBOTS_CONFIG_PATH" "robots config"
require_file "$VALIDATOR" "robot domain validator"

"$PYTHON_BIN" "$VALIDATOR" --config "$ROBOTS_CONFIG_PATH" --bridge-dir "$ROOT/config/domain_bridge"

# shellcheck source=/dev/null
set +u
source "$ROS_SETUP"
set -u
export ROS_LOCALHOST_ONLY

if [[ -d "$VENV_SITE_PACKAGES" ]]; then
  export PYTHONPATH="$VENV_SITE_PACKAGES:${PYTHONPATH:-}"
fi

if ! command -v ros2 >/dev/null 2>&1; then
  echo "[nav_servers] ros2 command not found after sourcing $ROS_SETUP" >&2
  exit 1
fi

if ! "$PYTHON_BIN" -c 'import uvicorn' >/dev/null 2>&1; then
  echo "[nav_servers] Python package not found: uvicorn" >&2
  echo "[nav_servers] install or activate the project venv before running this script." >&2
  exit 1
fi

start_nav_server "tb3_burger_01" 2 "$TB3_1_PORT" "$ROOT/map/robot1_map.yaml"
start_nav_server "tb3_burger_02" 5 "$TB3_2_PORT" "$ROOT/map/robot2_map.yaml"

echo "[nav_servers] up. tb3_burger_01=:${TB3_1_PORT}, tb3_burger_02=:${TB3_2_PORT}. Ctrl+C to stop."
wait
