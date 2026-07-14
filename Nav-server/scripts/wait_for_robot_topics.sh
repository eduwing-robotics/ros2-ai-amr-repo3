#!/usr/bin/env bash
# Nav PC에서 로봇 SBC bringup이 /odom, /scan 을 publish할 때까지 대기.
set -euo pipefail

DOMAIN="${1:-5}"
TIMEOUT_SEC="${2:-90}"
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"

# shellcheck source=/dev/null
source "$ROS_SETUP" 2>/dev/null || true
export ROS_DOMAIN_ID="$DOMAIN"

deadline=$(( $(date +%s) + TIMEOUT_SEC ))
echo "[wait_robot] DOMAIN=$DOMAIN timeout=${TIMEOUT_SEC}s — /odom + /scan 대기..."

while [[ $(date +%s) -lt $deadline ]]; do
  odom_ok=0 scan_ok=0
  if timeout 4 ros2 topic echo /odom --once >/dev/null 2>&1; then odom_ok=1; fi
  if timeout 4 ros2 topic echo /scan --once --qos-reliability best_effort >/dev/null 2>&1; then scan_ok=1; fi
  if [[ $odom_ok -eq 1 && $scan_ok -eq 1 ]]; then
    echo "[wait_robot] OK — /odom + /scan 수신"
    exit 0
  fi
  printf '[wait_robot] odom=%s scan=%s — 재시도...\n' "$([[ $odom_ok -eq 1 ]] && echo OK || echo -)" "$([[ $scan_ok -eq 1 ]] && echo OK || echo -)"
  sleep 3
done

echo "[wait_robot] TIMEOUT — bringup/ROS_DOMAIN_ID/네트워크 확인" >&2
exit 1
