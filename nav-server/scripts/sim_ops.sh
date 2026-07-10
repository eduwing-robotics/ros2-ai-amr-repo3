#!/usr/bin/env bash
# Convenience entry point for the external Gazebo Simulator workspace.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
DEFAULT_SIMULATOR_ROOT="/home/lucas/slam_nav_ws/Simulator"
SIMULATOR_ROOT="${SIMULATOR_ROOT:-$DEFAULT_SIMULATOR_ROOT}"
NAV2_REFECTOR_ROOT="${NAV2_REFECTOR_ROOT:-$(cd "$ROOT/.." && pwd)}"
NAV_API_VENV="${NAV_API_VENV:-$ROOT/.venv}"
SIM_PROFILE="${SIM_PROFILE:-sample}"
MAP_NAME="${MAP_NAME:-}"

usage() {
  cat <<'EOF'
Usage:
  scripts/sim_ops.sh deps          # check host ROS/Gazebo/Python deps
  scripts/sim_ops.sh phase3        # validate robot/domain bridge config against this slam_nav_ws
  scripts/sim_ops.sh world         # generate sample warehouse world only
  scripts/sim_ops.sh rviz          # Gazebo + Nav2 + RViz, sample profile
  scripts/sim_ops.sh start         # Gazebo + Nav2 + Movement API, sample profile
  scripts/sim_ops.sh topics        # check /cmd_vel /scan /odom /tf
  scripts/sim_ops.sh api           # check Movement API on BASE_URL
  scripts/sim_ops.sh multi         # start Gazebo + Nav2 + both API ports 8001/8002

Common overrides:
  SIMULATOR_ROOT=/home/lucas/slam_nav_ws/Simulator
  NAV2_REFECTOR_ROOT=/home/lucas
  SIM_PROFILE=sample
  MAP_NAME=sample
  BASE_URL=http://localhost:8001
  ROBOT_NAME=tb3_1
  NAV_API_VENV=/home/lucas/slam_nav_ws/.venv

Notes:
  The simulator expects NAV2_REFECTOR_ROOT/slam_nav_ws.
  For this workspace the default NAV2_REFECTOR_ROOT is /home/lucas.
EOF
}

require_simulator() {
  if [[ ! -d "$SIMULATOR_ROOT" ]]; then
    echo "[sim_ops] missing simulator root: $SIMULATOR_ROOT" >&2
    exit 1
  fi
  if [[ ! -f "$SIMULATOR_ROOT/scripts/start_demo.sh" ]]; then
    echo "[sim_ops] invalid simulator root: $SIMULATOR_ROOT" >&2
    exit 1
  fi
}

source_nav_api_venv() {
  if [[ -f "$NAV_API_VENV/bin/activate" ]]; then
    # shellcheck source=/dev/null
    source "$NAV_API_VENV/bin/activate"
    local venv_site="$NAV_API_VENV/lib/python3.12/site-packages"
    export PYTHONPATH="$venv_site:/opt/ros/jazzy/lib/python3.12/site-packages:/usr/lib/python3/dist-packages:${PYTHONPATH:-}"
  fi
}

run_with_profile() {
  local command="$1"
  require_simulator
  cd "$SIMULATOR_ROOT"
  export NAV2_REFECTOR_ROOT
  source_nav_api_venv
  if [[ -n "$MAP_NAME" ]]; then
    export MAP_NAME
  else
    eval "$(bash scripts/load_profile.sh "$SIM_PROFILE")"
  fi
  eval "$command"
}

cmd="${1:-help}"
case "$cmd" in
  deps)
    require_simulator
    cd "$SIMULATOR_ROOT"
    source_nav_api_venv
    exec env NAV2_REFECTOR_ROOT="$NAV2_REFECTOR_ROOT" bash scripts/check_host_deps.sh
    ;;
  phase3)
    require_simulator
    cd "$SIMULATOR_ROOT"
    exec env NAV2_REFECTOR_ROOT="$NAV2_REFECTOR_ROOT" python3 scripts/validate_phase3_config.py
    ;;
  world)
    require_simulator
    cd "$SIMULATOR_ROOT"
    eval "$(bash scripts/load_profile.sh "$SIM_PROFILE")"
    map_name="${MAP_NAME:-sample}"
    map_yaml="${MAP_YAML:-$SIMULATOR_ROOT/maps/$map_name/map.yaml}"
    out_world="${OUT_WORLD:-$SIMULATOR_ROOT/worlds/generated_${map_name}.world}"
    out_model="${OUT_MODEL:-$SIMULATOR_ROOT/models/warehouse_zone_markers}"
    exec python3 scripts/generate_warehouse_world.py \
      --map-yaml "$map_yaml" \
      --out-world "$out_world" \
      --out-model "$out_model" \
      --wall-height-m "${WALL_HEIGHT_M:-0.50}"
    ;;
  rviz)
    require_simulator
    cd "$SIMULATOR_ROOT"
    exec env NAV2_REFECTOR_ROOT="$NAV2_REFECTOR_ROOT" SIM_PROFILE="$SIM_PROFILE" bash scripts/launch_gazebo_rviz.sh
    ;;
  start)
    run_with_profile 'bash scripts/start_demo.sh'
    ;;
  multi)
    run_with_profile 'MULTI_NAV_API=1 bash scripts/start_demo.sh'
    ;;
  topics)
    require_simulator
    cd "$SIMULATOR_ROOT"
    exec bash scripts/check_ros_topics.sh
    ;;
  api)
    require_simulator
    cd "$SIMULATOR_ROOT"
    exec bash scripts/check_api.sh
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "[sim_ops] unknown command: $cmd" >&2
    usage >&2
    exit 2
    ;;
esac
