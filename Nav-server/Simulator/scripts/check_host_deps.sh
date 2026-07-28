#!/usr/bin/env bash
set -euo pipefail

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/sim_paths.sh
source "$_SCRIPT_DIR/sim_paths.sh"
sim_paths_init "$_SCRIPT_DIR"

missing=0

check_cmd() {
  if command -v "$1" >/dev/null 2>&1; then
    echo "OK  command: $1"
  else
    echo "MISS command: $1" >&2
    missing=1
  fi
}

check_ros_pkg() {
  if ros2 pkg prefix "$1" >/dev/null 2>&1; then
    echo "OK  ros pkg: $1"
  else
    echo "MISS ros pkg: $1" >&2
    missing=1
  fi
}

check_python() {
  if python3 -c "import $1" >/dev/null 2>&1; then
    echo "OK  python: $1"
  else
    echo "MISS python: $1" >&2
    missing=1
  fi
}

source_ros_stack

echo "== host dependency check =="
check_cmd ros2
check_cmd gz
check_cmd python3
check_cmd curl
check_cmd jq
check_ros_pkg ros_gz_sim
check_ros_pkg ros_gz_bridge
check_ros_pkg turtlebot3_gazebo
check_ros_pkg turtlebot3_navigation2
check_python fastapi
check_python uvicorn

if resolve_nav2_refector_root >/dev/null; then
  echo "OK  nav2_REFECTOR: $(resolve_nav2_refector_root)"
else
  echo "MISS nav2_REFECTOR (expected ../WS/nav2_REFECTOR or NAV2_REFECTOR_ROOT)" >&2
  missing=1
fi

if (( missing )); then
  echo >&2
  echo "Install hints:" >&2
  echo "  sudo apt install ros-jazzy-turtlebot3-gazebo ros-jazzy-turtlebot3-navigation2" >&2
  echo "  pip3 install --user fastapi uvicorn requests pydantic" >&2
  exit 1
fi

echo "host dependencies look ready"
