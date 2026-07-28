#!/usr/bin/env bash
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/sim_paths.sh
source "$_SCRIPT_DIR/sim_paths.sh"
sim_paths_init "$_SCRIPT_DIR"

if ! NAV2_REFECTOR_ROOT="$(resolve_nav2_refector_root)"; then
  echo "[sim] cannot find nav2_REFECTOR (set NAV2_REFECTOR_ROOT or clone ../WS/nav2_REFECTOR)" >&2
  exit 1
fi
ROOT="$NAV2_REFECTOR_ROOT/slam_nav_ws"
MAP_NAME="${MAP_NAME:-}"
if [[ -n "$MAP_NAME" ]]; then
  MAP_YAML="${MAP_YAML:-$SIMULATOR_ROOT/maps/$MAP_NAME/map.yaml}"
else
  MAP_YAML="${MAP_YAML:-$ROOT/map/robot1_map.yaml}"
fi
WALL_HEIGHT_M="${WALL_HEIGHT_M:-0.50}"
GENERATED_WORLD="$SIMULATOR_ROOT/worlds/generated_${MAP_NAME:-robot1_map}.world"
API_PORT="${API_PORT:-8001}"
MULTI_NAV_API="${MULTI_NAV_API:-0}"
GAZEBO_GUI="${GAZEBO_GUI:-0}"
WAREHOUSE_WORLD="${WAREHOUSE_WORLD:-0}"
INITIAL_X="${INITIAL_X:-}"
INITIAL_Y="${INITIAL_Y:-}"
INITIAL_YAW="${INITIAL_YAW:-}"
EXTRA_ROS_SETUP="${EXTRA_ROS_SETUP:-}"
NAV2_PARAMS_FILE="${NAV2_PARAMS_FILE:-}"

pids=()

