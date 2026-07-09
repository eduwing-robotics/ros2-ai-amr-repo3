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
Usage: $(basename "$0") [--check|--print-config|--smoke-local|--help]

Official local/Main integration entrypoint.
Runs the Main-compatible single-port D1 vision gateway bundle:
  - AI Server on AI_SERVER_HOST:AI_SERVER_PORT
  - Robot1/domain2 gateway + internal stream bridge
  - Robot2/domain5 gateway + internal stream bridge
  - Public source-based Vision Stream Gateway on 0.0.0.0:8090

Main sees only one base URL:
  LMS_VISION_STREAM_BASE_URL=http://smartfactory-vision.local:8090

Recommended endpoint contract:
  - hostname first: VISION_PUBLIC_HOST=smartfactory-vision.local
  - explicit fallback only: use the detected LAN IP printed by --print-config
    only when Main/operator config sets a fallback URL.

No robot motion, Nav2, teleop, /cmd_vel, robot-side persistent services, or
whole-graph bridge are started.

Makefile aliases are intentionally thin wrappers around this script:
  make vision-check       # preflight this bundle with model worker disabled unless overridden
  make vision-run         # run this bundle
  make vision-config      # print this bundle configuration
  make vision-smoke-local # curl local health/status endpoints if already running

Supporting/debug scripts remain available for narrower cases:
  scripts/ai/run_ai_server.sh                  # AI Server only
  scripts/vision/run_d1_vision_bundle.sh           # single-source bundle
  scripts/vision/run_d1_vision_domain_sidecar.sh   # extra source/domain sidecar
  scripts/vision/run_d1_vision_stream_gateway.py   # public source mux implementation
USAGE
}

set_defaults() {
  export RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"

  export AI_SERVER_HOST="${AI_SERVER_HOST:-0.0.0.0}"
  export AI_SERVER_PORT="${AI_SERVER_PORT:-8100}"
  export AI_SERVER_URL="${AI_SERVER_URL:-http://127.0.0.1:${AI_SERVER_PORT}}"
  export AI_SERVER_VENV_DIR="${AI_SERVER_VENV_DIR:-${ROOT_DIR}/.venv}"
  export VISION_PUBLIC_HOST="${VISION_PUBLIC_HOST:-smartfactory-vision.local}"
  export MAIN_SERVER_URL="${MAIN_SERVER_URL:-http://smartfactory-main.local:8088}"
  if [ -z "${AI_SERVER_EXTRA_PYTHONPATH:-}" ] && [ -d "${DEFAULT_MODEL_EXTRA_PYTHONPATH}" ]; then
    export AI_SERVER_EXTRA_PYTHONPATH="${DEFAULT_MODEL_EXTRA_PYTHONPATH}"
  fi

  export VISION_MODEL_WORKER_ENABLED="${VISION_MODEL_WORKER_ENABLED:-true}"
  # Lightweight default for Main/MJPEG smoke and TurtleBot comparator runs.
  # GoPro segment-overlay proof is an explicit override profile:
  #   VISION_MODEL_TASK=segment
  #   VISION_MODEL_PATH=models/yolov8s-seg.pt
  #   VISION_MODEL_IMGSZ=640
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

  export VISION_SOURCE_1_ID="${VISION_SOURCE_1_ID:-tb3_1_picam}"
  export VISION_SOURCE_1_ENABLED="${VISION_SOURCE_1_ENABLED:-true}"
  export VISION_SOURCE_1_DOMAIN="${VISION_SOURCE_1_DOMAIN:-2}"
  export VISION_SOURCE_1_TOPIC="${VISION_SOURCE_1_TOPIC:-/camera/image_raw/compressed}"
  export VISION_SOURCE_1_INTERNAL_PORT="${VISION_SOURCE_1_INTERNAL_PORT:-18090}"

  export VISION_SOURCE_2_ID="${VISION_SOURCE_2_ID:-tb3_2_picam}"
  export VISION_SOURCE_2_ENABLED="${VISION_SOURCE_2_ENABLED:-true}"
  export VISION_SOURCE_2_DOMAIN="${VISION_SOURCE_2_DOMAIN:-5}"
  export VISION_SOURCE_2_TOPIC="${VISION_SOURCE_2_TOPIC:-/camera/image_raw/compressed}"
  export VISION_SOURCE_2_INTERNAL_PORT="${VISION_SOURCE_2_INTERNAL_PORT:-18091}"

  export VISION_GLOBAL_SOURCE_ID="${VISION_GLOBAL_SOURCE_ID:-global_cam_01}"
  export VISION_GLOBAL_UPSTREAM_URL="${VISION_GLOBAL_UPSTREAM_URL:-${AI_SERVER_URL}}"
  export VISION_STREAM_AI_MJPEG_SOURCES="${VISION_STREAM_AI_MJPEG_SOURCES:-${VISION_GLOBAL_SOURCE_ID}}"

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
  export VISION_GATEWAY_FORCE_WORKER_TICK="${VISION_GATEWAY_FORCE_WORKER_TICK:-true}"
  export VISION_GATEWAY_PUBLISH_OVERLAY="${VISION_GATEWAY_PUBLISH_OVERLAY:-true}"
  export VISION_GATEWAY_PUBLISH_EVIDENCE="${VISION_GATEWAY_PUBLISH_EVIDENCE:-true}"
  export VISION_STREAM_MAX_FPS="${VISION_STREAM_MAX_FPS:-30.0}"
  export VISION_STREAM_STALE_AFTER_SEC="${VISION_STREAM_STALE_AFTER_SEC:-2.0}"
  export VISION_STREAM_OVERLAY_SUB_QOS_RELIABILITY="${VISION_STREAM_OVERLAY_SUB_QOS_RELIABILITY:-reliable}"
  export VISION_STREAM_OVERLAY_SUB_QOS_DEPTH="${VISION_STREAM_OVERLAY_SUB_QOS_DEPTH:-1}"

  export VISION_STREAM_GATEWAY_HOST="${VISION_STREAM_GATEWAY_HOST:-0.0.0.0}"
  export VISION_STREAM_GATEWAY_PORT="${VISION_STREAM_GATEWAY_PORT:-8090}"
  export VISION_STREAM_SOURCE_UPSTREAMS_JSON="${VISION_STREAM_SOURCE_UPSTREAMS_JSON:-{\"${VISION_GLOBAL_SOURCE_ID}\":\"${VISION_GLOBAL_UPSTREAM_URL}\",\"${VISION_SOURCE_1_ID}\":\"http://127.0.0.1:${VISION_SOURCE_1_INTERNAL_PORT}\",\"${VISION_SOURCE_2_ID}\":\"http://127.0.0.1:${VISION_SOURCE_2_INTERNAL_PORT}\"}}"
}

