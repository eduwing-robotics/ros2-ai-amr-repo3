#!/usr/bin/env bash
#
# Start domain_bridge processes for the logistics Nav server topology.
#
# Default behavior starts only the domain bridges:
#   center domain 1 -> robot domains 2 and 5 for teleop command topics
#   robot domains 2 and 5 -> center domain 1 for camera topics
#
# Optional teleop adapters can be started for manual movement testing when a
# standalone teleop_adapter.py path is provided.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BRIDGE_DIR="${BRIDGE_DIR:-$ROOT/config/domain_bridge}"
ROBOTS_CONFIG="${ROBOTS_CONFIG:-$ROOT/config/robots.json}"
VALIDATOR="${VALIDATOR:-$SCRIPT_DIR/validate_robot_domains.py}"
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
ROS_LOCALHOST_ONLY="${ROS_LOCALHOST_ONLY:-0}"
START_TELEOP_ADAPTERS="${START_TELEOP_ADAPTERS:-0}"
TELEOP_ADAPTER_PATH="${TELEOP_ADAPTER_PATH:-}"

BRIDGE_FILES=(
  "center_to_tb3_1.yaml"
  "center_to_tb3_2.yaml"
  "tb3_1_to_center.yaml"
  "tb3_2_to_center.yaml"
)

pids=()

usage() {
  cat <<'EOF'
Usage:
  scripts/run_domain_bridges.sh [--with-teleop] [--bridges-only]

Environment:
  ROS_SETUP              ROS setup path. Default: /opt/ros/jazzy/setup.bash
  ROS_LOCALHOST_ONLY     ROS localhost setting. Default: 0
  BRIDGE_DIR             domain_bridge YAML directory
  ROBOTS_CONFIG          robots.json path
  START_TELEOP_ADAPTERS  1 to start teleop adapters, 0 to skip
  TELEOP_ADAPTER_PATH    path to standalone teleop_adapter.py when teleop is enabled

Examples:
  scripts/run_domain_bridges.sh
  START_TELEOP_ADAPTERS=1 TELEOP_ADAPTER_PATH="/path/to/teleop_adapter.py" scripts/run_domain_bridges.sh
EOF
}

cleanup() {
  if ((${#pids[@]} > 0)); then
    echo
    echo "[domain_bridge] stopping child processes..."
    kill "${pids[@]}" 2>/dev/null || true
    wait 2>/dev/null || true
  fi
}

require_file() {
  local path="$1"
  local label="$2"
  if [[ ! -f "$path" ]]; then
    echo "[domain_bridge] missing ${label}: $path" >&2
    exit 1
  fi
}

start_bridge() {
  local yaml="$1"
  echo "[domain_bridge] starting $yaml"
  ros2 run domain_bridge domain_bridge "$BRIDGE_DIR/$yaml" &
  pids+=("$!")
}

start_teleop_adapter() {
  local domain_id="$1"
  local robot_id="$2"
  local command_topic="$3"

  echo "[teleop_adapter] starting $robot_id on ROS_DOMAIN_ID=$domain_id"
  ROS_DOMAIN_ID="$domain_id" python3 "$TELEOP_ADAPTER_PATH" --ros-args \
    -p robot_id:="$robot_id" \
    -p command_topic:="$command_topic" \
    -p cmd_vel_topic:=/cmd_vel \
    -p use_stamped:=true &
  pids+=("$!")
}

while (($# > 0)); do
  case "$1" in
    --with-teleop)
      START_TELEOP_ADAPTERS=1
      ;;
    --bridges-only)
      START_TELEOP_ADAPTERS=0
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[domain_bridge] unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

trap cleanup EXIT INT TERM

require_file "$ROS_SETUP" "ROS setup"
require_file "$ROBOTS_CONFIG" "robots config"
require_file "$VALIDATOR" "domain validator"

for bridge_file in "${BRIDGE_FILES[@]}"; do
  require_file "$BRIDGE_DIR/$bridge_file" "bridge config"
done

python3 "$VALIDATOR" --config "$ROBOTS_CONFIG" --bridge-dir "$BRIDGE_DIR"

# shellcheck source=/dev/null
set +u
source "$ROS_SETUP"
set -u
export ROS_LOCALHOST_ONLY

if ! command -v ros2 >/dev/null 2>&1; then
  echo "[domain_bridge] ros2 command not found after sourcing $ROS_SETUP" >&2
  exit 1
fi

if ! ros2 pkg prefix domain_bridge >/dev/null 2>&1; then
  echo "[domain_bridge] ROS package not found: domain_bridge" >&2
  echo "[domain_bridge] install prerequisite: sudo apt install -y ros-jazzy-domain-bridge" >&2
  exit 1
fi

echo "[domain_bridge] starting bridges from $BRIDGE_DIR"
for bridge_file in "${BRIDGE_FILES[@]}"; do
  start_bridge "$bridge_file"
done

if [[ "$START_TELEOP_ADAPTERS" == "1" ]]; then
  require_file "$TELEOP_ADAPTER_PATH" "teleop adapter"
  start_teleop_adapter 2 "tb3_1" "/mission/tb3_1/teleop_cmd"
  start_teleop_adapter 5 "tb3_2" "/mission/tb3_2/teleop_cmd"
else
  echo "[teleop_adapter] skipped. Set START_TELEOP_ADAPTERS=1 and TELEOP_ADAPTER_PATH to enable."
fi

echo "[domain_bridge] up. center=domain1, tb3_1=domain2, tb3_2=domain5. Ctrl+C to stop."
wait
