#!/usr/bin/env bash
#
# Bring up TurtleBot3 Pi Camera and the project ArUco detector in one robot domain.
# Based on the provided Pi-Camera ROS2 and OpenCV ArUco PDFs.
#
# Typical usage on TurtleBot3 SBC:
#   ROBOT_ID=tb3_burger_01 scripts/run_pi_camera_aruco.sh
#   ROBOT_ID=tb3_burger_02 scripts/run_pi_camera_aruco.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
ROBOTS_CONFIG_PATH="${ROBOTS_CONFIG_PATH:-$ROOT/config/robots.json}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
ROBOT_ID="${ROBOT_ID:-tb3_burger_01}"
CAMERA_LAUNCH="${CAMERA_LAUNCH:-turtlebot3_bringup camera.launch.py}"
ARUCO_DICTIONARY="${ARUCO_DICTIONARY:-DICT_4X4_50}"
ARUCO_MARKER_SIZE_M="${ARUCO_MARKER_SIZE_M:-0.05}"
ARUCO_FOCAL_LENGTH_PX="${ARUCO_FOCAL_LENGTH_PX:-0.0}"
ARUCO_MIN_MARKER_WIDTH_PX="${ARUCO_MIN_MARKER_WIDTH_PX:-8.0}"
ARUCO_CALIBRATION_FILE="${ARUCO_CALIBRATION_FILE:-}"

require_file() {
  local path="$1"
  local label="$2"
  if [[ ! -f "$path" ]]; then
    echo "[pi_camera_aruco] missing ${label}: $path" >&2
    exit 1
  fi
}

robot_field() {
  local field="$1"
  "$PYTHON_BIN" - "$ROBOTS_CONFIG_PATH" "$ROBOT_ID" "$field" <<'PYROBOT'
import json, sys
path, robot_id, field = sys.argv[1:4]
data = json.load(open(path, encoding='utf-8'))
for robot in data.get('robots', []):
    if robot.get('robot_id') == robot_id:
        value = robot.get(field)
        if value is None:
            raise SystemExit(2)
        print(value)
        raise SystemExit(0)
raise SystemExit(1)
PYROBOT
}

require_file "$ROS_SETUP" "ROS setup"
require_file "$ROBOTS_CONFIG_PATH" "robots config"

BRIDGE_ROBOT_ID="${BRIDGE_ROBOT_ID:-$(robot_field bridge_robot_id)}"
CONFIGURED_ROS_DOMAIN_ID="$(robot_field ros_domain_id)"
ROS_DOMAIN_ID="${ROS_DOMAIN_ID_OVERRIDE:-$CONFIGURED_ROS_DOMAIN_ID}"
CAMERA_TOPIC="${CAMERA_TOPIC:-$(robot_field camera_topic)}"
ARUCO_DETECTION_TOPIC="${ARUCO_DETECTION_TOPIC:-$(robot_field aruco_detection_topic)}"
if [[ -z "$ARUCO_CALIBRATION_FILE" ]]; then
  robot_calibration="$ROOT/config/camera/${ROBOT_ID}.json"
  [[ ! -f "$robot_calibration" ]] || ARUCO_CALIBRATION_FILE="$robot_calibration"
fi
RAW_CAMERA_TOPIC="${RAW_CAMERA_TOPIC:-/camera/image_raw}"
RAW_COMPRESSED_TOPIC="${RAW_COMPRESSED_TOPIC:-/camera/image_raw/compressed}"
DETECTOR_IMAGE_TOPIC="${DETECTOR_IMAGE_TOPIC:-$RAW_COMPRESSED_TOPIC}"
CAMERA_WIDTH="${CAMERA_WIDTH:-640}"
CAMERA_HEIGHT="${CAMERA_HEIGHT:-480}"
CAMERA_USE_IMAGE_VIEW="${CAMERA_USE_IMAGE_VIEW:-false}"
START_CAMERA_LAUNCH="${START_CAMERA_LAUNCH:-1}"
START_CAMERA_RELAY="${START_CAMERA_RELAY:-1}"

