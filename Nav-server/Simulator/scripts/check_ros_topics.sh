#!/usr/bin/env bash
set -euo pipefail

ROS_SETUP="${ROS_SETUP:-/opt/ros/${ROS_DISTRO:-jazzy}/setup.bash}"
TIMEOUT_SEC="${TIMEOUT_SEC:-20}"

if [[ -f "$ROS_SETUP" ]]; then
  # shellcheck source=/dev/null
  source "$ROS_SETUP"
fi

required_topics=(/cmd_vel /scan /odom /tf)
deadline=$((SECONDS + TIMEOUT_SEC))
missing=("${required_topics[@]}")

while (( SECONDS < deadline )); do
  mapfile -t topics < <(ros2 topic list 2>/dev/null || true)
  missing=()
  for topic in "${required_topics[@]}"; do
    found=0
    for seen in "${topics[@]}"; do
      if [[ "$seen" == "$topic" ]]; then
        found=1
        break
      fi
    done
    if (( ! found )); then
      missing+=("$topic")
    fi
  done

  if ((${#missing[@]} == 0)); then
    echo "ROS topic check passed: ${required_topics[*]}"
    exit 0
  fi

  sleep 1
done

echo "ROS topic check failed. Missing: ${missing[*]}" >&2
echo "Current topics:" >&2
ros2 topic list >&2 || true
exit 1