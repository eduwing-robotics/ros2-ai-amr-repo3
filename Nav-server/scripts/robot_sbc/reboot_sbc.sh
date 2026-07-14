#!/usr/bin/env bash
# TurtleBot SBC 재부팅 (libcamera IPA 크래시 복구용)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROBOT_SSH="${ROBOT_SSH:-musk@192.168.30.102}"
ROBOT_PW="${ROBOT_PW:?Set ROBOT_PW in the environment}"
WAIT_SEC="${WAIT_SEC:-90}"

if command -v sshpass >/dev/null 2>&1 && [[ -n "$ROBOT_PW" ]]; then
  SSH_CMD=(sshpass -p "$ROBOT_PW" ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8)
else
  SSH_CMD=(ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8)
fi

echo "[reboot_sbc] rebooting $ROBOT_SSH ..."
"${SSH_CMD[@]}" "$ROBOT_SSH" "echo '$ROBOT_PW' | sudo -S reboot" 2>/dev/null || \
  "${SSH_CMD[@]}" "$ROBOT_SSH" "sudo reboot" 2>/dev/null || \
  echo "[reboot_sbc] ERROR: reboot command failed" >&2
  exit 1

echo "[reboot_sbc] waiting up to ${WAIT_SEC}s for ssh..."
deadline=$((SECONDS + WAIT_SEC))
while (( SECONDS < deadline )); do
  sleep 5
  if "${SSH_CMD[@]}" "$ROBOT_SSH" "echo ssh_ok" 2>/dev/null | grep -q ssh_ok; then
    echo "[reboot_sbc] ssh OK after reboot"
    exit 0
  fi
  printf '.'
done
echo
echo "[reboot_sbc] WARNING: ssh not back within ${WAIT_SEC}s" >&2
exit 1