cleanup() {
  echo "[sim] stopping demo processes..."
  if ((${#pids[@]} > 0)); then
    kill "${pids[@]}" 2>/dev/null || true
    wait 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

require_file() {
  local path="$1"
  local label="$2"
  if [[ ! -f "$path" ]]; then
    echo "[sim] missing ${label}: ${path}" >&2
    exit 1
  fi
}

require_file "$ROS_SETUP" "ROS setup"
require_file "$MAP_YAML" "Nav2 map yaml"

source_ros_stack

if [[ -z "$EXTRA_ROS_SETUP" ]]; then
  EXTRA_ROS_SETUP="$(resolve_turtlebot3_setup 2>/dev/null || true)"
fi
if [[ -n "$EXTRA_ROS_SETUP" && -f "$EXTRA_ROS_SETUP" ]]; then
  set +u
  # shellcheck source=/dev/null
  source "$EXTRA_ROS_SETUP"
  set -u
fi

export TURTLEBOT3_MODEL="${TURTLEBOT3_MODEL:-burger}"
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-2}"
export ROS_LOCALHOST_ONLY="${ROS_LOCALHOST_ONLY:-0}"
if [[ -z "${RMW_IMPLEMENTATION:-}" ]]; then
  if ros2 pkg prefix rmw_cyclonedds_cpp >/dev/null 2>&1; then
    export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
  else
    export RMW_IMPLEMENTATION=rmw_fastrtps_cpp
  fi
fi
export ROBOT_ID="${ROBOT_ID:-tb3_burger_01}"
export ACTIVE_MAP_YAML="$MAP_YAML"
export SIMULATOR_ROOT
export NAV2_REFECTOR_ROOT

cd "$ROOT"

echo "[sim] SIMULATOR_ROOT=$SIMULATOR_ROOT"
echo "[sim] NAV2_REFECTOR_ROOT=$NAV2_REFECTOR_ROOT"
echo "[sim] ROS_DOMAIN_ID=$ROS_DOMAIN_ID TURTLEBOT3_MODEL=$TURTLEBOT3_MODEL RMW=$RMW_IMPLEMENTATION"
echo "[sim] map=$MAP_YAML"

GAZEBO_GUI_BOOL="false"
if [[ "$GAZEBO_GUI" == "1" || "$GAZEBO_GUI" == "true" ]]; then
  GAZEBO_GUI_BOOL="true"
fi

if [[ "$WAREHOUSE_WORLD" == "1" || "$WAREHOUSE_WORLD" == "true" ]]; then
  INITIAL_X="${INITIAL_X:-0.765}"
  INITIAL_Y="${INITIAL_Y:-0.58}"
  INITIAL_YAW="${INITIAL_YAW:--1.57}"
  echo "[sim] regenerating warehouse world from map=$MAP_YAML"
  python3 "$SIMULATOR_ROOT/scripts/generate_warehouse_world.py" \
    --map-yaml "$MAP_YAML" \
    --out-world "$GENERATED_WORLD" \
    --out-model "$SIMULATOR_ROOT/models/warehouse_zone_markers" \
    --wall-height-m "$WALL_HEIGHT_M"
  echo "[sim] starting Gazebo Sim warehouse world ($GENERATED_WORLD)"
  ros2 launch "$SIMULATOR_ROOT/launch/warehouse_demo.launch.py" \
    world:="$GENERATED_WORLD" \
    gui:="$GAZEBO_GUI_BOOL" \
    x_pose:="$INITIAL_X" \
    y_pose:="$INITIAL_Y" \
    yaw:="$INITIAL_YAW" &
else
  INITIAL_X="${INITIAL_X:-0.0}"
  INITIAL_Y="${INITIAL_Y:-0.0}"
  INITIAL_YAW="${INITIAL_YAW:-0.0}"
  if [[ "$GAZEBO_GUI_BOOL" == "true" ]]; then
    echo "[sim] starting TurtleBot3 Gazebo world with GUI"
  else
    echo "[sim] starting TurtleBot3 Gazebo world headless"
  fi
  ros2 launch "$SIMULATOR_ROOT/launch/turtlebot3_gz_demo.launch.py" \
    gui:="$GAZEBO_GUI_BOOL" &
fi
pids+=("$!")

echo "[sim] waiting for Gazebo topics..."
sleep 10

echo "[sim] starting Nav2"
if [[ -n "$NAV2_PARAMS_FILE" ]]; then
  require_file "$NAV2_PARAMS_FILE" "Nav2 params file"
  echo "[sim] nav2_params=$NAV2_PARAMS_FILE"
  ros2 launch turtlebot3_navigation2 navigation2.launch.py \
    use_sim_time:=True \
    map:="$MAP_YAML" \
    params_file:="$NAV2_PARAMS_FILE" &
else
  ros2 launch turtlebot3_navigation2 navigation2.launch.py \
    use_sim_time:=True \
    map:="$MAP_YAML" &
fi
pids+=("$!")

echo "[sim] waiting before initial pose..."
sleep 12

echo "[sim] publishing initial pose x=$INITIAL_X y=$INITIAL_Y yaw=$INITIAL_YAW"
bash "$SIMULATOR_ROOT/scripts/pub_initialpose.sh" "$INITIAL_X" "$INITIAL_Y" "$INITIAL_YAW"

if [[ "$MULTI_NAV_API" == "1" || "$MULTI_NAV_API" == "true" ]]; then
  echo "[sim] starting multi Nav APIs on :${TB3_1_PORT:-8001}, :${TB3_2_PORT:-8002}"
  (
    cd "$ROOT"
    TB3_1_PORT="${TB3_1_PORT:-8001}" \
    TB3_2_PORT="${TB3_2_PORT:-8002}" \
    scripts/run_nav_servers.sh
  ) &
  pids+=("$!")
  echo "[sim] demo is running. APIs: http://localhost:${TB3_1_PORT:-8001}, http://localhost:${TB3_2_PORT:-8002}"
else
  echo "[sim] starting Nav API on :$API_PORT"
  (
    cd "$ROOT/scripts"
    python3 -m uvicorn nav_server:app --host 0.0.0.0 --port "$API_PORT"
  ) &
  pids+=("$!")
  echo "[sim] demo is running. API: http://localhost:$API_PORT"
fi

wait
