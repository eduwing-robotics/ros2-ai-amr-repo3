#!/usr/bin/env bash
# picamera2 기반 카메라 (marco libcamera). ros-jazzy-libcamera IPA 크래시 우회.
set -eo pipefail

DOMAIN="${ROS_DOMAIN_ID:-5}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || true)"
PUBLISHER="${SCRIPT_DIR}/picamera2_compressed_publisher.py"
for candidate in \
  "$PUBLISHER" \
  "$HOME/slam_nav_camera_fix/picamera2_compressed_publisher.py" \
  "$HOME/slam_nav_ws/scripts/robot_sbc/picamera2_compressed_publisher.py"; do
  if [[ -f "$candidate" ]]; then
    PUBLISHER="$candidate"
    break
  fi
done
if [[ ! -f "$PUBLISHER" ]]; then
  echo "[robot_sbc] ERROR: picamera2_compressed_publisher.py not found on SBC" >&2
  echo "[robot_sbc] HINT: scp scripts/robot_sbc/* to ~/slam_nav_camera_fix/ on robot" >&2
  exit 1
fi
BRINGUP_WAIT_SEC="${BRINGUP_WAIT_SEC:-5}"

stop_camera_local() {
  echo "[robot_sbc] stopping camera processes..."
  pkill -f "picamera2_compressed_publisher.py" 2>/dev/null || true
  pkill -f "raspberrypi_ipa_proxy" 2>/dev/null || true
  pkill -f "libcamera_component" 2>/dev/null || true
  pkill -f "camera.launch.py" 2>/dev/null || true
  pkill -f "camera_container" 2>/dev/null || true
  sleep 2
}

source /opt/ros/jazzy/setup.bash
export ROS_DOMAIN_ID="$DOMAIN"
export LD_LIBRARY_PATH=/usr/lib/aarch64-linux-gnu:${LD_LIBRARY_PATH:-}
export LIBCAMERA_IPA_MODULE_PATH=/usr/lib/aarch64-linux-gnu/libcamera/ipa
export LIBCAMERA_IPA_PROXY_PATH=/usr/libexec/aarch64-linux-gnu/libcamera

echo "[robot_sbc] waiting ${BRINGUP_WAIT_SEC}s before picamera2..."
sleep "$BRINGUP_WAIT_SEC"
stop_camera_local || true

if ! python3 -c "import picamera2" 2>/dev/null; then
  echo "[robot_sbc] ERROR: python3-picamera2 not installed. Run setup_marco_libcamera.sh first." >&2
  exit 1
fi

echo "[robot_sbc] starting picamera2 publisher DOMAIN=$DOMAIN"
exec python3 "$PUBLISHER" --ros-args \
  -p width:=320 -p height:=240 -p topic:=/camera/image_raw/compressed
