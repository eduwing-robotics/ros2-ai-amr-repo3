#!/usr/bin/env bash
# Prepare and run the two-robot Gazebo standby safety stack.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIMULATOR_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROOT="$(cd "$SIMULATOR_ROOT/.." && pwd)"
CONFIG="${DUAL_SIM_CONFIG:-$SIMULATOR_ROOT/config/dual_robot_standby.json}"
GENERATED="$SIMULATOR_ROOT/generated/dual_robot"
WORLD="$SIMULATOR_ROOT/worlds/generated_nav_server_dual.world"
STATE_DIR="$GENERATED/state"
PID_FILE="$GENERATED/stack.pid"
PARTITION_FILE="$GENERATED/gz_partition"
LOG_FILE="$GENERATED/stack.log"
GAZEBO_GUI="${GAZEBO_GUI:-0}"
GAZEBO_USE_XVFB="${GAZEBO_USE_XVFB:-auto}"
GAZEBO_VIRTUAL_DISPLAY="${GAZEBO_VIRTUAL_DISPLAY:-:98}"
XVFB_BIN="${XVFB_BIN:-$(command -v Xvfb || true)}"
NAV2_PARAMS_FILE="${NAV2_PARAMS_FILE:-$ROOT/config/nav2/burger_smartfactory_sim.yaml}"

source "$SCRIPT_DIR/sim_paths.sh"
sim_paths_init "$SCRIPT_DIR"

pids=()

partition_process_ids() {
  local partition="$1"
  local env_file pid
  for env_file in /proc/[0-9]*/environ; do
    [[ -r "$env_file" ]] || continue
    if grep -zFqx -- "GZ_PARTITION=$partition" "$env_file" 2>/dev/null; then
      pid="${env_file#/proc/}"
      printf '%s\n' "${pid%/environ}"
    fi
  done
}