check_prereqs() {
  if [ ! -f "${ROS_SETUP}" ]; then
    echo "ERROR: ROS setup not found: ${ROS_SETUP}" >&2
    return 1
  fi
  if [ ! -x "${AI_SERVER_VENV_DIR}/bin/uvicorn" ]; then
    echo "ERROR: AI Server venv not found at ${AI_SERVER_VENV_DIR}" >&2
    return 1
  fi
  if [ "${VISION_MODEL_WORKER_ENABLED}" = "true" ] && [ ! -f "${VISION_MODEL_PATH}" ]; then
    echo "ERROR: VISION_MODEL_PATH does not exist: ${VISION_MODEL_PATH}" >&2
    return 1
  fi
  if [ "${VISION_MODEL_WORKER_ENABLED}" = "true" ] && [ -n "${VISION_MODEL_SOURCE_CONFIG_JSON:-}" ]; then
    sf_validate_vision_model_source_config_json "${VISION_MODEL_SOURCE_CONFIG_JSON}"
  fi
  warn_ros_discovery_config
  python3 -m py_compile "${ROOT_DIR}/scripts/vision/run_d1_vision_stream_gateway.py"
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
  local ip public_host ros_setup
  ip="$(sf_lan_ip "${VISION_MAIN_HOST:-}")"
  ip="${ip:-127.0.0.1}"
  public_host="${VISION_PUBLIC_HOST:-smartfactory-vision.local}"
  ros_setup="${ROS_SETUP:-/opt/ros/${ROS_DISTRO:-jazzy}/setup.bash}"
  cat << CONFIG
D1 Main-compatible multi-source gateway bundle
  root: ${ROOT_DIR}
  ai_server: ${AI_SERVER_HOST}:${AI_SERVER_PORT}
  public_host: ${public_host}
  public_gateway: ${VISION_STREAM_GATEWAY_HOST}:${VISION_STREAM_GATEWAY_PORT}
  source1: ${VISION_SOURCE_1_ID}, enabled=${VISION_SOURCE_1_ENABLED}, domain=${VISION_SOURCE_1_DOMAIN}, topic=${VISION_SOURCE_1_TOPIC}, internal_port=${VISION_SOURCE_1_INTERNAL_PORT}
  source2: ${VISION_SOURCE_2_ID}, enabled=${VISION_SOURCE_2_ENABLED}, domain=${VISION_SOURCE_2_DOMAIN}, topic=${VISION_SOURCE_2_TOPIC}, internal_port=${VISION_SOURCE_2_INTERNAL_PORT}
  global_source: ${VISION_GLOBAL_SOURCE_ID}, upstream=${VISION_GLOBAL_UPSTREAM_URL}, ingest=HTTP /api/v1/vision/frame/process
  ai_mjpeg_sources: ${VISION_STREAM_AI_MJPEG_SOURCES}
  qos: image_sub=${VISION_GATEWAY_IMAGE_QOS_RELIABILITY}, overlay_pub=${VISION_GATEWAY_OVERLAY_PUB_QOS_RELIABILITY}, overlay_sub=${VISION_STREAM_OVERLAY_SUB_QOS_RELIABILITY}
  pipeline: async=${VISION_GATEWAY_ASYNC_PIPELINE}, inline_process=${VISION_GATEWAY_PROCESS_FRAME_INLINE}, frame_process_path=${VISION_GATEWAY_FRAME_PROCESS_PATH}, period=${VISION_GATEWAY_PERIOD_SEC}s, output_period=${VISION_GATEWAY_PUBLISH_OUTPUT_PERIOD_SEC}s, retry_failed=${VISION_GATEWAY_RETRY_FAILED_FRAME}
  model_source_config: ${VISION_MODEL_SOURCE_CONFIG_JSON:-<none>}
  upstreams: ${VISION_STREAM_SOURCE_UPSTREAMS_JSON}

ROS/DDS discovery:
  ros_env_file: ${SF_VISION_ROS_ENV_FILE_LOADED:-<none>}
  ROS_DISTRO=${ROS_DISTRO:-<unset>}
  ROS_SETUP=${ros_setup}
  RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-<unset>}
  ROS_AUTOMATIC_DISCOVERY_RANGE=${ROS_AUTOMATIC_DISCOVERY_RANGE:-<unset>}
  ROS_STATIC_PEERS=${ROS_STATIC_PEERS:-<unset>}
  FASTRTPS_DEFAULT_PROFILES_FILE=${FASTRTPS_DEFAULT_PROFILES_FILE:-<unset>}

