#!/usr/bin/env bash
# Repo-relative path helpers. Source from other scripts:
#   _SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
#   # shellcheck source=scripts/sim_paths.sh
#   source "$_SCRIPT_DIR/sim_paths.sh"
#   sim_paths_init "$_SCRIPT_DIR"

sim_paths_init() {
  local script_dir="${1:?script_dir required}"
  SIMULATOR_ROOT="${SIMULATOR_ROOT:-$(cd "$script_dir/.." && pwd)}"
  NAV2_REFECTOR_REL="../WS/nav2_REFECTOR"
  TURTLEBOT3_WS_REL="../turtlebot3_ws"
  DOCKER_NAV2_REFECTOR_ROOT="/workspace/nav2_REFECTOR"
  DOCKER_SIMULATOR_ROOT="/workspace/Simulator"
  ROS_SETUP="${ROS_SETUP:-/opt/ros/${ROS_DISTRO:-jazzy}/setup.bash}"
}

resolve_nav2_refector_root() {
  local candidate
  for candidate in \
    "${NAV2_REFECTOR_ROOT:-}" \
    "$SIMULATOR_ROOT/$NAV2_REFECTOR_REL" \
    "$SIMULATOR_ROOT/../nav2_REFECTOR" \
    "$DOCKER_NAV2_REFECTOR_ROOT" \
    "$HOME/WS/nav2_REFECTOR"; do
    if [[ -n "$candidate" && -d "$candidate/slam_nav_ws" ]]; then
      printf '%s\n' "$(cd "$candidate" && pwd)"
      return 0
    fi
  done
  return 1
}

resolve_turtlebot3_setup() {
  local candidate
  for candidate in \
    "${EXTRA_ROS_SETUP:-}" \
    "$SIMULATOR_ROOT/$TURTLEBOT3_WS_REL/install/setup.bash" \
    "$HOME/turtlebot3_ws/install/setup.bash"; do
    if [[ -n "$candidate" && -f "$candidate" ]]; then
      printf '%s\n' "$candidate"
      return 0
    fi
  done
  return 1
}

source_ros_stack() {
  if [[ -f "$ROS_SETUP" ]]; then
    set +u
    # shellcheck source=/dev/null
    source "$ROS_SETUP"
    set -u
  fi
  if [[ -f "$SIMULATOR_ROOT/deps_ws/install/setup.bash" ]]; then
    set +u
    # shellcheck source=/dev/null
    source "$SIMULATOR_ROOT/deps_ws/install/setup.bash"
    set -u
  fi
  local tb3_setup
  if tb3_setup="$(resolve_turtlebot3_setup 2>/dev/null)"; then
    set +u
    # shellcheck source=/dev/null
    source "$tb3_setup"
    set -u
  fi
}
