#!/usr/bin/env bash
# Launch warehouse Gazebo + Nav2 + RViz with aligned map/spawn.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIMULATOR_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Optional profile: SIM_PROFILE=sample bash scripts/launch_gazebo_rviz.sh
if [[ -n "${SIM_PROFILE:-}" ]]; then
  # shellcheck disable=SC1090
  eval "$(bash "$SCRIPT_DIR/load_profile.sh" "$SIM_PROFILE")"
fi

MAP_YAML="${MAP_YAML:-$SIMULATOR_ROOT/maps/sample/map.yaml}"
MAP_NAME="${MAP_NAME:-sample}"
NAV2_PARAMS_FILE="${NAV2_PARAMS_FILE:-}"
INITIAL_X="${INITIAL_X:-${SPAWN_X:-0.765}}"
INITIAL_Y="${INITIAL_Y:-${SPAWN_Y:-0.58}}"
INITIAL_YAW="${INITIAL_YAW:-${SPAWN_YAW:--1.57}}"
GAZEBO_GUI="${GAZEBO_GUI:-1}"
RVIZ="${RVIZ:-0}"
WORLD_PATH="$SIMULATOR_ROOT/worlds/generated_${MAP_NAME}.world"

# shellcheck source=scripts/sim_paths.sh
source "$SCRIPT_DIR/sim_paths.sh"
sim_paths_init "$SCRIPT_DIR"
source_ros_stack

export TURTLEBOT3_MODEL="${TURTLEBOT3_MODEL:-burger}"
export ROS_DOMAIN_ID="${SIM_ROS_DOMAIN_ID:-2}"
export DISPLAY="${DISPLAY:-:1}"
export SIMULATOR_ROOT

pids=()
cleanup() {
  echo "[launch] stopping..."
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "[launch] stopping stale sim processes..."
pkill -f "gz sim" 2>/dev/null || true
pkill -f "rviz2" 2>/dev/null || true
pkill -f "warehouse_demo.launch.py" 2>/dev/null || true
pkill -f "navigation2.launch.py" 2>/dev/null || true
sleep 2

echo "[launch] generating world from $MAP_YAML"
python3 "$SIMULATOR_ROOT/scripts/generate_warehouse_world.py" \
  --map-yaml "$MAP_YAML" \
  --out-world "$WORLD_PATH" \
  --out-model "$SIMULATOR_ROOT/models/warehouse_zone_markers"

echo "[launch] starting Gazebo + TurtleBot3 at ($INITIAL_X, $INITIAL_Y, $INITIAL_YAW)"
ros2 launch "$SIMULATOR_ROOT/launch/warehouse_demo.launch.py" \
  world:="$WORLD_PATH" \
  gui:=false \
  x_pose:="$INITIAL_X" \
  y_pose:="$INITIAL_Y" \
  yaw:="$INITIAL_YAW" &
pids+=("$!")
sleep 8

echo "[launch] starting Nav2 with map=$MAP_YAML"
if [[ -n "$NAV2_PARAMS_FILE" ]]; then
  if [[ ! -f "$NAV2_PARAMS_FILE" ]]; then
    echo "[launch] missing Nav2 params file: $NAV2_PARAMS_FILE" >&2
    exit 1
  fi
  echo "[launch] nav2_params=$NAV2_PARAMS_FILE"
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
sleep 12

echo "[launch] waiting for /scan (lidar must publish before AMCL can localize)"
for _ in $(seq 1 30); do
  if timeout 2 ros2 topic echo /scan --once >/dev/null 2>&1; then
    echo "[launch] /scan is publishing"
    break
  fi
  sleep 1
done

echo "[launch] publishing initial pose (sim time)"
bash "$SIMULATOR_ROOT/scripts/pub_initialpose.sh" "$INITIAL_X" "$INITIAL_Y" "$INITIAL_YAW"
sleep 2

if [[ "$GAZEBO_GUI" == "1" || "$GAZEBO_GUI" == "true" ]]; then
  TB3_MODELS="$(ros2 pkg prefix turtlebot3_gazebo)/share/turtlebot3_gazebo/models"
  export GZ_SIM_RESOURCE_PATH="$SIMULATOR_ROOT/models:${TB3_MODELS}"
  echo "[launch] starting Gazebo GUI"
  gz sim -g -v 2 &
  pids+=("$!")
fi

if [[ "$RVIZ" == "1" || "$RVIZ" == "true" ]]; then
  RVIZ_CONFIG="$(ros2 pkg prefix turtlebot3_navigation2)/share/turtlebot3_navigation2/rviz/tb3_navigation2.rviz"
  echo "[launch] starting extra RViz ($RVIZ_CONFIG)"
  ros2 run rviz2 rviz2 -d "$RVIZ_CONFIG" --ros-args -r __node:=rviz2_extra -p use_sim_time:=true &
  pids+=("$!")
fi

echo "[launch] running. Gazebo spawn=($INITIAL_X,$INITIAL_Y) map=$MAP_YAML"
echo "[launch] press Ctrl+C to stop"
wait
