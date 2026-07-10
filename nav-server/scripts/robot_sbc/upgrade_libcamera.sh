#!/usr/bin/env bash
# ros-jazzy-libcamera 0.7.1 업그레이드 (ControlInfoMap IPA 크래시 수정 포함 가능)
set -eo pipefail

echo "[robot_sbc] upgrading ros-jazzy-libcamera / camera-ros..."
sudo apt-get update -qq
sudo apt-get install -y --only-upgrade \
  ros-jazzy-libcamera \
  ros-jazzy-camera-ros \
  2>&1 | tail -20

dpkg -l | grep -E 'ros-jazzy-libcamera|ros-jazzy-camera-ros'
echo "[robot_sbc] libcamera upgrade done"