pids=()
cleanup() {
  if ((${#pids[@]} > 0)); then
    echo
    echo "[pi_camera_aruco] stopping child processes..."
    kill "${pids[@]}" 2>/dev/null || true
    wait 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

# shellcheck source=/dev/null
set +u
source "$ROS_SETUP"
set -u
export ROS_DOMAIN_ID
export BRIDGE_ROBOT_ID
export ARUCO_IMAGE_TOPIC="$DETECTOR_IMAGE_TOPIC"
export ARUCO_DETECTION_TOPIC
# venv numpy 2.x breaks system cv2 — detector/relay must not inherit venv site-packages
export PYTHONPATH="$(python3 -c "import os; print(':'.join(p for p in os.environ.get('PYTHONPATH','').split(':') if p and 'venv' not in p))")"
DETECTOR_PY="${PYTHON_BIN:-python3}"
if ! "$DETECTOR_PY" -c "import cv2" 2>/dev/null; then
  DETECTOR_PY="/usr/bin/python3"
fi

printf '[pi_camera_aruco] robot=%s bridge=%s domain=%s\n' "$ROBOT_ID" "$BRIDGE_ROBOT_ID" "$ROS_DOMAIN_ID"
printf '[pi_camera_aruco] camera input topic: %s\n' "$DETECTOR_IMAGE_TOPIC"
printf '[pi_camera_aruco] mission camera topic: %s\n' "$CAMERA_TOPIC"
printf '[pi_camera_aruco] detection topic: %s\n' "$ARUCO_DETECTION_TOPIC"
printf '[pi_camera_aruco] camera relay enabled: %s\n' "$START_CAMERA_RELAY"
if [[ -n "$ARUCO_CALIBRATION_FILE" ]]; then
  require_file "$ARUCO_CALIBRATION_FILE" "camera calibration"
  printf '[pi_camera_aruco] calibration: %s\n' "$ARUCO_CALIBRATION_FILE"
fi

# ros2 launch does not accept global --ros-args remaps for this launch file.
# Keep the camera on its default compressed topic and let the detector publish
# project-standard detection JSON under /mission/<tb3>/aruco/detections.
if [[ "$START_CAMERA_LAUNCH" != "0" ]]; then
  ros2 launch $CAMERA_LAUNCH \
    width:="$CAMERA_WIDTH" \
    height:="$CAMERA_HEIGHT" \
    use_image_view:="$CAMERA_USE_IMAGE_VIEW" &
  pids+=("$!")
else
  echo "[pi_camera_aruco] camera launch skipped; expecting existing topic: $DETECTOR_IMAGE_TOPIC"
fi

if [[ "$START_CAMERA_RELAY" != "0" ]]; then
  "$DETECTOR_PY" "$SCRIPT_DIR/compressed_image_relay.py" --ros-args \
    -p "input_topic:=${DETECTOR_IMAGE_TOPIC}" \
    -p "output_topic:=${CAMERA_TOPIC}" &
  pids+=("$!")
fi

detector_args=(--ros-args
  -p "image_topic:=${DETECTOR_IMAGE_TOPIC}"
  -p "detection_topic:=${ARUCO_DETECTION_TOPIC}"
  -p "dictionary:=${ARUCO_DICTIONARY}"
  -p "marker_size_m:=${ARUCO_MARKER_SIZE_M}"
  -p "focal_length_px:=${ARUCO_FOCAL_LENGTH_PX}"
  -p "min_marker_width_px:=${ARUCO_MIN_MARKER_WIDTH_PX}")
[[ -z "$ARUCO_CALIBRATION_FILE" ]] || detector_args+=(-p "calibration_file:=${ARUCO_CALIBRATION_FILE}")
"$DETECTOR_PY" "$SCRIPT_DIR/aruco_detector_node.py" "${detector_args[@]}" &
pids+=("$!")

wait -n "${pids[@]}"
