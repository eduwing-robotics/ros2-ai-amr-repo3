#!/usr/bin/env bash
# Nav PC에서 로봇 SBC bringup이 /odom, /scan 을 publish할 때까지 대기.
set -euo pipefail

DOMAIN="${1:-5}"
TIMEOUT_SEC="${2:-90}"
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
ROS_NETWORK_SETUP="${ROS_NETWORK_SETUP:-$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/setup_ros_robot_network_env.sh}"
TOPIC_PROBE_TIMEOUT_SEC="${TOPIC_PROBE_TIMEOUT_SEC:-10}"

set +eu
# shellcheck source=/dev/null
source "$ROS_SETUP" 2>/dev/null
# shellcheck source=/dev/null
source "$ROS_NETWORK_SETUP" 2>/dev/null
set -eu
if [[ "$DOMAIN" == "5" ]]; then
  export ROS_STATIC_PEERS="192.168.30.102"
elif [[ "$DOMAIN" == "2" ]]; then
  export ROS_STATIC_PEERS="192.168.30.101"
fi

deadline=$(( $(date +%s) + TIMEOUT_SEC ))
echo "[wait_robot] DOMAIN=$DOMAIN timeout=${TIMEOUT_SEC}s — /odom + /scan 대기..."

publisher_count() {
  timeout --kill-after=2 "$TOPIC_PROBE_TIMEOUT_SEC" ros2 topic info "$1" 2>/dev/null | awk '/Publisher count:/ {print $3; exit}'
}

while [[ $(date +%s) -lt $deadline ]]; do
  odom_ok=0 scan_ok=0
  odom_publishers="$(publisher_count /odom || true)"
  scan_publishers="$(publisher_count /scan || true)"
  [[ "${odom_publishers:-0}" =~ ^[1-9][0-9]*$ ]] && odom_ok=1
  [[ "${scan_publishers:-0}" =~ ^[1-9][0-9]*$ ]] && scan_ok=1
  if [[ $odom_ok -eq 1 && $scan_ok -eq 1 ]]; then
    echo "[wait_robot] OK — /odom + /scan publishers 확인"
    exit 0
  fi
  printf '[wait_robot] odom=%s scan=%s — 재시도...\n' "$([[ $odom_ok -eq 1 ]] && echo OK || echo -)" "$([[ $scan_ok -eq 1 ]] && echo OK || echo -)"
  sleep 3
done

echo "[wait_robot] TIMEOUT — bringup/ROS_DOMAIN_ID/네트워크 확인" >&2
exit 1
