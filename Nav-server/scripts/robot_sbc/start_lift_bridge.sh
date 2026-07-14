#!/usr/bin/env bash
# 로봇 SBC lift_bridge (Arduino Uno). Nav PC에서 ssh로 호출.
set -eo pipefail

DOMAIN="${ROS_DOMAIN_ID:-5}"
LIFT_WS="${LIFT_WS_SETUP:-$HOME/lift_project/ros2_ws/install/setup.bash}"
LIFT_BRIDGE_PKG="${LIFT_BRIDGE_PKG:-lift_bridge}"
LIFT_SERIAL_PORT="${LIFT_SERIAL_PORT:-}"

source /opt/ros/jazzy/setup.bash
if [[ ! -f "$LIFT_WS" ]]; then
  echo "[robot_sbc] ERROR: lift workspace not found: $LIFT_WS" >&2
  echo "[robot_sbc] SBC에 ~/lift_project 배포 후 colcon build, 또는 LIFT_WS_SETUP 지정" >&2
  exit 1
fi
# shellcheck source=/dev/null
source "$LIFT_WS"
# Match Nav PC DDS discovery (LOCALHOST + static peers)
if [[ -f "$HOME/ros2_env.sh" ]]; then
  # shellcheck source=/dev/null
  source "$HOME/ros2_env.sh"
fi
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
unset ROS_LOCALHOST_ONLY
export ROS_AUTOMATIC_DISCOVERY_RANGE="${ROS_AUTOMATIC_DISCOVERY_RANGE:-SUBNET}"
export ROS_STATIC_PEERS="${ROS_STATIC_PEERS:-192.168.30.101;192.168.30.102;192.168.30.9;192.168.30.5;192.168.30.12;192.168.30.3}"

export ROS_DOMAIN_ID="$DOMAIN"
export TURTLEBOT3_MODEL=burger

resolve_arduino_port() {
  local p
  # Prefer explicit override
  if [[ -n "$LIFT_SERIAL_PORT" ]]; then
    printf '%s' "$LIFT_SERIAL_PORT"
    return 0
  fi
  # Any Arduino Uno / CDC ACM by-id (robot-specific serial changes)
  shopt -s nullglob
  for p in /dev/serial/by-id/usb-Arduino* /dev/serial/by-id/usb-*Arduino*; do
    if [[ -e "$p" ]]; then
      printf '%s' "$p"
      return 0
    fi
  done
  return 1
}

PORT="$(resolve_arduino_port || true)"
if [[ -z "$PORT" ]]; then
  echo "[robot_sbc] ERROR: Arduino (lift) USB not found on this SBC" >&2
  echo "[robot_sbc] /dev/serial/by-id 목록:" >&2
  ls -la /dev/serial/by-id/ 2>&1 | sed 's/^/[robot_sbc]   /' >&2 || true
  echo "[robot_sbc] 리프트 Uno를 꽂거나, 없으면 WITH_LIFT=0 으로 기동하세요." >&2
  exit 1
fi

echo "[robot_sbc] lift_bridge start DOMAIN=$DOMAIN"
echo "[robot_sbc] lift_ws=$LIFT_WS"
echo "[robot_sbc] arduino port=$PORT"

exec ros2 run "$LIFT_BRIDGE_PKG" lift_bridge --ros-args -p "port:=${PORT}"
