#!/usr/bin/env bash
# Nav PC ROS 2 DDS discovery env — delegates to ~/ros2_env.sh when present.
# source scripts/setup_ros_robot_network_env.sh

if [[ -f "$HOME/ros2_env.sh" ]]; then
  # shellcheck source=/dev/null
  source "$HOME/ros2_env.sh"
else
  export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
  unset ROS_LOCALHOST_ONLY
  if [[ -f "$HOME/slam_nav_ws/config/fastdds_robot_network.xml" ]]; then
    export FASTRTPS_DEFAULT_PROFILES_FILE="$HOME/slam_nav_ws/config/fastdds_robot_network.xml"
  fi
fi
# Avoid subnet-wide DDS multicast storms on the robot Wi-Fi. Local processes
# discover each other on localhost; the two robot SBCs are explicit peers.
export ROS_AUTOMATIC_DISCOVERY_RANGE="${ROBOT_NETWORK_DISCOVERY_RANGE:-LOCALHOST}"
export ROS_STATIC_PEERS="${ROBOT_NETWORK_STATIC_PEERS:-192.168.30.101;192.168.30.102;192.168.30.12}"
