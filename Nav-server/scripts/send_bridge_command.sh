#!/usr/bin/env bash
#
# Publish a manual teleop command through the center ROS domain.

set -euo pipefail

ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
CENTER_DOMAIN="${CENTER_DOMAIN:-1}"
ROS_LOCALHOST_ONLY="${ROS_LOCALHOST_ONLY:-0}"

usage() {
  cat <<'EOF'
Usage:
  scripts/send_bridge_command.sh <bridge_robot_id> <command> [rate_hz]

Commands:
  forward | backward | left | right | stop

Examples:
  scripts/send_bridge_command.sh tb3_1 forward
  scripts/send_bridge_command.sh tb3_2 left 10
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if (($# < 2 || $# > 3)); then
  usage >&2
  exit 2
fi

ROBOT="$1"
COMMAND="$2"
RATE="${3:-}"
TOPIC="/mission/${ROBOT}/teleop_cmd"
PAYLOAD="{data: '{\"robot_id\":\"${ROBOT}\",\"command\":\"${COMMAND}\"}'}"

case "$COMMAND" in
  forward|backward|left|right|stop) ;;
  *)
    echo "[send_bridge_command] unsupported command: $COMMAND" >&2
    usage >&2
    exit 2
    ;;
esac

if [[ ! -f "$ROS_SETUP" ]]; then
  echo "[send_bridge_command] missing ROS setup: $ROS_SETUP" >&2
  exit 1
fi

# shellcheck source=/dev/null
set +u
source "$ROS_SETUP"
set -u
export ROS_DOMAIN_ID="$CENTER_DOMAIN"
export ROS_LOCALHOST_ONLY

if [[ -n "$RATE" ]]; then
  echo "[send_bridge_command] ${ROBOT} <- ${COMMAND} @ ${RATE}Hz on center domain ${CENTER_DOMAIN}"
  ros2 topic pub -r "$RATE" "$TOPIC" std_msgs/msg/String "$PAYLOAD"
else
  echo "[send_bridge_command] ${ROBOT} <- ${COMMAND} once on center domain ${CENTER_DOMAIN}"
  ros2 topic pub --once "$TOPIC" std_msgs/msg/String "$PAYLOAD"
fi