Main/GUI recommended stable base URLs (hostname-first):
  VISION_API_BASE_URL=http://${public_host}:${AI_SERVER_PORT}
  VISION_STREAM_BASE_URL=http://${public_host}:${VISION_STREAM_GATEWAY_PORT}
  LMS_VISION_STREAM_BASE_URL=http://${public_host}:${VISION_STREAM_GATEWAY_PORT}

Vision -> Main callback settings:
  MAIN_SERVER_URL=${MAIN_SERVER_URL}
  WMS_VISION_EVENTS_PATH=${WMS_VISION_EVENTS_PATH:-/api/v1/vision/events}
  WMS_EMIT_ENABLED=${WMS_EMIT_ENABLED:-false}
  Overlay ${VISION_SOURCE_1_ID}: http://${public_host}:${VISION_STREAM_GATEWAY_PORT}/api/v1/vision/overlay/stream?source=${VISION_SOURCE_1_ID}&max_fps=${VISION_STREAM_MAX_FPS}
  Overlay ${VISION_SOURCE_2_ID}: http://${public_host}:${VISION_STREAM_GATEWAY_PORT}/api/v1/vision/overlay/stream?source=${VISION_SOURCE_2_ID}&max_fps=${VISION_STREAM_MAX_FPS}
  Overlay ${VISION_GLOBAL_SOURCE_ID} full:     http://${public_host}:${VISION_STREAM_GATEWAY_PORT}/api/v1/vision/overlay/stream?source=${VISION_GLOBAL_SOURCE_ID}&view=full&max_fps=${VISION_STREAM_MAX_FPS}
  Overlay ${VISION_GLOBAL_SOURCE_ID} lift_roi: http://${public_host}:${VISION_STREAM_GATEWAY_PORT}/api/v1/vision/overlay/stream?source=${VISION_GLOBAL_SOURCE_ID}&view=lift_roi&max_fps=${VISION_STREAM_MAX_FPS}
  Raw ${VISION_SOURCE_1_ID}:     http://${public_host}:${VISION_STREAM_GATEWAY_PORT}/api/v1/vision/frame/stream?source=${VISION_SOURCE_1_ID}&max_fps=${VISION_STREAM_MAX_FPS}
  Raw ${VISION_SOURCE_2_ID}:     http://${public_host}:${VISION_STREAM_GATEWAY_PORT}/api/v1/vision/frame/stream?source=${VISION_SOURCE_2_ID}&max_fps=${VISION_STREAM_MAX_FPS}
  Raw ${VISION_GLOBAL_SOURCE_ID}:     http://${public_host}:${VISION_STREAM_GATEWAY_PORT}/api/v1/vision/frame/stream?source=${VISION_GLOBAL_SOURCE_ID}&max_fps=${VISION_STREAM_MAX_FPS}
  Status:            http://${public_host}:${VISION_STREAM_GATEWAY_PORT}/api/v1/vision/bridge/status

