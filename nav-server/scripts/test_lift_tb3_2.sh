#!/usr/bin/env bash
# tb3_2 lift topic smoke test (ROS domain 5). Bridge must run on robot SBC first.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
DOMAIN="${ROS_DOMAIN_ID:-5}"

usage() {
  cat <<'EOF'
Usage:
  scripts/test_lift_tb3_2.sh status          # /lift/* pub/sub counts
  scripts/test_lift_tb3_2.sh move <mm>       # publish /lift/cmd_move once
  scripts/test_lift_tb3_2.sh home            # publish /lift/cmd_home
  scripts/test_lift_tb3_2.sh stop            # publish /lift/cmd_stop

Requires: lift_bridge on robot SBC (ROS_DOMAIN_ID=5)
Safety: start with low mm (e.g. 20) before 43mm load height.
EOF
}

source_ros() {
  set +u
  # shellcheck source=/dev/null
  source "$ROS_SETUP"
  set -u
  export ROS_DOMAIN_ID="$DOMAIN"
}

topic_info() {
  local topic="$1"
  echo "== $topic =="
  timeout 4 ros2 topic info "$topic" -v 2>/dev/null || echo "(no topic / timeout)"
  echo
}

cmd_status() {
  source_ros
  topic_info /lift/cmd_move
  topic_info /lift/position
  topic_info /lift/direction
  topic_info /lift/limit_lower
  local subs
  subs=$(timeout 4 ros2 topic info /lift/cmd_move 2>/dev/null | awk '/Subscription count:/ {print $3}' | head -1)
  if [[ "${subs:-0}" -ge 1 ]]; then
    echo "OK: lift_bridge subscriber on /lift/cmd_move"
    return 0
  fi
  echo "FAIL: no subscriber on /lift/cmd_move — start lift_bridge on SBC (domain $DOMAIN)" >&2
  return 1
}

cmd_move() {
  local mm="${1:?usage: move <mm>}"
  mm="${mm%mm}"   # allow "20" or "20mm"
  source_ros
  echo "[lift_test] cmd_move ${mm}mm (domain $DOMAIN)"
  ros2 topic pub --once /lift/cmd_move std_msgs/msg/Float32 "{data: ${mm}}"
}

cmd_home() {
  source_ros
  echo "[lift_test] cmd_home (domain $DOMAIN)"
  ros2 topic pub --once /lift/cmd_home std_msgs/msg/Bool "{data: true}"
}

cmd_stop() {
  source_ros
  echo "[lift_test] cmd_stop (domain $DOMAIN)"
  ros2 topic pub --once /lift/cmd_stop std_msgs/msg/Bool "{data: true}"
}

main="${1:-status}"
case "$main" in
  status) cmd_status ;;
  move) shift; cmd_move "$@" ;;
  home) cmd_home ;;
  stop) cmd_stop ;;
  -h|--help|help) usage ;;
  *) usage; exit 2 ;;
esac
