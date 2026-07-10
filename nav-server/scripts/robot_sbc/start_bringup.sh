#!/usr/bin/env bash
# 로봇 SBC bringup (odom/scan/TF). Nav PC에서 ssh로 호출.
#
# TB3_EKF_MODE=1 이면 wheel odom TF/IMU 융합을 끄고 EKF(Nav PC)가 odom TF를 발행.
set -eo pipefail

DOMAIN="${ROS_DOMAIN_ID:-5}"
LDS_MODEL="${LDS_MODEL:-LDS-03}"
USB_PORT="${USB_PORT:-/dev/serial/by-id/usb-ROBOTIS_OpenCR_Virtual_ComPort_in_FS_Mode_FFFFFFFEFFFF-if00}"
WS_SETUP="${WS_SETUP:?WS_SETUP must point to the TurtleBot3 overlay setup.bash}"
TB3_EKF_MODE="${TB3_EKF_MODE:-0}"

source /opt/ros/jazzy/setup.bash
# shellcheck source=/dev/null
source "$WS_SETUP"

export TURTLEBOT3_MODEL=burger
export LDS_MODEL="$LDS_MODEL"
export ROS_DOMAIN_ID="$DOMAIN"

echo "[robot_sbc] bringup start DOMAIN=$DOMAIN LDS=$LDS_MODEL EKF_MODE=$TB3_EKF_MODE"
echo "[robot_sbc] usb=$USB_PORT"

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

exec ros2 launch turtlebot3_bringup robot.launch.py "${LAUNCH_ARGS[@]}"
