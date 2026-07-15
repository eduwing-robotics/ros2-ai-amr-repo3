#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/vision_bundle_common.sh
source "${SCRIPT_DIR}/../lib/vision_bundle_common.sh"
ROOT_DIR="$(sf_repo_root_from_script "${BASH_SOURCE[0]}")"
ROS_DISTRO="${ROS_DISTRO:-jazzy}"
ROS_SETUP="${ROS_SETUP:-/opt/ros/${ROS_DISTRO}/setup.bash}"
LOCAL_ROS_PYTHONPATH="${ROOT_DIR}/ros2/smartfactory_perception_ros"

usage() {
  cat << USAGE
Usage: $(basename "$0") [--check|--print-config|--help]

Runs one extra D1 vision ROS domain sidecar as one supervised process group:
  1) vision_frame_gateway for VISION_SOURCE_ID in ROS_DOMAIN_ID
  2) vision_overlay_stream_bridge on VISION_STREAM_PORT in the same ROS_DOMAIN_ID

AI Server must already be running. This script never starts robot motion, Nav2,
teleop, /cmd_vel, robot-side persistent services, or a whole-graph bridge.

Example Robot2/domain5:
  ROS_DOMAIN_ID=5 \
  VISION_SOURCE_ID=tb3_2_picam \
  VISION_IMAGE_TOPIC=/camera/image_raw/compressed \
  VISION_STREAM_PORT=8091 \
  ./scripts/vision/run_d1_vision_domain_sidecar.sh
USAGE
}

set_defaults() {
  export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-5}"
  export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
  export AI_SERVER_URL="${AI_SERVER_URL:-http://127.0.0.1:8100}"
  export VISION_SOURCE_ID="${VISION_SOURCE_ID:-tb3_2_picam}"
  export VISION_IMAGE_TOPIC="${VISION_IMAGE_TOPIC:-/camera/image_raw/compressed}"
  export VISION_GATEWAY_REQUEST_TIMEOUT_SEC="${VISION_GATEWAY_REQUEST_TIMEOUT_SEC:-1.2}"
  export VISION_GATEWAY_FRAME_PROCESS_PATH="${VISION_GATEWAY_FRAME_PROCESS_PATH:-/api/v1/vision/frame/process}"
  export VISION_GATEWAY_PERIOD_SEC="${VISION_GATEWAY_PERIOD_SEC:-0.033333}"
  export VISION_GATEWAY_PUBLISH_OUTPUT_PERIOD_SEC="${VISION_GATEWAY_PUBLISH_OUTPUT_PERIOD_SEC:-0.02}"
  VISION_GATEWAY_REQUEST_TIMEOUT_SEC="$(sf_ros_double "${VISION_GATEWAY_REQUEST_TIMEOUT_SEC}")"
  VISION_GATEWAY_PERIOD_SEC="$(sf_ros_double "${VISION_GATEWAY_PERIOD_SEC}")"
  VISION_GATEWAY_PUBLISH_OUTPUT_PERIOD_SEC="$(sf_ros_double "${VISION_GATEWAY_PUBLISH_OUTPUT_PERIOD_SEC}")"
  export VISION_GATEWAY_REQUEST_TIMEOUT_SEC
  export VISION_GATEWAY_PERIOD_SEC
  export VISION_GATEWAY_PUBLISH_OUTPUT_PERIOD_SEC
  export VISION_GATEWAY_IMAGE_QOS_RELIABILITY="${VISION_GATEWAY_IMAGE_QOS_RELIABILITY:-reliable}"
  export VISION_GATEWAY_IMAGE_QOS_DEPTH="${VISION_GATEWAY_IMAGE_QOS_DEPTH:-1}"
  export VISION_GATEWAY_OVERLAY_PUB_QOS_RELIABILITY="${VISION_GATEWAY_OVERLAY_PUB_QOS_RELIABILITY:-reliable}"
  export VISION_GATEWAY_OVERLAY_PUB_QOS_DEPTH="${VISION_GATEWAY_OVERLAY_PUB_QOS_DEPTH:-1}"
  export VISION_GATEWAY_ASYNC_PIPELINE="${VISION_GATEWAY_ASYNC_PIPELINE:-true}"
  export VISION_GATEWAY_PROCESS_FRAME_INLINE="${VISION_GATEWAY_PROCESS_FRAME_INLINE:-true}"
  export VISION_GATEWAY_RETRY_FAILED_FRAME="${VISION_GATEWAY_RETRY_FAILED_FRAME:-true}"
  export VISION_GATEWAY_RETRY_BACKOFF_SEC="${VISION_GATEWAY_RETRY_BACKOFF_SEC:-0.05}"
  export VISION_GATEWAY_PUBLISH_LAGGING_OVERLAY="${VISION_GATEWAY_PUBLISH_LAGGING_OVERLAY:-false}"
  export VISION_GATEWAY_PUBLISH_OVERLAY="${VISION_GATEWAY_PUBLISH_OVERLAY:-true}"
  export VISION_GATEWAY_PUBLISH_EVIDENCE="${VISION_GATEWAY_PUBLISH_EVIDENCE:-true}"
  export VISION_OVERLAY_TOPIC="${VISION_OVERLAY_TOPIC:-/sf/vision/sources/${VISION_SOURCE_ID}/overlay/compressed}"
  export VISION_EVIDENCE_TOPIC="${VISION_EVIDENCE_TOPIC:-/sf/vision/events}"
  export VISION_STREAM_HOST="${VISION_STREAM_HOST:-0.0.0.0}"
  export VISION_STREAM_PORT="${VISION_STREAM_PORT:-8091}"
  export VISION_STREAM_MAX_FPS="${VISION_STREAM_MAX_FPS:-30.0}"
  export VISION_STREAM_STALE_AFTER_SEC="${VISION_STREAM_STALE_AFTER_SEC:-2.0}"
  export VISION_STREAM_OVERLAY_SUB_QOS_RELIABILITY="${VISION_STREAM_OVERLAY_SUB_QOS_RELIABILITY:-reliable}"
  export VISION_STREAM_OVERLAY_SUB_QOS_DEPTH="${VISION_STREAM_OVERLAY_SUB_QOS_DEPTH:-1}"
}

