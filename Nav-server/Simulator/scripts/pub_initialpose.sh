#!/usr/bin/env bash
# Publish /initialpose with the current simulation clock (required when use_sim_time:=true).
set -euo pipefail

X="${1:?x required}"
Y="${2:?y required}"
YAW="${3:-0}"

_SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/sim_paths.sh
source "$_SCRIPT_DIR/sim_paths.sh"
sim_paths_init "$_SCRIPT_DIR"
source_ros_stack

export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-2}"

read -r SEC NANOSEC < <(
  timeout 8 ros2 topic echo /clock --once 2>/dev/null |
    awk '/^[[:space:]]*sec:/{s=$2} /^[[:space:]]*nanosec:/{n=$2} END{if (s != "" && n != "") print s, n}'
)

if [[ -z "${SEC:-}" || -z "${NANOSEC:-}" ]]; then
  echo "[initialpose] failed to read /clock" >&2
  exit 1
fi

XY_VARIANCE="${INITIALPOSE_XY_VARIANCE:-0.0004}"
YAW_VARIANCE="${INITIALPOSE_YAW_VARIANCE:-0.0012}"
PAYLOAD="$(
  python3 - "$X" "$Y" "$YAW" "$SEC" "$NANOSEC" "$XY_VARIANCE" "$YAW_VARIANCE" <<'PY_PAYLOAD'
import math
import sys

x, y, yaw = map(float, sys.argv[1:4])
sec, nsec = int(sys.argv[4]), int(sys.argv[5])
xy_variance, yaw_variance = map(float, sys.argv[6:8])
qz = math.sin(yaw / 2.0)
qw = math.cos(yaw / 2.0)
print(
    "{header: {stamp: {sec: %d, nanosec: %d}, frame_id: map}, "
    "pose: {pose: {position: {x: %.6f, y: %.6f, z: 0.0}, "
    "orientation: {x: 0.0, y: 0.0, z: %.6f, w: %.6f}}, "
    "covariance: [%.6f, 0.0, 0.0, 0.0, 0.0, 0.0, "
    "0.0, %.6f, 0.0, 0.0, 0.0, 0.0, "
    "0.0, 0.0, 0.0, 0.0, 0.0, 0.0, "
    "0.0, 0.0, 0.0, 0.0, 0.0, 0.0, "
    "0.0, 0.0, 0.0, 0.0, 0.0, 0.0, "
    "0.0, 0.0, 0.0, 0.0, 0.0, %.6f]}}"
    % (sec, nsec, x, y, qz, qw, xy_variance, xy_variance, yaw_variance)
)
PY_PAYLOAD
)"

ros2 topic pub --once /initialpose geometry_msgs/msg/PoseWithCovarianceStamped "$PAYLOAD"
echo "[initialpose] published x=$X y=$Y yaw=$YAW stamp=$SEC.$NANOSEC"
