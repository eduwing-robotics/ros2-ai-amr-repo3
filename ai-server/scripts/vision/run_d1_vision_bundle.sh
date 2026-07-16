#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/vision_bundle_common.sh
source "${SCRIPT_DIR}/../lib/vision_bundle_common.sh"
ROOT_DIR="$(sf_repo_root_from_script "${BASH_SOURCE[0]}")"
ROS_DISTRO="${ROS_DISTRO:-jazzy}"
ROS_SETUP="${ROS_SETUP:-/opt/ros/${ROS_DISTRO}/setup.bash}"
LOCAL_ROS_PYTHONPATH="${ROOT_DIR}/ros2/smartfactory_perception_ros"
DEFAULT_MODEL_EXTRA_PYTHONPATH="$(sf_default_model_extra_pythonpath)"

usage() {
  cat << USAGE
Usage: $(basename "$0") [--check|--print-config|--help]

Runs the local D1 vision bundle as one supervised process group:
  1) AI Server (FastAPI) on AI_SERVER_HOST:AI_SERVER_PORT
  2) vision_frame_gateway ROS2 sidecar (camera -> AI Server -> /sf/vision/*)
  3) vision_overlay_stream_bridge read-only MJPEG bridge for Main/GUI

This script intentionally does NOT start robot motion, Nav2, teleop, /cmd_vel,
or robot-side persistent services. Robot camera/domain bridge must already be
publishing the configured camera topic.

Common run:
  ./scripts/vision/run_d1_vision_bundle.sh

Useful environment overrides:
  ROS_DOMAIN_ID                         default: 2
  RMW_IMPLEMENTATION                    default: rmw_fastrtps_cpp
  AI_SERVER_HOST                        default: 0.0.0.0
  AI_SERVER_PORT                        default: 8100
  AI_SERVER_VENV_DIR                    default: ai-server/.venv
  AI_SERVER_EXTRA_PYTHONPATH            default: empty; set explicitly for local model envs
  VISION_MODEL_WORKER_ENABLED           default: true
  VISION_MODEL_PATH                     default: ./yolov8n.pt
  VISION_MODEL_IMGSZ                    default: 224
  VISION_MODEL_CONF                     default: 0.35
                                          Defaults are a lightweight smoke/comparator
                                          profile. GoPro segment-overlay proof should
                                          override task/path/imgsz to segment/best.pt/640.
  VISION_SOURCE_ID                      default: tb3_1_picam
  VISION_IMAGE_TOPIC                    default: /camera/image_raw/compressed
  VISION_GATEWAY_PERIOD_SEC             default: 0.033333
  VISION_STREAM_HOST                    default: 0.0.0.0
  VISION_STREAM_PORT                    default: 8090
  VISION_STREAM_MAX_FPS                 default: 30.0

Main/GUI receives from:
  http://<this-pc>:8090/api/v1/vision/overlay/view?source=tb3_1_picam
  http://<this-pc>:8090/api/v1/vision/overlay/stream?source=tb3_1_picam&max_fps=30
  http://<this-pc>:8090/api/v1/vision/bridge/status
  http://<this-pc>:8100/api/v1/detections/latest?source=tb3_1_picam&limit=10
USAGE
}

set_defaults() {
  export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-2}"
  export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"

  export AI_SERVER_HOST="${AI_SERVER_HOST:-0.0.0.0}"
  export AI_SERVER_PORT="${AI_SERVER_PORT:-8100}"
  export AI_SERVER_VENV_DIR="${AI_SERVER_VENV_DIR:-${ROOT_DIR}/.venv}"
  if [ -z "${AI_SERVER_EXTRA_PYTHONPATH:-}" ] && [ -d "${DEFAULT_MODEL_EXTRA_PYTHONPATH}" ]; then
    export AI_SERVER_EXTRA_PYTHONPATH="${DEFAULT_MODEL_EXTRA_PYTHONPATH}"
  fi

  export VISION_MODEL_WORKER_ENABLED="${VISION_MODEL_WORKER_ENABLED:-true}"
  # Lightweight default for laptop smoke/TurtleBot comparator runs. Do not treat
  # this as the GoPro segment-overlay proof profile; that proof must explicitly
  # set VISION_MODEL_TASK=segment, the segment best.pt path, and imgsz=640.
  export VISION_MODEL_PATH="${VISION_MODEL_PATH:-${ROOT_DIR}/yolov8n.pt}"
  export VISION_MODEL_TASK="${VISION_MODEL_TASK:-detect}"
  export VISION_MODEL_DEVICE="${VISION_MODEL_DEVICE:-0}"
  export VISION_MODEL_IMGSZ="${VISION_MODEL_IMGSZ:-224}"
  export VISION_MODEL_CONF="${VISION_MODEL_CONF:-0.35}"
  if [ -z "${VISION_MODEL_CLASS_MAP_JSON:-}" ]; then
    export VISION_MODEL_CLASS_MAP_JSON='{"bottle":"box","person":"person"}'
  else
    export VISION_MODEL_CLASS_MAP_JSON
  fi
  export VISION_MODEL_UNMAPPED_CLASS="${VISION_MODEL_UNMAPPED_CLASS:-unknown}"

  export VISION_SOURCE_ID="${VISION_SOURCE_ID:-tb3_1_picam}"
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

  export VISION_STREAM_HOST="${VISION_STREAM_HOST:-0.0.0.0}"
  export VISION_STREAM_PORT="${VISION_STREAM_PORT:-8090}"
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
  if [ ! -x "${AI_SERVER_VENV_DIR}/bin/uvicorn" ]; then
    echo "ERROR: AI Server venv not found at ${AI_SERVER_VENV_DIR}" >&2
    echo "       Run ./scripts/ai/setup_ai_server_env.sh or set AI_SERVER_VENV_DIR." >&2
    return 1
  fi
  if [ "${VISION_MODEL_WORKER_ENABLED}" = "true" ] && [ ! -f "${VISION_MODEL_PATH}" ]; then
    echo "ERROR: VISION_MODEL_PATH does not exist: ${VISION_MODEL_PATH}" >&2
    return 1
  fi
  if [ "${VISION_MODEL_WORKER_ENABLED}" = "true" ] && [ -n "${VISION_MODEL_SOURCE_CONFIG_JSON:-}" ]; then
    sf_validate_vision_model_source_config_json "${VISION_MODEL_SOURCE_CONFIG_JSON}"
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
D1 vision bundle config
  root: ${ROOT_DIR}
  ROS_DOMAIN_ID: ${ROS_DOMAIN_ID}
  RMW_IMPLEMENTATION: ${RMW_IMPLEMENTATION}
  ai_server: ${AI_SERVER_HOST}:${AI_SERVER_PORT}
  ai_venv: ${AI_SERVER_VENV_DIR}
  ai_extra_pythonpath: ${AI_SERVER_EXTRA_PYTHONPATH:-<empty>}
  model_enabled: ${VISION_MODEL_WORKER_ENABLED}
  model_path: ${VISION_MODEL_PATH}
  model_imgsz/conf/device: ${VISION_MODEL_IMGSZ}/${VISION_MODEL_CONF}/${VISION_MODEL_DEVICE}
  source/topic: ${VISION_SOURCE_ID} <= ${VISION_IMAGE_TOPIC}
  gateway period/timeout: ${VISION_GATEWAY_PERIOD_SEC}s/${VISION_GATEWAY_REQUEST_TIMEOUT_SEC}s
  qos/pipeline: image=${VISION_GATEWAY_IMAGE_QOS_RELIABILITY}, overlay_pub=${VISION_GATEWAY_OVERLAY_PUB_QOS_RELIABILITY}, overlay_sub=${VISION_STREAM_OVERLAY_SUB_QOS_RELIABILITY}, async=${VISION_GATEWAY_ASYNC_PIPELINE}, inline_process=${VISION_GATEWAY_PROCESS_FRAME_INLINE}, frame_process_path=${VISION_GATEWAY_FRAME_PROCESS_PATH}
  stream_bridge: ${VISION_STREAM_HOST}:${VISION_STREAM_PORT} max_fps=${VISION_STREAM_MAX_FPS}

Main/GUI URLs on this LAN candidate:
  View:   http://${ip}:${VISION_STREAM_PORT}/api/v1/vision/overlay/view?source=${VISION_SOURCE_ID}
  Stream: http://${ip}:${VISION_STREAM_PORT}/api/v1/vision/overlay/stream?source=${VISION_SOURCE_ID}&max_fps=${VISION_STREAM_MAX_FPS}
  Bridge: http://${ip}:${VISION_STREAM_PORT}/api/v1/vision/bridge/status
  AI:     http://${ip}:${AI_SERVER_PORT}/api/v1/health
  Tags:   http://${ip}:${AI_SERVER_PORT}/api/v1/detections/latest?source=${VISION_SOURCE_ID}&limit=10
CONFIG
}

wait_for_ai_server() {
  local url="http://127.0.0.1:${AI_SERVER_PORT}/api/v1/health"
  local timeout_s="${AI_SERVER_START_TIMEOUT_SEC:-45}"
  local start now
  start="$(date +%s)"
  echo "[bundle] waiting for AI Server health: ${url}"
  while true; do
    if command -v curl > /dev/null 2>&1 && curl -fsS --max-time 1 "${url}" > /dev/null 2>&1; then
      echo "[bundle] AI Server is healthy"
      return 0
    fi
    now="$(date +%s)"
    if [ $((now - start)) -ge "${timeout_s}" ]; then
      echo "ERROR: AI Server did not become healthy within ${timeout_s}s" >&2
      return 1
    fi
    sleep 1
  done
}

PIDS=()
NAMES=()

start_ai_server() {
  echo "[bundle] starting AI Server"
  (
    cd "${ROOT_DIR}"
    exec ./scripts/ai/run_ai_server.sh
  ) &
  PIDS+=("$!")
  NAMES+=("ai-server")
  echo "[bundle] ai-server pid=${PIDS[-1]}"
}

start_ros_child() {
  local name="$1"
  shift
  echo "[bundle] starting ${name}"
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
  NAMES+=("${name}")
  echo "[bundle] ${name} pid=${PIDS[-1]}"
}

cleanup() {
  local status=$?
  trap - INT TERM EXIT
  if [ "${#PIDS[@]}" -gt 0 ]; then
    echo "[bundle] stopping ${#PIDS[@]} child process(es)"
    for pid in "${PIDS[@]}"; do
      kill -INT "${pid}" 2> /dev/null || true
    done
    sleep 2
    for pid in "${PIDS[@]}"; do
      kill -TERM "${pid}" 2> /dev/null || true
    done
    wait 2> /dev/null || true
  fi
  exit "${status}"
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
    "")
      ;;
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

  start_ai_server
  wait_for_ai_server

  start_ros_child "vision_frame_gateway" \
    python3 -m smartfactory_perception_ros.vision_frame_gateway --ros-args \
    -p "source_id:=${VISION_SOURCE_ID}" \
    -p "image_topic:=${VISION_IMAGE_TOPIC}" \
    -p "image_transport:=compressed" \
    -p "ai_server_url:=http://127.0.0.1:${AI_SERVER_PORT}" \
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
    -p "publish_evidence:=${VISION_GATEWAY_PUBLISH_EVIDENCE}"

  start_ros_child "vision_overlay_stream_bridge" \
    python3 -m smartfactory_perception_ros.vision_overlay_stream_bridge --ros-args \
    -p "host:=${VISION_STREAM_HOST}" \
    -p "port:=${VISION_STREAM_PORT}" \
    -p "sources:=${VISION_SOURCE_ID}" \
    -p "max_fps:=${VISION_STREAM_MAX_FPS}" \
    -p "stale_after_sec:=${VISION_STREAM_STALE_AFTER_SEC}" \
    -p "overlay_sub_qos_reliability:=${VISION_STREAM_OVERLAY_SUB_QOS_RELIABILITY}" \
    -p "overlay_sub_qos_depth:=${VISION_STREAM_OVERLAY_SUB_QOS_DEPTH}"

  echo "[bundle] D1 vision bundle running. Ctrl-C stops all local child processes."
  set +e
  wait -n "${PIDS[@]}"
  child_status=$?
  set -e
  echo "[bundle] a child process exited (status=${child_status}); shutting down bundle"
  exit "${child_status}"
}

main "$@"
