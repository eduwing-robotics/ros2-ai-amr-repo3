#!/usr/bin/env bash
# picamera2 퍼블리셔를 로봇 SBC에 배포 (terminator camera pane 선행 조건)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# Caller (start_all_tb3_*.sh) must export ROBOT_SSH / ROBOT_PW for the target robot.
ROBOT_SSH="${ROBOT_SSH:-musk@192.168.30.102}"
ROBOT_PW="${ROBOT_PW:?Set ROBOT_PW in the environment}"
REMOTE_DIR="${REMOTE_DIR:-~/slam_nav_camera_fix}"

if command -v sshpass >/dev/null 2>&1 && [[ -n "$ROBOT_PW" ]]; then
  SSH_CMD=(sshpass -p "$ROBOT_PW" ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8)
  SCP_CMD=(sshpass -p "$ROBOT_PW" scp -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8)
else
  SSH_CMD=(ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8)
  SCP_CMD=(scp -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8)
fi

echo "[deploy_camera] target=$ROBOT_SSH dir=$REMOTE_DIR"
"${SSH_CMD[@]}" "$ROBOT_SSH" "mkdir -p $REMOTE_DIR"
"${SCP_CMD[@]}" \
  "$SCRIPT_DIR/picamera2_compressed_publisher.py" \
  "$SCRIPT_DIR/setup_marco_libcamera.sh" \
  "$ROBOT_SSH:$REMOTE_DIR/"

echo "[deploy_camera] OK → $ROBOT_SSH:$REMOTE_DIR/picamera2_compressed_publisher.py"
