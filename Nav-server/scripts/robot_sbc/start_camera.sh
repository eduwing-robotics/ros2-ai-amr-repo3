#!/usr/bin/env bash
# 로봇 SBC Pi 카메라. picamera2(marco libcamera) 기본 — ros libcamera IPA 크래시 우회.
# Nav PC에서 ssh bash -s 로 파이프되므로 sibling 스크립트 exec 금지(경로 깨짐).
set -eo pipefail

DOMAIN="${ROS_DOMAIN_ID:-5}"
WS_SETUP="${WS_SETUP:-/home/musk/turtlebot3_ws/install/setup.bash}"
CAMERA_BACKEND="${CAMERA_BACKEND:-picamera2}"
BRINGUP_WAIT_SEC="${BRINGUP_WAIT_SEC:-10}"
CAMERA_START_RETRIES="${CAMERA_START_RETRIES:-2}"
CAMERA_LAUNCH="${CAMERA_LAUNCH:-turtlebot3_bringup camera.launch.py}"
CAMERA_LAUNCH_ARGS="${CAMERA_LAUNCH_ARGS:-format:=YUYV width:=320 height:=240 orientation:=180}"

# Match Nav PC DDS discovery across the robot Wi-Fi subnet.
if [[ -f "$HOME/ros2_env.sh" ]]; then
  # shellcheck source=/dev/null
  source "$HOME/ros2_env.sh"
fi
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
unset ROS_LOCALHOST_ONLY
export ROS_AUTOMATIC_DISCOVERY_RANGE="${TB3_DISCOVERY_RANGE:-LOCALHOST}"
export ROS_STATIC_PEERS="${TB3_STATIC_PEERS:-192.168.30.12}"

resolve_publisher() {
  local candidate
  for candidate in \
    "$HOME/slam_nav_camera_fix/picamera2_compressed_publisher.py" \
    "$HOME/slam_nav_ws/scripts/robot_sbc/picamera2_compressed_publisher.py"; do
    if [[ -f "$candidate" ]]; then
      printf '%s' "$candidate"
      return 0
    fi
  done
  return 1
}

stop_camera_local() {
  echo "[robot_sbc] stopping camera processes..."
  pkill -f "picamera2_compressed_publisher.py" 2>/dev/null || true
  pkill -f "raspberrypi_ipa_proxy" 2>/dev/null || true
  pkill -f "libcamera_component" 2>/dev/null || true
  pkill -f "camera_container" 2>/dev/null || true
  pkill -f "component_container" 2>/dev/null || true
  pkill -f "camera.launch.py" 2>/dev/null || true
  sleep 2
  if fuser /dev/media0 >/dev/null 2>&1; then
    echo "[robot_sbc] /dev/media0 busy — force kill"
    pkill -9 -f "raspberrypi_ipa_proxy" 2>/dev/null || true
    pkill -9 -f "camera_container" 2>/dev/null || true
    pkill -9 -f "component_container" 2>/dev/null || true
    sleep 2
  fi
}

source /opt/ros/jazzy/setup.bash
export LD_LIBRARY_PATH=/usr/lib/aarch64-linux-gnu:${LD_LIBRARY_PATH:-}
export LIBCAMERA_IPA_MODULE_PATH=/usr/lib/aarch64-linux-gnu/libcamera/ipa
export LIBCAMERA_IPA_PROXY_PATH=/usr/libexec/aarch64-linux-gnu/libcamera
# shellcheck source=/dev/null
[[ -f "$WS_SETUP" ]] && source "$WS_SETUP"
export ROS_DOMAIN_ID="$DOMAIN"

echo "[robot_sbc] waiting ${BRINGUP_WAIT_SEC}s for bringup before camera..."
sleep "$BRINGUP_WAIT_SEC"
stop_camera_local || true

if [[ "$CAMERA_BACKEND" == "picamera2" ]]; then
  PUBLISHER="$(resolve_publisher || true)"
  if [[ -n "$PUBLISHER" ]] && python3 -c "import picamera2" 2>/dev/null; then
    echo "[robot_sbc] starting picamera2 publisher DOMAIN=$DOMAIN ($PUBLISHER)"
    exec python3 "$PUBLISHER" --ros-args \
      -p width:=320 -p height:=240 -p topic:=/camera/image_raw/compressed
  fi
  echo "[robot_sbc] WARNING: picamera2 unavailable (publisher=${PUBLISHER:-missing}, import failed or missing)"
  echo "[robot_sbc] falling back to camera_ros (CAMERA_BACKEND=ros)"
  CAMERA_BACKEND=ros
fi

# --- legacy: ros-jazzy camera_ros ---
attempt=1
while (( attempt <= CAMERA_START_RETRIES )); do
  echo "[robot_sbc] camera_ros attempt ${attempt}/${CAMERA_START_RETRIES} DOMAIN=$DOMAIN"
  # shellcheck disable=SC2086
  ros2 launch $CAMERA_LAUNCH $CAMERA_LAUNCH_ARGS &
  cam_pid=$!
  sleep 10
  if timeout 15 ros2 topic echo /camera/image_raw/compressed --once \
      --qos-reliability best_effort >/dev/null 2>&1; then
    echo "[robot_sbc] camera OK — compressed frame received"
    wait "$cam_pid"
    exit 0
  fi
  kill "$cam_pid" 2>/dev/null || true
  wait "$cam_pid" 2>/dev/null || true
  stop_camera_local || true
  attempt=$((attempt + 1))
  sleep 5
done

echo "[robot_sbc] ERROR: camera_ros failed — use CAMERA_BACKEND=picamera2 (default)" >&2
exit 1