check_prereqs() {
  if [ ! -f "${ROS_SETUP}" ]; then
    echo "ERROR: ROS setup not found: ${ROS_SETUP}" >&2
    return 1
  fi
  if command -v curl > /dev/null 2>&1; then
    curl -fsS --max-time 2 "${AI_SERVER_URL%/}/api/v1/health" > /dev/null || {
      echo "ERROR: AI Server health failed at ${AI_SERVER_URL%/}/api/v1/health" >&2
      return 1
    }
  fi
  (
    # shellcheck disable=SC1090
    unset PYTHONPATH
    set +u
    source "${ROS_SETUP}"
    set -u
    export PYTHONPATH="${LOCAL_ROS_PYTHONPATH}${PYTHONPATH:+:${PYTHONPATH}}"
    python3 - << 'PY'
import importlib.util
for module in (
    'smartfactory_perception_ros.vision_frame_gateway',
    'smartfactory_perception_ros.vision_overlay_stream_bridge',
):
    if importlib.util.find_spec(module) is None:
        raise SystemExit(f'ERROR: missing local ROS module: {module}')
print('local ROS module check: ok')
PY
  )
}

print_config() {
  local ip
  ip="$(sf_lan_ip)"
  ip="${ip:-127.0.0.1}"
  cat << CONFIG
D1 vision domain sidecar config
  root: ${ROOT_DIR}
  ROS_DOMAIN_ID: ${ROS_DOMAIN_ID}
  RMW_IMPLEMENTATION: ${RMW_IMPLEMENTATION}
  ai_server_url: ${AI_SERVER_URL}
  source/topic: ${VISION_SOURCE_ID} <= ${VISION_IMAGE_TOPIC}
  overlay_topic: ${VISION_OVERLAY_TOPIC}
  evidence_topic: ${VISION_EVIDENCE_TOPIC}
  gateway period/timeout: ${VISION_GATEWAY_PERIOD_SEC}s/${VISION_GATEWAY_REQUEST_TIMEOUT_SEC}s
  qos/pipeline: image=${VISION_GATEWAY_IMAGE_QOS_RELIABILITY}, overlay_pub=${VISION_GATEWAY_OVERLAY_PUB_QOS_RELIABILITY}, overlay_sub=${VISION_STREAM_OVERLAY_SUB_QOS_RELIABILITY}, async=${VISION_GATEWAY_ASYNC_PIPELINE}, inline_process=${VISION_GATEWAY_PROCESS_FRAME_INLINE}, frame_process_path=${VISION_GATEWAY_FRAME_PROCESS_PATH}
  stream_bridge: ${VISION_STREAM_HOST}:${VISION_STREAM_PORT} max_fps=${VISION_STREAM_MAX_FPS}

Main/GUI URLs on this LAN candidate:
  View:   http://${ip}:${VISION_STREAM_PORT}/api/v1/vision/overlay/view?source=${VISION_SOURCE_ID}
  Stream: http://${ip}:${VISION_STREAM_PORT}/api/v1/vision/overlay/stream?source=${VISION_SOURCE_ID}&max_fps=${VISION_STREAM_MAX_FPS}
  Bridge: http://${ip}:${VISION_STREAM_PORT}/api/v1/vision/bridge/status
  Tags:   ${AI_SERVER_URL%/}/api/v1/detections/latest?source=${VISION_SOURCE_ID}&limit=10
CONFIG
}

