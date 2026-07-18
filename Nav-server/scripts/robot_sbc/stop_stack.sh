#!/usr/bin/env bash
# 로봇 SBC에서 bringup/카메라 프로세스를 정리한다. (Nav PC에서 ssh로 호출)
set -eo pipefail

echo "[robot_sbc] stopping bringup/camera/lift..."
patterns=(
  "lift_bridge"
  "lift_monitor"
  "lift_teleop"
  "turtlebot3_ros"
  "robot_state_publisher"
  "single_coin_d4_node"
  "turtlebot3_bringup.*robot.launch"
  "ros2 launch turtlebot3_bringup robot.launch.py"
)
for pattern in "${patterns[@]}"; do
  pkill -TERM -f "$pattern" 2>/dev/null || true
done
sleep 3
for pattern in "${patterns[@]}"; do
  pkill -KILL -f "$pattern" 2>/dev/null || true
done
for device in \
  /dev/serial/by-id/usb-ROBOTIS_OpenCR_Virtual_ComPort_in_FS_Mode_FFFFFFFEFFFF-if00 \
  /dev/tb3_lidar /dev/ttyUSB0; do
  [[ -e "$device" ]] || continue
  fuser -k "$device" >/dev/null 2>&1 || true
done
rm -f /tmp/tb3_bringup.lock
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
bash "$SCRIPT_DIR/stop_camera.sh" 2>/dev/null || true
remaining=$(pgrep -fc "turtlebot3_ros|single_coin_d4_node|turtlebot3_bringup.*robot.launch|ros2 launch turtlebot3_bringup robot.launch.py" 2>/dev/null || true)
echo "[robot_sbc] stop complete (remaining bringup processes=${remaining:-0})"
