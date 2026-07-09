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

export ROS_DOMAIN_ID="$DOMAIN"
export TURTLEBOT3_MODEL=burger

echo "[robot_sbc] lift_bridge start DOMAIN=$DOMAIN"
echo "[robot_sbc] lift_ws=$LIFT_WS"

ros_args=()
if [[ -n "$LIFT_SERIAL_PORT" ]]; then
  echo "[robot_sbc] arduino port=$LIFT_SERIAL_PORT"
  ros_args+=(--ros-args -p "port:=${LIFT_SERIAL_PORT}")
fi

exec ros2 run "$LIFT_BRIDGE_PKG" lift_bridge "${ros_args[@]}"