PIDS=()
cleanup() {
  local status=$?
  trap - INT TERM EXIT
  if [ "${#PIDS[@]}" -gt 0 ]; then
    echo "[domain-sidecar] stopping ${#PIDS[@]} child process(es)"
    for pid in "${PIDS[@]}"; do kill -INT "${pid}" 2> /dev/null || true; done
    sleep 2
    for pid in "${PIDS[@]}"; do kill -TERM "${pid}" 2> /dev/null || true; done
    wait 2> /dev/null || true
  fi
  exit "${status}"
}

start_ros_child() {
  local name="$1"
  shift
  echo "[domain-sidecar] starting ${name}"
  (
    # shellcheck disable=SC1090
    unset PYTHONPATH
    set +u
    source "${ROS_SETUP}"
    set -u
    export PYTHONPATH="${LOCAL_ROS_PYTHONPATH}${PYTHONPATH:+:${PYTHONPATH}}"
    exec "$@"
  ) &
  PIDS+=("$!")
  echo "[domain-sidecar] ${name} pid=${PIDS[-1]}"
}

main() {
  case "${1:-}" in
    --help | -h)
      usage
      exit 0
      ;;
    --check)
      set_defaults
      check_prereqs
      print_config
      exit 0
      ;;
    --print-config)
      set_defaults
      print_config
      exit 0
      ;;
    "") ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac

  set_defaults
  check_prereqs
  print_config
  trap cleanup INT TERM EXIT

  start_ros_child "vision_frame_gateway:${VISION_SOURCE_ID}" \
    python3 -m smartfactory_perception_ros.vision_frame_gateway --ros-args \
    -p "source_id:=${VISION_SOURCE_ID}" \
    -p "image_topic:=${VISION_IMAGE_TOPIC}" \
    -p "image_transport:=compressed" \
    -p "ai_server_url:=${AI_SERVER_URL}" \
    -p "frame_process_path:=${VISION_GATEWAY_FRAME_PROCESS_PATH}" \
    -p "request_timeout_sec:=${VISION_GATEWAY_REQUEST_TIMEOUT_SEC}" \
    -p "publish_period_sec:=${VISION_GATEWAY_PERIOD_SEC}" \
    -p "publish_output_period_sec:=${VISION_GATEWAY_PUBLISH_OUTPUT_PERIOD_SEC}" \
    -p "image_qos_reliability:=${VISION_GATEWAY_IMAGE_QOS_RELIABILITY}" \
    -p "image_qos_depth:=${VISION_GATEWAY_IMAGE_QOS_DEPTH}" \
    -p "overlay_pub_qos_reliability:=${VISION_GATEWAY_OVERLAY_PUB_QOS_RELIABILITY}" \
    -p "overlay_pub_qos_depth:=${VISION_GATEWAY_OVERLAY_PUB_QOS_DEPTH}" \
    -p "async_pipeline:=${VISION_GATEWAY_ASYNC_PIPELINE}" \
    -p "process_frame_inline:=${VISION_GATEWAY_PROCESS_FRAME_INLINE}" \
    -p "retry_failed_frame:=${VISION_GATEWAY_RETRY_FAILED_FRAME}" \
    -p "retry_backoff_sec:=${VISION_GATEWAY_RETRY_BACKOFF_SEC}" \
    -p "publish_lagging_overlay:=${VISION_GATEWAY_PUBLISH_LAGGING_OVERLAY}" \
    -p "publish_overlay:=${VISION_GATEWAY_PUBLISH_OVERLAY}" \
    -p "publish_evidence:=${VISION_GATEWAY_PUBLISH_EVIDENCE}" \
    -p "overlay_topic:=${VISION_OVERLAY_TOPIC}" \
    -p "evidence_topic:=${VISION_EVIDENCE_TOPIC}"

  start_ros_child "vision_overlay_stream_bridge:${VISION_SOURCE_ID}" \
    python3 -m smartfactory_perception_ros.vision_overlay_stream_bridge --ros-args \
    -p "host:=${VISION_STREAM_HOST}" \
    -p "port:=${VISION_STREAM_PORT}" \
    -p "sources:=${VISION_SOURCE_ID}" \
    -p "max_fps:=${VISION_STREAM_MAX_FPS}" \
    -p "stale_after_sec:=${VISION_STREAM_STALE_AFTER_SEC}" \
    -p "overlay_sub_qos_reliability:=${VISION_STREAM_OVERLAY_SUB_QOS_RELIABILITY}" \
    -p "overlay_sub_qos_depth:=${VISION_STREAM_OVERLAY_SUB_QOS_DEPTH}"

  echo "[domain-sidecar] running. Ctrl-C stops ${VISION_SOURCE_ID} local child processes."
  set +e
  wait -n "${PIDS[@]}"
  child_status=$?
  set -e
  echo "[domain-sidecar] a child process exited (status=${child_status}); shutting down sidecar"
  exit "${child_status}"
}

main "$@"
