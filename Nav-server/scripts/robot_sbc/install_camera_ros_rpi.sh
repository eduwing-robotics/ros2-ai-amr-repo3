#!/usr/bin/env bash
# marco PPA libcamera(0.6)에 링크된 camera_ros 오버레이 빌드 (ros-jazzy-libcamera 0.7 IPA 크래시 우회)
set -eo pipefail

CAMERA_WS="${CAMERA_WS:-$HOME/camera_rpi_ws}"
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"

source "$ROS_SETUP"
export LD_LIBRARY_PATH=/usr/lib/aarch64-linux-gnu:${LD_LIBRARY_PATH:-}
export LIBCAMERA_IPA_MODULE_PATH=/usr/lib/aarch64-linux-gnu/libcamera/ipa
export LIBCAMERA_IPA_PROXY_PATH=/usr/libexec/aarch64-linux-gnu/libcamera

mkdir -p "$CAMERA_WS/src"
if [[ ! -d "$CAMERA_WS/src/camera_ros" ]]; then
  git clone --depth 1 https://github.com/christianrauch/camera_ros.git "$CAMERA_WS/src/camera_ros"
fi

cd "$CAMERA_WS"
rosdep install --from-paths src --ignore-src -y -r --rosdistro jazzy --skip-keys=libcamera 2>&1 | tail -5
colcon build --packages-select camera_ros --cmake-args -DCMAKE_BUILD_TYPE=Release 2>&1 | tail -15

echo "[robot_sbc] camera_ros overlay: $CAMERA_WS/install/setup.bash"
ldd "$CAMERA_WS/install/camera_ros/lib/camera_ros/camera_node" | grep libcamera || true