terminate_partition_processes() {
  local partition="$1"
  local excluded_pid="${2:-}"
  local pid index
  local -a matched=() survivors=()
  while IFS= read -r pid; do
    [[ -n "$pid" && "$pid" != "$excluded_pid" && "$pid" != "$$" ]] || continue
    matched+=("$pid")
  done < <(partition_process_ids "$partition")
  ((${#matched[@]} > 0)) || return 0
  echo "[dual_sim] stopping partition $partition processes: ${matched[*]}"
  kill -TERM "${matched[@]}" 2>/dev/null || true
  for index in $(seq 1 50); do
    survivors=()
    for pid in "${matched[@]}"; do
      kill -0 "$pid" 2>/dev/null && survivors+=("$pid")
    done
    ((${#survivors[@]} == 0)) && return 0
    sleep 0.1
  done
  echo "[dual_sim] partition $partition processes still shutting down: ${survivors[*]}" >&2
  return 1
}

prepare() {
  mkdir -p "$SIMULATOR_ROOT/maps/nav_server" "$GENERATED" "$STATE_DIR"
  cp "$ROOT/map/robot2_map.pgm" "$SIMULATOR_ROOT/maps/nav_server/map.pgm"
  cp "$ROOT/map/zones.json" "$SIMULATOR_ROOT/maps/nav_server/zones.json"
  python3 "$SCRIPT_DIR/dual_robot_geometry.py" --config "$CONFIG" >/dev/null
  python3 "$SCRIPT_DIR/generate_warehouse_world.py" \
    --map-yaml "$SIMULATOR_ROOT/maps/nav_server/map.yaml" \
    --out-world "$WORLD" \
    --out-model "$SIMULATOR_ROOT/models/warehouse_zone_markers" \
    --wall-height-m 0.50 >/dev/null
  python3 "$SCRIPT_DIR/generate_dual_robot_assets.py" \
    --config "$CONFIG" --world "$WORLD" --output-dir "$GENERATED" >/dev/null
  TRAFFIC_LOCK_STATE_PATH="$(jq -r ".traffic_lock_state_path" "$CONFIG")" \
    PYTHONPATH="$ROOT/scripts" python3 -c "from traffic_manager import TrafficManager; TrafficManager().reset()"
  echo "[dual_sim] prepared current map, world, SDFs, bridges, and empty traffic state"
  python3 "$SCRIPT_DIR/dual_robot_geometry.py" --config "$CONFIG"
}

assert_port_free() {
  local port="$1"
  if ss -ltn | grep -q ":${port} "; then
    echo "[dual_sim] port ${port} is already in use; existing physical/API stack is left untouched" >&2
    exit 1
  fi
}

wait_for_topic() {
  local domain="$1"
  local topic="$2"
  local attempts="${3:-45}"
  local index
  for index in $(seq 1 "$attempts"); do
    if env ROS_DOMAIN_ID="$domain" timeout 2 ros2 topic echo "$topic" --once >/dev/null 2>&1; then
      echo "[dual_sim] domain${domain} ${topic} ready"
      return 0
    fi
    sleep 1
  done
  echo "[dual_sim] domain${domain} ${topic} timeout" >&2
  return 1
}

foreground() {
  assert_port_free 8001
  assert_port_free 8002
  prepare
  source_ros_stack
  export TURTLEBOT3_MODEL=burger
  export SIMULATOR_ROOT
  export GZ_PARTITION="${DUAL_SIM_GZ_PARTITION:-nav_server_dual_$$}"
  printf '%s\n' "$GZ_PARTITION" >"$PARTITION_FILE"
  echo "[dual_sim] Gazebo transport partition: $GZ_PARTITION"
  pids=()
  cleanup() {
    echo "[dual_sim] stopping child processes"
    if ((${#pids[@]} > 0)); then
      kill "${pids[@]}" 2>/dev/null || true
      wait 2>/dev/null || true
    fi
    terminate_partition_processes "$GZ_PARTITION" "$$" || true
  }
  trap cleanup EXIT INT TERM

  local use_xvfb=0
  if [[ "$GAZEBO_USE_XVFB" == 1 || "$GAZEBO_USE_XVFB" == true ]]; then
    use_xvfb=1
  elif [[ "$GAZEBO_USE_XVFB" == auto && -n "$XVFB_BIN" ]]; then
    use_xvfb=1
  fi
  if ((use_xvfb)); then
    if [[ ! -x "$XVFB_BIN" ]]; then
      echo "[dual_sim] GAZEBO_USE_XVFB requested but Xvfb is unavailable" >&2
      exit 1
    fi
    if ! DISPLAY="$GAZEBO_VIRTUAL_DISPLAY" xdpyinfo >/dev/null 2>&1; then
      "$XVFB_BIN" "$GAZEBO_VIRTUAL_DISPLAY" -screen 0 1280x720x24 -nolisten tcp -noreset &
      pids+=("$!")
      sleep 1
    fi
    DISPLAY="$GAZEBO_VIRTUAL_DISPLAY" xdpyinfo >/dev/null 2>&1 || {
      echo "[dual_sim] virtual display $GAZEBO_VIRTUAL_DISPLAY failed" >&2
      exit 1
    }
    export DISPLAY="$GAZEBO_VIRTUAL_DISPLAY"
    export LIBGL_ALWAYS_SOFTWARE=1
    export GAZEBO_HEADLESS_RENDERING=0
    export DUAL_SIM_SENSOR_CONFIG="$SIMULATOR_ROOT/config/gz_sim_sensors_xvfb.config"
    echo "[dual_sim] Gazebo sensor rendering: Xvfb $DISPLAY + software GL"
  elif [[ -z "${DISPLAY:-}" ]]; then
    export GAZEBO_HEADLESS_RENDERING=1
    export DUAL_SIM_SENSOR_CONFIG="$SIMULATOR_ROOT/config/gz_sim_sensors_server.config"
    echo "[dual_sim] Gazebo sensor rendering: EGL headless"
  else
    export GAZEBO_HEADLESS_RENDERING=0
    export DUAL_SIM_SENSOR_CONFIG="$SIMULATOR_ROOT/config/gz_sim_sensors_server.config"
    echo "[dual_sim] Gazebo sensor rendering: existing DISPLAY=$DISPLAY"
  fi

  ros2 launch "$SIMULATOR_ROOT/launch/dual_robot_warehouse.launch.py" \
    world:="$WORLD" gui:="$([[ "$GAZEBO_GUI" == 1 || "$GAZEBO_GUI" == true ]] && echo true || echo false)" &
  pids+=("$!")
  wait_for_topic 2 /scan
  wait_for_topic 5 /scan

  local robot name domain x y yaw
  for name in tb3_1 tb3_2; do
    robot="$(python3 "$SCRIPT_DIR/dual_robot_geometry.py" --config "$CONFIG" --robot "$name")"
    domain="$(jq -r ".ros_domain_id" <<<"$robot")"
    x="$(jq -r ".hold_pose.x" <<<"$robot")"
    y="$(jq -r ".hold_pose.y" <<<"$robot")"
    yaw="$(jq -r ".hold_pose.yaw" <<<"$robot")"
    env ROS_DOMAIN_ID="$domain" python3 "$SCRIPT_DIR/sim_standby_marker_oracle.py" --config "$CONFIG" --robot "$name" &
    pids+=("$!")
    env ROS_DOMAIN_ID="$domain" TURTLEBOT3_MODEL=burger ros2 launch "$ROOT/launch/navigation2_labeled.launch.py" \
      map:="$SIMULATOR_ROOT/maps/nav_server/map.yaml" params_file:="$NAV2_PARAMS_FILE" \
      use_sim_time:=true launch_rviz:=false rviz_title:="Gazebo ${name}" &
    pids+=("$!")
    printf "%s %s %s %s\n" "$domain" "$x" "$y" "$yaw" >"$GENERATED/${name}_initial_pose.txt"
  done

  sleep 12
  while read -r domain x y yaw; do
    env ROS_DOMAIN_ID="$domain" bash "$SCRIPT_DIR/pub_initialpose.sh" "$x" "$y" "$yaw"
  done <"$GENERATED/tb3_1_initial_pose.txt"
  while read -r domain x y yaw; do
    env ROS_DOMAIN_ID="$domain" bash "$SCRIPT_DIR/pub_initialpose.sh" "$x" "$y" "$yaw"
  done <"$GENERATED/tb3_2_initial_pose.txt"

  env ROBOTS_CONFIG_PATH="$ROOT/config/robots.json" \
    MOVEMENT_STATE_DIR="$STATE_DIR" \
    TRAFFIC_LOCK_STATE_PATH="$(jq -r ".traffic_lock_state_path" "$CONFIG")" \
    TRAFFIC_COORDINATION_MODE=segment \
    TRAFFIC_DEPARTURE_STAGGER_SEC=0.5 \
    TRAFFIC_SEGMENT_WAIT_TIMEOUT_SEC=60 \
    TRAFFIC_SEGMENT_TTL_SEC=120 \
    NAV_USE_SIM_TIME=1 SIMULATION_MODE=0 DRY_RUN_MISSION=0 \
    MAIN_API_BASE=http://127.0.0.1:9/api/v1 \
    "$ROOT/scripts/run_nav_servers.sh" &
  pids+=("$!")

  echo "[dual_sim] running: Gazebo world + Nav2 domains 2/5 + APIs :8001/:8002"
  echo "[dual_sim] orange line=20cm hold, green line=40cm approach"
  wait
}

start_background() {
  mkdir -p "$GENERATED"
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "[dual_sim] already running pid=$(cat "$PID_FILE")"
    return 0
  fi
  setsid "$0" foreground >"$LOG_FILE" 2>&1 < /dev/null &
  echo "$!" >"$PID_FILE"
  sleep 2
  if ! kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    tail -80 "$LOG_FILE" >&2 || true
    exit 1
  fi
  echo "[dual_sim] started pid=$(cat "$PID_FILE") log=$LOG_FILE"
}

stop_background() {
  if [[ ! -f "$PID_FILE" ]]; then
    echo "[dual_sim] no tracked stack"
    return 0
  fi
  local pid partition=""
  pid="$(cat "$PID_FILE")"
  [[ -f "$PARTITION_FILE" ]] && partition="$(cat "$PARTITION_FILE")"
  if [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null; then
    kill -TERM "$pid" 2>/dev/null || true
    local index
    for index in $(seq 1 100); do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.1
    done
    if kill -0 "$pid" 2>/dev/null; then
      echo "[dual_sim] tracked stack pid=$pid is still shutting down" >&2
      return 1
    fi
  fi
  [[ -z "$partition" ]] || terminate_partition_processes "$partition" "$$" || return 1
  rm -f "$PID_FILE" "$PARTITION_FILE"
  echo "[dual_sim] stopped tracked stack pid=$pid"
}

status() {
  if [[ -f "$PID_FILE" ]] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "[dual_sim] process: running pid=$(cat "$PID_FILE")"
  else
    echo "[dual_sim] process: stopped"
  fi
  for port in 8001 8002; do
    curl -fsS --max-time 2 "http://127.0.0.1:${port}/movement-api/v1/health" || true
    echo
  done
  if [[ -f "$LOG_FILE" ]]; then tail -40 "$LOG_FILE"; fi
}

case "${1:-start}" in
  prepare|check) prepare ;;
  foreground) foreground ;;
  start) start_background ;;
  stop) stop_background ;;
  restart|reset) stop_background; start_background ;;
  status) status ;;
  *) echo "usage: $0 prepare|start|foreground|stop|restart|status" >&2; exit 2 ;;
esac
