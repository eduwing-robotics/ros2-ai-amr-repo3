#!/usr/bin/env bash
# Isolated stock-Jazzy acceptance test for Gazebo + AMCL + NavigateToPose.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
INITIAL_X="${INITIAL_X:--2.0}"
INITIAL_Y="${INITIAL_Y:--0.5}"
INITIAL_YAW="${INITIAL_YAW:-0.0}"
GOAL_X="${GOAL_X:--1.0}"
GOAL_Y="${GOAL_Y:--0.5}"
GOAL_YAW="${GOAL_YAW:-0.0}"
FINAL_ERROR_THRESHOLD_M="${FINAL_ERROR_THRESHOLD_M:-0.30}"
STARTUP_TIMEOUT_SEC="${STARTUP_TIMEOUT_SEC:-180}"
ACTION_TIMEOUT_SEC="${ACTION_TIMEOUT_SEC:-180}"

usage() {
  cat <<'EOF'
Usage: scripts/verify_gazebo_nav2_e2e.sh [--check|--help]

Discovers the installed Jazzy package shares for nav2_bringup,
nav2_minimal_tb3_sim, and ros_gz_sim. The normal mode launches the stock
tb3_simulation_launch.py headlessly in an isolated ROS domain, publishes a
valid AMCL initial pose, requires both Nav2 lifecycle managers to be active,
requires NavigateToPose to report SUCCEEDED, and verifies final map-frame XY error.

Options:
  --check  Check stock package, launch-file, and map availability only.
  --help   Show this help.

Environment overrides:
  E2E_ROS_DOMAIN_ID          Reserved DDS domain in 100..232. By default a
                             per-run domain is generated in that range.
  INITIAL_X/Y/YAW            Spawn and AMCL initial pose. Default: -2,-0.5,0.
  GOAL_X/Y/YAW               Map-frame goal. Default: -1,-0.5,0.
  FINAL_ERROR_THRESHOLD_M    Maximum final XY error. Default: 0.30 m (stock
                             0.25 m goal tolerance plus one 0.05 m map cell).
  STARTUP_TIMEOUT_SEC        Lifecycle/localization timeout. Default: 180.
  ACTION_TIMEOUT_SEC         NavigateToPose result timeout. Default: 180.

This acceptance covers localization and NavigateToPose only. It makes no
claim about ArUco, lift, forks, docking hardware, or load handling.
EOF
}

source_ros() {
  [[ -f "$ROS_SETUP" ]] || {
    echo "[gazebo-nav2-e2e] missing ROS setup: $ROS_SETUP" >&2
    return 1
  }
  # shellcheck source=/dev/null
  set +u
  source "$ROS_SETUP"
  set -u
}

discover_stock_assets() {
  source_ros

  local package
  for package in nav2_bringup nav2_minimal_tb3_sim ros_gz_sim; do
    ros2 pkg prefix --share "$package" >/dev/null 2>&1 || {
      echo "[gazebo-nav2-e2e] missing Jazzy package: $package" >&2
      return 1
    }
  done

  NAV2_BRINGUP_SHARE="$(ros2 pkg prefix --share nav2_bringup)"
  TB3_SIM_SHARE="$(ros2 pkg prefix --share nav2_minimal_tb3_sim)"
  ROS_GZ_SIM_SHARE="$(ros2 pkg prefix --share ros_gz_sim)"
  NAV2_LAUNCH="$NAV2_BRINGUP_SHARE/launch/tb3_simulation_launch.py"
  TB3_SPAWN_LAUNCH="$TB3_SIM_SHARE/launch/spawn_tb3.launch.py"
  ROS_GZ_LAUNCH="$ROS_GZ_SIM_SHARE/launch/gz_sim.launch.py"
  MAP_YAML="$NAV2_BRINGUP_SHARE/maps/tb3_sandbox.yaml"
  MAP_IMAGE="$NAV2_BRINGUP_SHARE/maps/tb3_sandbox.pgm"
  NAV2_PARAMS_FILE="$NAV2_BRINGUP_SHARE/params/nav2_params.yaml"
  WORLD_FILE="$TB3_SIM_SHARE/worlds/tb3_sandbox.sdf.xacro"

  local asset
  for asset in \
    "$NAV2_LAUNCH" "$TB3_SPAWN_LAUNCH" "$ROS_GZ_LAUNCH" \
    "$MAP_YAML" "$MAP_IMAGE" "$NAV2_PARAMS_FILE" "$WORLD_FILE"; do
    [[ -f "$asset" ]] || {
      echo "[gazebo-nav2-e2e] missing stock launch/map asset: $asset" >&2
      return 1
    }
  done
}