Detected LAN fallback evidence (configure explicitly only if hostname resolution fails):
  detected_lan_ip=${ip}
  VISION_API_FALLBACK_BASE_URL=http://${ip}:${AI_SERVER_PORT}
  VISION_STREAM_FALLBACK_BASE_URL=http://${ip}:${VISION_STREAM_GATEWAY_PORT}
  LMS_VISION_STREAM_FALLBACK_BASE_URL=http://${ip}:${VISION_STREAM_GATEWAY_PORT}
CONFIG
}

warn_ros_discovery_config() {
  if ! is_truthy "${VISION_SOURCE_1_ENABLED:-true}" && ! is_truthy "${VISION_SOURCE_2_ENABLED:-true}"; then
    return 0
  fi
  if [ "${RMW_IMPLEMENTATION:-}" != "rmw_fastrtps_cpp" ]; then
    echo "[multi-gateway] WARN: PiCam sources are enabled but RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-<unset>} (expected rmw_fastrtps_cpp for the current FastDDS robot setup)" >&2
  fi
  if [ "${ROS_AUTOMATIC_DISCOVERY_RANGE:-}" != "LOCALHOST" ]; then
    echo "[multi-gateway] WARN: PiCam sources are enabled but ROS_AUTOMATIC_DISCOVERY_RANGE=${ROS_AUTOMATIC_DISCOVERY_RANGE:-<unset>} (expected LOCALHOST with static peers)" >&2
  fi
  if [ -z "${ROS_STATIC_PEERS:-}" ]; then
    echo "[multi-gateway] WARN: PiCam sources are enabled but ROS_STATIC_PEERS is empty; FastDDS LOCALHOST/static-peer robot discovery may fail" >&2
  fi
}

PIDS=()
cleanup() {
  local status=$?
  trap - INT TERM EXIT
  if [ "${#PIDS[@]}" -gt 0 ]; then
    echo "[multi-gateway] stopping ${#PIDS[@]} child process(es)"
    for pid in "${PIDS[@]}"; do kill -INT "${pid}" 2> /dev/null || true; done
    sleep 2
    for pid in "${PIDS[@]}"; do kill -TERM "${pid}" 2> /dev/null || true; done
    wait 2> /dev/null || true
  fi
  exit "${status}"
}

start_ai_server() {
  echo "[multi-gateway] starting AI Server"
  (
    cd "${ROOT_DIR}"
    exec ./scripts/ai/run_ai_server.sh
  ) &
  PIDS+=("$!")
  echo "[multi-gateway] ai-server pid=${PIDS[-1]}"
}

