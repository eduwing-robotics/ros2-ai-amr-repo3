#!/usr/bin/env bash
# tb3_2 로봇 SBC 카메라만 재기동 (bringup/Nav PC 스택 유지)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROBOT_SBC_DIR="$SCRIPT_DIR/robot_sbc"
ROBOT_SSH="${ROBOT_SSH:-musk@192.168.30.102}"
ROBOT_PW="${ROBOT_PW:?Set ROBOT_PW in the environment}"
DOMAIN="${DOMAIN:-5}"
WS_SETUP="${ROBOT_WS_SETUP:-/home/musk/turtlebot3_ws/install/setup.bash}"
BRINGUP_WAIT_SEC="${BRINGUP_WAIT_SEC:-3}"

if command -v sshpass >/dev/null 2>&1 && [[ -n "$ROBOT_PW" ]]; then
  SSH_CMD=(sshpass -p "$ROBOT_PW" ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8)
else
  SSH_CMD=(ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8)
fi

echo "[restart_camera] stop camera on $ROBOT_SSH"
"${SSH_CMD[@]}" "$ROBOT_SSH" "bash -s" <"$ROBOT_SBC_DIR/stop_camera.sh"

echo "[restart_camera] start camera (foreground — Ctrl+C to stop)"
"${SSH_CMD[@]}" "$ROBOT_SSH" \
  "export ROS_DOMAIN_ID=$DOMAIN BRINGUP_WAIT_SEC=$BRINGUP_WAIT_SEC WS_SETUP='$WS_SETUP' CAMERA_START_RETRIES=3; bash -s" \
  <"$ROBOT_SBC_DIR/start_camera.sh"