print_check_result() {
  echo "[gazebo-nav2-e2e] CHECK PASS"
  echo "[gazebo-nav2-e2e] nav2_bringup=$NAV2_BRINGUP_SHARE"
  echo "[gazebo-nav2-e2e] nav2_minimal_tb3_sim=$TB3_SIM_SHARE"
  echo "[gazebo-nav2-e2e] ros_gz_sim=$ROS_GZ_SIM_SHARE"
  echo "[gazebo-nav2-e2e] launch=$NAV2_LAUNCH"
  echo "[gazebo-nav2-e2e] map=$MAP_YAML"
}

case "${1:-}" in
  -h|--help)
    usage
    exit 0
    ;;
  --check)
    discover_stock_assets
    print_check_result
    exit 0
    ;;
  "") ;;
  *)
    echo "[gazebo-nav2-e2e] unknown option: $1" >&2
    usage >&2
    exit 2
    ;;
esac

discover_stock_assets

E2E_ROS_DOMAIN_ID="${E2E_ROS_DOMAIN_ID:-$((100 + (( $$ + RANDOM + RANDOM ) % 133)))}"
if ! [[ "$E2E_ROS_DOMAIN_ID" =~ ^[0-9]+$ ]] \
  || (( E2E_ROS_DOMAIN_ID < 100 || E2E_ROS_DOMAIN_ID > 232 )); then
  echo "[gazebo-nav2-e2e] E2E_ROS_DOMAIN_ID must be in 100..232" >&2
  exit 2
fi

RUN_DIR="$(mktemp -d /tmp/gazebo-nav2-e2e.XXXXXX)"
LAUNCH_PID=""
cleanup() {
  local status=$?
  trap - EXIT INT TERM
  if [[ -n "$LAUNCH_PID" ]] && kill -0 "$LAUNCH_PID" 2>/dev/null; then
    echo "[gazebo-nav2-e2e] stopping launch process group $LAUNCH_PID" >&2
    kill -TERM -- "-$LAUNCH_PID" 2>/dev/null || true
    for _ in 1 2 3 4 5; do
      kill -0 "$LAUNCH_PID" 2>/dev/null || break
      sleep 1
    done
    kill -KILL -- "-$LAUNCH_PID" 2>/dev/null || true
  fi
  [[ -n "$LAUNCH_PID" ]] && wait "$LAUNCH_PID" 2>/dev/null || true
  rm -rf "$RUN_DIR"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

export ROS_DOMAIN_ID="$E2E_ROS_DOMAIN_ID"
unset ROS_LOCALHOST_ONLY
export ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST

echo "[gazebo-nav2-e2e] domain=$ROS_DOMAIN_ID run_dir=$RUN_DIR"
echo "[gazebo-nav2-e2e] launch=$NAV2_LAUNCH map=$MAP_YAML"
echo "[gazebo-nav2-e2e] initial=($INITIAL_X,$INITIAL_Y,$INITIAL_YAW) goal=($GOAL_X,$GOAL_Y,$GOAL_YAW) final_error_threshold_m=$FINAL_ERROR_THRESHOLD_M"

# The new session is also the process-group leader. The EXIT trap therefore
# terminates ros2 launch and all Gazebo/Nav2 descendants as one unit.
setsid env TMPDIR="$RUN_DIR" ros2 launch nav2_bringup tb3_simulation_launch.py \
  headless:=True use_rviz:=False use_simulator:=True \
  map:="$MAP_YAML" params_file:="$NAV2_PARAMS_FILE" world:="$WORLD_FILE" \
  x_pose:="$INITIAL_X" y_pose:="$INITIAL_Y" yaw:="$INITIAL_YAW" \
  >"$RUN_DIR/launch.log" 2>&1 &
LAUNCH_PID="$!"

set +e
python3 "$SCRIPT_DIR/verify_gazebo_nav2_e2e_client.py" \
  --initial-x "$INITIAL_X" --initial-y "$INITIAL_Y" --initial-yaw "$INITIAL_YAW" \
  --goal-x "$GOAL_X" --goal-y "$GOAL_Y" --goal-yaw "$GOAL_YAW" \
  --max-final-error-m "$FINAL_ERROR_THRESHOLD_M" \
  --startup-timeout-sec "$STARTUP_TIMEOUT_SEC" --action-timeout-sec "$ACTION_TIMEOUT_SEC"
client_status=$?
set -e

if (( client_status != 0 )); then
  echo "[gazebo-nav2-e2e] launch log tail follows" >&2
  tail -n 80 "$RUN_DIR/launch.log" >&2 || true
  exit "$client_status"
fi
