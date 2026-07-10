#!/usr/bin/env bash
# tb3_2 로봇 SBC 카메라만 재기동 (bringup/Nav PC 스택 유지)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROBOT_SBC_DIR="$SCRIPT_DIR/robot_sbc"
# shellcheck source=lib/local_hardware.sh
source "$SCRIPT_DIR/lib/local_hardware.sh"
load_local_hardware_env
ROBOT_SSH="${ROBOT_SSH:-musk@192.168.30.102}"
DOMAIN="${DOMAIN:-5}"
WS_SETUP="${ROBOT_WS_SETUP:?ROBOT_WS_SETUP must point to the SBC TurtleBot3 overlay setup.bash}"
BRINGUP_WAIT_SEC="${BRINGUP_WAIT_SEC:-3}"

configure_robot_ssh 8

echo "[restart_camera] stop camera on $ROBOT_SSH"
"${SSH_CMD[@]}" "$ROBOT_SSH" "bash -s" <"$ROBOT_SBC_DIR/stop_camera.sh"

echo "[restart_camera] start camera (foreground — Ctrl+C to stop)"
"${SSH_CMD[@]}" "$ROBOT_SSH" \
  env "ROS_DOMAIN_ID=$DOMAIN" "BRINGUP_WAIT_SEC=$BRINGUP_WAIT_SEC" "WS_SETUP=$WS_SETUP" CAMERA_START_RETRIES=3 bash -s \
  <"$ROBOT_SBC_DIR/start_camera.sh"