wait_for_ai_server() {
  local url="${AI_SERVER_URL%/}/api/v1/health"
  local timeout_s="${AI_SERVER_START_TIMEOUT_SEC:-45}"
  local start now
  start="$(date +%s)"
  echo "[multi-gateway] waiting for AI Server health: ${url}"
  while true; do
    if command -v curl > /dev/null 2>&1 && curl -fsS --max-time 1 "${url}" > /dev/null 2>&1; then
      echo "[multi-gateway] AI Server is healthy"
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

start_ros_child() {
  local name="$1"
  local domain="$2"
  shift 2
  echo "[multi-gateway] starting ${name} (ROS_DOMAIN_ID=${domain})"
  (
    # shellcheck disable=SC1090
    unset PYTHONPATH
    set +u
    source "${ROS_SETUP}"
    set -u
    export ROS_DOMAIN_ID="${domain}"
    export RMW_IMPLEMENTATION
    export PYTHONPATH="${LOCAL_ROS_PYTHONPATH}${PYTHONPATH:+:${PYTHONPATH}}"
    exec "$@"
  ) &
  PIDS+=("$!")
  echo "[multi-gateway] ${name} pid=${PIDS[-1]}"
}

start_source_pair() {
  local source_id="$1"
  local domain="$2"
  local image_topic="$3"
  local internal_port="$4"
  local overlay_topic="/sf/vision/sources/${source_id}/overlay/compressed"

  start_ros_child "vision_frame_gateway:${source_id}" "${domain}" \
    python3 -m smartfactory_perception_ros.vision_frame_gateway --ros-args \
    -p "source_id:=${source_id}" \
    -p "image_topic:=${image_topic}" \
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
    -p "process_with_worker_tick:=true" \
    -p "force_worker_tick:=${VISION_GATEWAY_FORCE_WORKER_TICK}" \
    -p "publish_overlay:=${VISION_GATEWAY_PUBLISH_OVERLAY}" \
    -p "publish_evidence:=${VISION_GATEWAY_PUBLISH_EVIDENCE}" \
    -p "overlay_topic:=${overlay_topic}" \
    -p "evidence_topic:=/sf/vision/events"

  start_ros_child "vision_overlay_stream_bridge:${source_id}" "${domain}" \
    python3 -m smartfactory_perception_ros.vision_overlay_stream_bridge --ros-args \
    -p "host:=127.0.0.1" \
    -p "port:=${internal_port}" \
    -p "sources:=${source_id}" \
    -p "max_fps:=${VISION_STREAM_MAX_FPS}" \
    -p "stale_after_sec:=${VISION_STREAM_STALE_AFTER_SEC}" \
    -p "overlay_sub_qos_reliability:=${VISION_STREAM_OVERLAY_SUB_QOS_RELIABILITY}" \
    -p "overlay_sub_qos_depth:=${VISION_STREAM_OVERLAY_SUB_QOS_DEPTH}"
}

smoke_local() {
  local ai_health_url="${AI_SERVER_URL%/}/api/v1/health"
  local gateway_host="127.0.0.1"
  local gateway_status_url="http://${gateway_host}:${VISION_STREAM_GATEWAY_PORT}/api/v1/vision/bridge/status"

  if ! command -v curl > /dev/null 2>&1; then
    echo "ERROR: curl is required for --smoke-local" >&2
    return 1
  fi

  echo "[multi-gateway] smoke: AI Server health ${ai_health_url}"
  curl -fsS --max-time 2 "${ai_health_url}" > /dev/null
  echo "[multi-gateway] smoke: public Vision Stream Gateway status ${gateway_status_url}"
  curl -fsS --max-time 2 "${gateway_status_url}" > /dev/null
  echo "[multi-gateway] smoke-local: ok"
}

start_public_gateway() {
  echo "[multi-gateway] starting public Vision Stream Gateway"
  (
    cd "${ROOT_DIR}"
    exec python3 scripts/vision/run_d1_vision_stream_gateway.py
  ) &
  PIDS+=("$!")
  echo "[multi-gateway] public-gateway pid=${PIDS[-1]}"
}

is_truthy() {
  case "${1:-}" in
    1 | true | TRUE | yes | YES | y | Y | on | ON) return 0 ;;
    *) return 1 ;;
  esac
}

main() {
  case "${1:-}" in
    --help | -h)
      usage
      exit 0
      ;;
    --check)
      sf_load_ros_network_env "${ROOT_DIR}"
      set_defaults
      check_prereqs
      print_config
      exit 0
      ;;
    --print-config)
      sf_load_ros_network_env "${ROOT_DIR}"
      set_defaults
      print_config
      exit 0
      ;;
    --smoke-local)
      sf_load_ros_network_env "${ROOT_DIR}"
      set_defaults
      smoke_local
      exit 0
      ;;
    "") ;;
    *)
      echo "ERROR: unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
	  esac

  sf_load_ros_network_env "${ROOT_DIR}"
  set_defaults
  check_prereqs
  print_config
  trap cleanup INT TERM EXIT

  start_ai_server
  wait_for_ai_server
  if is_truthy "${VISION_SOURCE_1_ENABLED}"; then
    start_source_pair "${VISION_SOURCE_1_ID}" "${VISION_SOURCE_1_DOMAIN}" "${VISION_SOURCE_1_TOPIC}" "${VISION_SOURCE_1_INTERNAL_PORT}"
  else
    echo "[multi-gateway] source disabled: ${VISION_SOURCE_1_ID}"
  fi
  if is_truthy "${VISION_SOURCE_2_ENABLED}"; then
    start_source_pair "${VISION_SOURCE_2_ID}" "${VISION_SOURCE_2_DOMAIN}" "${VISION_SOURCE_2_TOPIC}" "${VISION_SOURCE_2_INTERNAL_PORT}"
  else
    echo "[multi-gateway] source disabled: ${VISION_SOURCE_2_ID}"
  fi
  start_public_gateway

  echo "[multi-gateway] running. Ctrl-C stops all local child processes."
  set +e
  wait -n "${PIDS[@]}"
  child_status=$?
  set -e
  echo "[multi-gateway] a child process exited (status=${child_status}); shutting down bundle"
  exit "${child_status}"
}

main "$@"
