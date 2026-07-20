#!/usr/bin/env bash
# 로봇 SBC bringup (odom/scan/TF). Nav PC에서 ssh로 호출.
#
# TB3_EKF_MODE=1 이면 wheel odom TF/IMU 융합을 끄고 EKF(Nav PC)가 odom TF를 발행.
set -eo pipefail

DOMAIN="${ROS_DOMAIN_ID:-5}"
LDS_MODEL="${LDS_MODEL:-LDS-03}"
USB_PORT="${USB_PORT:-/dev/serial/by-id/usb-ROBOTIS_OpenCR_Virtual_ComPort_in_FS_Mode_FFFFFFFEFFFF-if00}"
EXPECTED_USB_TOPOLOGY="${EXPECTED_USB_TOPOLOGY:-}"
WS_SETUP="${WS_SETUP:-/home/musk/turtlebot3_ws/install/setup.bash}"
TB3_EKF_MODE="${TB3_EKF_MODE:-0}"
TB3_BRINGUP_LOG="${TB3_BRINGUP_LOG:-/dev/null}"

source /opt/ros/jazzy/setup.bash
# shellcheck source=/dev/null
source "$WS_SETUP"
# Nav PC uses LOCALHOST + ROS_STATIC_PEERS — SBC must match or odom/scan never arrive.
if [[ -f "$HOME/ros2_env.sh" ]]; then
  # shellcheck source=/dev/null
  source "$HOME/ros2_env.sh"
fi
export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
unset ROS_LOCALHOST_ONLY
export ROS_AUTOMATIC_DISCOVERY_RANGE="${ROS_AUTOMATIC_DISCOVERY_RANGE:-SUBNET}"
export ROS_STATIC_PEERS="${ROS_STATIC_PEERS:-192.168.30.101;192.168.30.102;192.168.30.9;192.168.30.5;192.168.30.12;192.168.30.3}"

export TURTLEBOT3_MODEL=burger
export LDS_MODEL="$LDS_MODEL"
export ROS_DOMAIN_ID="$DOMAIN"

if [[ ! -e "$USB_PORT" ]]; then
  echo "[robot_sbc] ERROR: OpenCR USB not found: $USB_PORT" >&2
  echo "[robot_sbc] detected serial devices:" >&2
  ls -l /dev/serial/by-id >&2 2>/dev/null || true
  exit 2
fi

USB_DEVICE_PATH="$(udevadm info -q path -n "$USB_PORT" 2>/dev/null || true)"
if [[ -n "$EXPECTED_USB_TOPOLOGY" && "$USB_DEVICE_PATH" != *"/$EXPECTED_USB_TOPOLOGY/"* ]]; then
  echo "[robot_sbc] ERROR: OpenCR is not on the verified USB path $EXPECTED_USB_TOPOLOGY" >&2
  echo "[robot_sbc] actual udev path: ${USB_DEVICE_PATH:-unknown}" >&2
  echo "[robot_sbc] keep Arduino unchanged and swap only OpenCR/LDS SBC-side USB ports" >&2
  exit 3
fi

echo "[robot_sbc] bringup start DOMAIN=$DOMAIN LDS=$LDS_MODEL EKF_MODE=$TB3_EKF_MODE"
echo "[robot_sbc] DDS peers=$ROS_STATIC_PEERS range=$ROS_AUTOMATIC_DISCOVERY_RANGE"
echo "[robot_sbc] usb=$USB_PORT"
echo "[robot_sbc] usb topology=${EXPECTED_USB_TOPOLOGY:-unchecked} path=${USB_DEVICE_PATH:-unknown}"
echo "[robot_sbc] runtime log=$TB3_BRINGUP_LOG"

LAUNCH_ARGS=("usb_port:=$USB_PORT")

if [[ "$TB3_EKF_MODE" == "1" ]]; then
  DEFAULT_PARAM="${TB3_DEFAULT_PARAM:-$(ros2 pkg prefix turtlebot3_bringup)/share/turtlebot3_bringup/param/burger.yaml}"
  MERGED_PARAM="$(mktemp /tmp/tb3_burger_ekf_merged.XXXXXX.yaml)"
  cp "$DEFAULT_PARAM" "$MERGED_PARAM"
  if [[ -n "${TB3_EKF_OVERLAY:-}" && -f "$TB3_EKF_OVERLAY" ]]; then
    cat "$TB3_EKF_OVERLAY" >>"$MERGED_PARAM"
  else
    cat >>"$MERGED_PARAM" <<'YAML'
/**:
  diff_drive_controller:
    ros__parameters:
      odometry:
        publish_tf: false
        use_imu: false
YAML
  fi
  LAUNCH_ARGS+=("tb3_param_dir:=$MERGED_PARAM")
  echo "[robot_sbc] EKF bringup overlay applied (publish_tf=false use_imu=false)"
fi

# Some LDS drivers emit high-rate diagnostics. Forwarding those lines over the
# control SSH session can saturate the robot Wi-Fi and delay DDS traffic.
exec ros2 launch turtlebot3_bringup robot.launch.py "${LAUNCH_ARGS[@]}" \
  >>"$TB3_BRINGUP_LOG" 2>&1
