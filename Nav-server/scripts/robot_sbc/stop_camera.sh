#!/usr/bin/env bash
# 로봇 SBC 카메라/libcamera 프로세스만 정리 (bringup 유지)
set -eo pipefail

echo "[robot_sbc] stopping camera/libcamera..."
pkill -f "picamera2_compressed_publisher.py" 2>/dev/null || true
pkill -f "raspberrypi_ipa_proxy" 2>/dev/null || true
pkill -f "libcamera_component" 2>/dev/null || true
pkill -f "camera_container" 2>/dev/null || true
pkill -f "component_container" 2>/dev/null || true
pkill -f "camera.launch.py" 2>/dev/null || true
sleep 2

if fuser /dev/media0 >/dev/null 2>&1; then
  echo "[robot_sbc] /dev/media0 still busy — force kill"
  pkill -9 -f "raspberrypi_ipa_proxy" 2>/dev/null || true
  pkill -9 -f "camera_container" 2>/dev/null || true
  pkill -9 -f "component_container" 2>/dev/null || true
  sleep 2
fi

for _ in $(seq 1 15); do
  if ! fuser /dev/media0 >/dev/null 2>&1; then
    echo "[robot_sbc] camera stop complete (/dev/media0 free)"
    exit 0
  fi
  sleep 1
done

echo "[robot_sbc] WARNING: /dev/media0 still busy after cleanup" >&2
exit 1
