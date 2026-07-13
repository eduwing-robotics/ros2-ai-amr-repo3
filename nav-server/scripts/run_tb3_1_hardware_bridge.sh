#!/usr/bin/env bash
# Bridge only robot1 hardware topics between ROS domains 2 and 42.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
BRIDGE_CONFIG="${BRIDGE_CONFIG:-$ROOT/config/domain_bridge/tb3_1_hardware_nav.yaml}"
ROBOT_PEER="${ROBOT_PEER:-smartfactory-robot1.local}"
mode=run

usage() {
  cat <<'EOF'
Usage:
  scripts/run_tb3_1_hardware_bridge.sh [--check|--print-plan]

The bridge exposes robot1 sensors from hardware domain 2 to local Nav domain
42 and returns only /cmd_vel. It never starts robot2 or publishes movement.
EOF
}

while (($# > 0)); do
  case "$1" in
    --check) mode=check ;;
    --print-plan) mode=print-plan ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[tb3_1_bridge] unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

[[ -f "$ROS_SETUP" ]] || { echo "[tb3_1_bridge] missing ROS setup: $ROS_SETUP" >&2; exit 1; }
[[ -f "$BRIDGE_CONFIG" ]] || { echo "[tb3_1_bridge] missing config: $BRIDGE_CONFIG" >&2; exit 1; }

if [[ "$mode" == print-plan ]]; then
  printf 'robot=tb3_1 hardware_domain=2 nav_domain=42 peer=%s config=%s\n' "$ROBOT_PEER" "$BRIDGE_CONFIG"
  exit 0
fi

# shellcheck source=/dev/null
set +u
source "$ROS_SETUP"
set -u
export RMW_IMPLEMENTATION=rmw_cyclonedds_cpp
export ROS_STATIC_PEERS="$ROBOT_PEER"
export SMARTFACTORY_DDS_ROUTE_PROBE="$ROBOT_PEER"
export SMARTFACTORY_DDS_PEER_MODE=lan

# Include both robot1 and this PC. Domain 2 reaches the SBC; domain 42 reaches
# local Nav/API/RViz participants without multicast discovery.
# shellcheck source=configure_cyclonedds_lan.sh
source "$SCRIPT_DIR/configure_cyclonedds_lan.sh"
export ROS_STATIC_PEERS="${ROBOT_PEER};${SMARTFACTORY_DDS_LAN_ADDRESS}"
source "$SCRIPT_DIR/configure_cyclonedds_lan.sh"

ros2 pkg prefix domain_bridge >/dev/null 2>&1 || {
  echo "[tb3_1_bridge] install prerequisite: sudo apt install -y ros-jazzy-domain-bridge" >&2
  exit 1
}

if [[ "$mode" == check ]]; then
  echo "[tb3_1_bridge] preflight OK: domain2<->domain42 peer=${ROBOT_PEER}"
  exit 0
fi

lock_dir="${XDG_RUNTIME_DIR:-/tmp}/smartfactory-domain-bridge"
mkdir -p "$lock_dir"
exec 9>"$lock_dir/tb3_1-hardware-nav.lock"
flock -n 9 || { echo "[tb3_1_bridge] already running" >&2; exit 1; }

echo "[tb3_1_bridge] starting domain2<->domain42: $BRIDGE_CONFIG"
exec ros2 run domain_bridge domain_bridge "$BRIDGE_CONFIG"
