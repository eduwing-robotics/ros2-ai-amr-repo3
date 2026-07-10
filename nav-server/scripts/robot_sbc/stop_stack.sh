#!/usr/bin/env bash
# 로봇 SBC에서 bringup/카메라 프로세스를 정리한다. (Nav PC에서 ssh로 호출)
set -eo pipefail

echo "[robot_sbc] stopping bringup/camera/lift..."
pkill -f "lift_bridge" 2>/dev/null || true
pkill -f "lift_monitor" 2>/dev/null || true
pkill -f "lift_teleop" 2>/dev/null || true
pkill -f "turtlebot3_ros" 2>/dev/null || true
pkill -f "robot_state_publisher" 2>/dev/null || true
pkill -f "single_coin_d4" 2>/dev/null || true
pkill -f "turtlebot3_bringup.*robot.launch" 2>/dev/null || true
pkill -f "robot.launch.py" 2>/dev/null || true
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "$SCRIPT_DIR/stop_camera.sh" 2>/dev/null || true
echo "[robot_sbc] stop complete"
