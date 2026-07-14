#!/usr/bin/env bash
# Nav PC ROS 2 DDS discovery env — delegates to ~/ros2_env.sh when present.
# source scripts/setup_ros_robot_network_env.sh

if [[ -f "$HOME/ros2_env.sh" ]]; then
  # shellcheck source=/dev/null
  source "$HOME/ros2_env.sh"
else
  export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
  unset ROS_LOCALHOST_ONLY
  export ROS_AUTOMATIC_DISCOVERY_RANGE="${ROS_AUTOMATIC_DISCOVERY_RANGE:-SUBNET}"
  export ROS_STATIC_PEERS="${ROS_STATIC_PEERS:-192.168.30.101;192.168.30.102;192.168.30.9;192.168.30.5;192.168.30.12;192.168.30.3}"
  if [[ -f "$HOME/.ros/fastdds_ghost_fix.xml" ]]; then
    export FASTRTPS_DEFAULT_PROFILES_FILE="$HOME/.ros/fastdds_ghost_fix.xml"
  fi
fi
