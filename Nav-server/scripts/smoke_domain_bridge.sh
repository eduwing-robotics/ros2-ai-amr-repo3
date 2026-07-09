#!/usr/bin/env bash
#
# Smoke test the center-domain command path through domain_bridge.
#
# Prerequisite in another terminal:
#   scripts/run_domain_bridges.sh --with-teleop
#
# This script publishes a command from center domain 1 and waits for /cmd_vel
# in the target robot domain.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
ROS_LOCALHOST_ONLY="${ROS_LOCALHOST_ONLY:-0}"
CENTER_DOMAIN="${CENTER_DOMAIN:-1}"
ECHO_TIMEOUT_SEC="${ECHO_TIMEOUT_SEC:-4}"

usage() {
  cat <<'EOF'
Usage:
  scripts/smoke_domain_bridge.sh [tb3_1|tb3_2|all]

Environment:
  ROS_SETUP           ROS setup path. Default: /opt/ros/jazzy/setup.bash
  CENTER_DOMAIN       Center domain for command publishing. Default: 1
  ROS_LOCALHOST_ONLY  ROS localhost setting. Default: 0
  ECHO_TIMEOUT_SEC    Seconds to wait for /cmd_vel. Default: 4

Prerequisite:
  scripts/run_domain_bridges.sh --with-teleop
EOF
}

TARGET="${1:-all}"

if [[ "$TARGET" == "-h" || "$TARGET" == "--help" ]]; then
  usage
  exit 0
fi

if [[ ! -f "$ROS_SETUP" ]]; then
  echo "[smoke_domain_bridge] missing ROS setup: $ROS_SETUP" >&2
  exit 1
fi

# shellcheck source=/dev/null
set +u
source "$ROS_SETUP"
set -u
export ROS_LOCALHOST_ONLY

smoke_one() {
  local bridge_robot_id="$1"
  local domain_id="$2"
  local command="$3"
  local log_file

  log_file="$(mktemp)"
  echo "[smoke_domain_bridge] testing ${bridge_robot_id}: center ${CENTER_DOMAIN} -> robot domain ${domain_id}"

  ROS_DOMAIN_ID="$domain_id" timeout "$ECHO_TIMEOUT_SEC" ros2 topic echo --once /cmd_vel >"$log_file" 2>&1 &
  local echo_pid=$!

  sleep 0.5
  CENTER_DOMAIN="$CENTER_DOMAIN" "$SCRIPT_DIR/send_bridge_command.sh" "$bridge_robot_id" "$command" >/dev/null 2>&1

  if wait "$echo_pid"; then
    CENTER_DOMAIN="$CENTER_DOMAIN" "$SCRIPT_DIR/send_bridge_command.sh" "$bridge_robot_id" stop >/dev/null
    echo "[smoke_domain_bridge] PASS ${bridge_robot_id}"
    rm -f "$log_file"
    return 0
  fi

  CENTER_DOMAIN="$CENTER_DOMAIN" "$SCRIPT_DIR/send_bridge_command.sh" "$bridge_robot_id" stop >/dev/null || true
  echo "[smoke_domain_bridge] FAIL ${bridge_robot_id}: no /cmd_vel received in domain ${domain_id}" >&2
  sed -n '1,120p' "$log_file" >&2
  rm -f "$log_file"
  return 1
}

case "$TARGET" in
  tb3_1)
    smoke_one tb3_1 2 forward
    ;;
  tb3_2)
    smoke_one tb3_2 5 left
    ;;
  all)
    smoke_one tb3_1 2 forward
    smoke_one tb3_2 5 left
    ;;
  *)
    echo "[smoke_domain_bridge] unknown target: $TARGET" >&2
    usage >&2
    exit 2
    ;;
esac
