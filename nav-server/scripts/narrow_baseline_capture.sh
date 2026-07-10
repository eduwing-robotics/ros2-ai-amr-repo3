#!/usr/bin/env bash
# Capture narrow-space drive baseline snapshot (env, QoS, optional bag).
# Usage: scripts/narrow_baseline_capture.sh [bag_seconds]
set -euo pipefail

BAG_SEC="${1:-60}"
LOG_ROOT="${LOG_ROOT:-$HOME/narrow_logs}"
LOG_DIR="$LOG_ROOT/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$LOG_DIR"

source /opt/ros/jazzy/setup.bash 2>/dev/null || true
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-5}"

echo "[narrow_baseline] writing to $LOG_DIR"

{
  date
  hostname
  uname -a
  lsb_release -ds 2>/dev/null || true
  printenv | grep -E '^(ROS|RMW|CYCLONE|FAST|DDS|TURTLEBOT)' | sort
  ros2 node list 2>/dev/null || true
  ros2 topic list 2>/dev/null || true
  ros2 doctor --report 2>/dev/null || true
} | tee "$LOG_DIR/env_graph.txt"

for t in /scan /odom /tf /cmd_vel; do
  ros2 topic info "$t" -v 2>&1 | tee "$LOG_DIR/qos_${t//\//_}.txt" >/dev/null || true
done

if command -v ros2 >/dev/null && ros2 bag record --help 2>&1 | grep -q mcap; then
  echo "[narrow_baseline] recording ${BAG_SEC}s MCAP bag..."
  timeout "$((BAG_SEC + 5))" ros2 bag record -s mcap -o "$LOG_DIR/run" \
    /scan /odom /tf /tf_static /amcl_pose /cmd_vel /cmd_vel_smoothed \
    /local_costmap/costmap /collision_monitor_state 2>/dev/null || true
fi

echo "[narrow_baseline] done: $LOG_DIR"
