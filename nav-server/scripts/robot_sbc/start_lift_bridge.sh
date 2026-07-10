#!/usr/bin/env bash
# 로봇 SBC lift_bridge (Arduino Uno). Nav PC에서 ssh로 호출.
set -eo pipefail

DOMAIN="${ROS_DOMAIN_ID:-5}"
LIFT_WS_SETUP="${LIFT_WS_SETUP:?LIFT_WS_SETUP must point to the SBC lift overlay setup.bash}"
LIFT_BRIDGE_PKG="${LIFT_BRIDGE_PKG:-lift_bridge}"
LIFT_SERIAL_PORT="${LIFT_SERIAL_PORT:-}"

source /opt/ros/jazzy/setup.bash
if [[ ! -f "$LIFT_WS_SETUP" ]]; then
  echo "[robot_sbc] ERROR: lift workspace overlay not found: $LIFT_WS_SETUP" >&2
  exit 1
fi
# shellcheck source=/dev/null
source "$LIFT_WS_SETUP"

export ROS_DOMAIN_ID="$DOMAIN"
export TURTLEBOT3_MODEL=burger

echo "[robot_sbc] lift_bridge start DOMAIN=$DOMAIN"
echo "[robot_sbc] lift_ws=$LIFT_WS_SETUP"

ros_args=()
if [[ -n "$LIFT_SERIAL_PORT" ]]; then
  echo "[robot_sbc] arduino port=$LIFT_SERIAL_PORT"
  ros_args+=(--ros-args -p "port:=${LIFT_SERIAL_PORT}")
fi

exec ros2 run "$LIFT_BRIDGE_PKG" lift_bridge "${ros_args[@]}"
