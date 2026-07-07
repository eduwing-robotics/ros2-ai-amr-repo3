#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/vision_bundle_common.sh
source "${SCRIPT_DIR}/../lib/vision_bundle_common.sh"
ROOT_DIR="$(sf_repo_root_from_script "${BASH_SOURCE[0]}")"
PROFILE_DIR="${ROOT_DIR}/config/vision/profiles"
RUN_DIR="${SMARTFACTORY_VISION_RUN_DIR:-${ROOT_DIR}/.run/vision}"
LOG_DIR="${RUN_DIR}/logs"
PID_FILE="${RUN_DIR}/pids.tsv"
SUPERVISOR_PID_FILE="${RUN_DIR}/supervisor.pid"
SUMMARY_FILE="${RUN_DIR}/summary.env"
WARNINGS_FILE="${RUN_DIR}/warnings.log"
DEFAULT_PROFILE="lab-gopro-tb3"

PROFILE=""
PROFILE_FILE=""
PIDS=()
REQUIRED_PIDS=()
NAMES=()
LOGS=()
OPTIONAL_WARNINGS=()
LAST_STARTED_PID=""
LAST_STARTED_LOG=""
LAST_STARTED_NAME=""
GOPRO_STREAM_AVAILABLE=false

usage() {
  cat << USAGE
Usage: $(basename "$0") <command> [profile]

Operator entrypoint for SmartFactory Vision runtime. Long-running processes are
supervised as one local process group and remain media/evidence-only.

Commands:
  profiles                 List available profiles
  print-config [profile]   Print resolved operator config without starting live processes
  check [profile]          Run non-live preflight checks
  up [profile]             Start live Vision runtime in the foreground
  status                   Show recorded process status and local endpoint health
  smoke                    Curl local AI/gateway/discovery/WebRTC-fallback endpoints
  logs [name]              Tail all logs or one named log
  down                     Stop the supervised Vision runtime

Default profile: ${DEFAULT_PROFILE}

Typical demo:
  ./scripts/vision/sf_vision.sh up lab-gopro-tb3
  ./scripts/vision/sf_vision.sh status
  ./scripts/vision/sf_vision.sh smoke
  ./scripts/vision/sf_vision.sh down

Recommended lab WebRTC demo:
  ./scripts/vision/sf_vision.sh up lab-gopro-tb3-ffmpeg-first

Low-load lab WebRTC demo:
  ./scripts/vision/sf_vision.sh up lab-gopro-tb3-low-load

Rollback/comparison WebRTC demo:
  ./scripts/vision/sf_vision.sh up lab-gopro-tb3-webrtc

Safety boundary: this script does not start robot motion, Nav2, teleop,
/cmd_vel, ROS parameter mutation, or a whole-graph rosbridge.
USAGE
}

is_truthy() {
  case "${1:-}" in
    1 | true | TRUE | yes | YES | y | Y | on | ON) return 0 ;;
    *) return 1 ;;
  esac
}

list_profiles() {
  local file name
  for file in "${PROFILE_DIR}"/*.env; do
    [ -e "${file}" ] || continue
    name="$(basename "${file}" .env)"
    printf '%s\n' "${name}"
  done | sort
}

load_profile() {
  PROFILE="${1:-${DEFAULT_PROFILE}}"
  PROFILE_FILE="${PROFILE_DIR}/${PROFILE}.env"
  if [ ! -f "${PROFILE_FILE}" ]; then
    echo "ERROR: unknown profile '${PROFILE}'" >&2
    echo "Available profiles:" >&2
    list_profiles >&2
    return 2
  fi

  cd "${ROOT_DIR}"
  set -a
  # shellcheck disable=SC1090
  source "${PROFILE_FILE}"
  if [ -n "${SF_VISION_RUNTIME_OVERRIDE_FILE:-}" ]; then
    if [ ! -f "${SF_VISION_RUNTIME_OVERRIDE_FILE}" ]; then
      echo "ERROR: SF_VISION_RUNTIME_OVERRIDE_FILE not found: ${SF_VISION_RUNTIME_OVERRIDE_FILE}" >&2
      return 2
    fi
    # shellcheck disable=SC1090
    source "${SF_VISION_RUNTIME_OVERRIDE_FILE}"
  fi
  set +a

  RUN_DIR="${SMARTFACTORY_VISION_RUN_DIR:-${ROOT_DIR}/.run/vision}"
  LOG_DIR="${RUN_DIR}/logs"
  PID_FILE="${RUN_DIR}/pids.tsv"
  SUPERVISOR_PID_FILE="${RUN_DIR}/supervisor.pid"
  SUMMARY_FILE="${RUN_DIR}/summary.env"
  WARNINGS_FILE="${RUN_DIR}/warnings.log"
  export SMARTFACTORY_VISION_RUN_DIR="${RUN_DIR}"

  export AI_SERVER_HOST="${AI_SERVER_HOST:-0.0.0.0}"
  export AI_SERVER_PORT="${AI_SERVER_PORT:-8100}"
  export AI_SERVER_URL="${AI_SERVER_URL:-http://127.0.0.1:${AI_SERVER_PORT}}"
  export AI_SERVER_VENV_DIR="${AI_SERVER_VENV_DIR:-${ROOT_DIR}/.venv}"
  export VISION_STREAM_GATEWAY_PORT="${VISION_STREAM_GATEWAY_PORT:-8090}"
  export VISION_PUBLIC_HOST="${VISION_PUBLIC_HOST:-smartfactory-vision.local}"
  export MAIN_SERVER_URL="${MAIN_SERVER_URL:-http://smartfactory-main.local:8088}"
  export WMS_EMIT_ENABLED="${WMS_EMIT_ENABLED:-false}"
  export VISION_WEBRTC_ENABLED="${VISION_WEBRTC_ENABLED:-true}"
  export AI_SERVER_CORS_ALLOW_ORIGINS="${AI_SERVER_CORS_ALLOW_ORIGINS:-http://smartfactory-main.local:8088,http://localhost:8088,http://127.0.0.1:8088}"
  export SF_VISION_MDNS_ENABLED="${SF_VISION_MDNS_ENABLED:-true}"
  export SF_VISION_BUNDLE_ENABLED="${SF_VISION_BUNDLE_ENABLED:-true}"
  export SF_VISION_GOPRO_ENABLED="${SF_VISION_GOPRO_ENABLED:-false}"
  export SF_VISION_GOPRO_REQUIRED="${SF_VISION_GOPRO_REQUIRED:-false}"
  export SF_VISION_OPTIONAL_CHILD_GRACE_SEC="${SF_VISION_OPTIONAL_CHILD_GRACE_SEC:-1}"
  export GOPRO_PORT="${GOPRO_PORT:-8554}"
  export GOPRO_PROTOCOL="${GOPRO_PROTOCOL:-TS}"
  export GOPRO_RESOLUTION="${GOPRO_RESOLUTION:-1080}"
  export GOPRO_FOV="${GOPRO_FOV:-WIDE}"
  export GOPRO_TEST_READ="${GOPRO_TEST_READ:-true}"
  export GOPRO_STREAM_WARMUP_SEC="${GOPRO_STREAM_WARMUP_SEC:-8}"
  export GOPRO_INPUT="${GOPRO_INPUT:-udp://0.0.0.0:${GOPRO_PORT}?overrun_nonfatal=1&fifo_size=50000000}"
  export GOPRO_ADAPTER_INPUT="${GOPRO_ADAPTER_INPUT:-${GOPRO_INPUT}}"
  export GOPRO_SOURCE="${GOPRO_SOURCE:-global_cam_01}"
  export GOPRO_ROI_VIEW="${GOPRO_ROI_VIEW:-lift_roi}"
  export GOPRO_TARGET_FPS="${GOPRO_TARGET_FPS:-5}"
  export GOPRO_STREAM_TARGET_FPS="${GOPRO_STREAM_TARGET_FPS:-30}"
  export GOPRO_AI_MONITOR_FPS="${GOPRO_AI_MONITOR_FPS:-${GOPRO_TARGET_FPS}}"
  export GOPRO_AI_MONITOR_IMGSZ="${GOPRO_AI_MONITOR_IMGSZ:-${VISION_MODEL_IMGSZ:-640}}"
  export GOPRO_EVIDENCE_IMGSZ="${GOPRO_EVIDENCE_IMGSZ:-960}"
  export GOPRO_DROPPED_ITEM_CONF="${GOPRO_DROPPED_ITEM_CONF:-0.25}"
  export GOPRO_PUBLISH_WEBRTC="${GOPRO_PUBLISH_WEBRTC:-false}"
  export GOPRO_PUBLISH_ROI_WEBRTC="${GOPRO_PUBLISH_ROI_WEBRTC:-true}"
  export GOPRO_WEBRTC_STALE_OVERLAY_AFTER_MS="${GOPRO_WEBRTC_STALE_OVERLAY_AFTER_MS:-1500}"
  export GOPRO_WEBRTC_METRICS_DIR="${GOPRO_WEBRTC_METRICS_DIR:-${VISION_WEBRTC_COMPOSITOR_METRICS_DIR:-${SMARTFACTORY_VISION_RUN_DIR:-.run/vision}/compositor-metrics}}"
  export GOPRO_EVIDENCE_CAPTURE_MODE="${GOPRO_EVIDENCE_CAPTURE_MODE:-parallel_then_pause_then_stream_frame}"
  export GOPRO_EVIDENCE_RUNTIME_SCOPE="${GOPRO_EVIDENCE_RUNTIME_SCOPE:-plan_mock_no_hardware}"
  export GOPRO_BUFFERLESS="${GOPRO_BUFFERLESS:-true}"
  export GOPRO_OPERATION="${GOPRO_OPERATION:-MONITOR}"
  export SF_VISION_GOPRO_ADAPTER_AFTER_WEBRTC_SIDECAR="${SF_VISION_GOPRO_ADAPTER_AFTER_WEBRTC_SIDECAR:-false}"
  export SF_VISION_GOPRO_MEDIAMTX_READY_PATH="${SF_VISION_GOPRO_MEDIAMTX_READY_PATH-${GOPRO_SOURCE}_full}"
  export SF_VISION_GOPRO_MEDIAMTX_READY_TIMEOUT_SEC="${SF_VISION_GOPRO_MEDIAMTX_READY_TIMEOUT_SEC:-30}"
  export FFPROBE_TIMEOUT_SEC="${FFPROBE_TIMEOUT_SEC:-3}"
  export FFPROBE_TIMEOUT_US="${FFPROBE_TIMEOUT_US:-3000000}"
  export VISION_SOURCE_1_ENABLED="${VISION_SOURCE_1_ENABLED:-true}"
  export VISION_SOURCE_1_ID="${VISION_SOURCE_1_ID:-tb3_1_picam}"
  export VISION_SOURCE_2_ENABLED="${VISION_SOURCE_2_ENABLED:-true}"
  export VISION_SOURCE_2_ID="${VISION_SOURCE_2_ID:-tb3_2_picam}"
  export PICAM_PUBLISH_WEBRTC="${PICAM_PUBLISH_WEBRTC:-false}"
  export PICAM_WEBRTC_TARGET_FPS="${PICAM_WEBRTC_TARGET_FPS:-30}"
  export PICAM_WEBRTC_AI_FPS="${PICAM_WEBRTC_AI_FPS:-5}"
  export PICAM_WEBRTC_METRICS_DIR="${PICAM_WEBRTC_METRICS_DIR:-${VISION_WEBRTC_COMPOSITOR_METRICS_DIR:-${SMARTFACTORY_VISION_RUN_DIR:-.run/vision}/compositor-metrics}}"
  export SF_VISION_WEBRTC_SIDECAR_ENABLED="${SF_VISION_WEBRTC_SIDECAR_ENABLED:-false}"
  export SF_VISION_SWEEP_STALE_WEBRTC="${SF_VISION_SWEEP_STALE_WEBRTC:-true}"
  export MEDIAMTX_RTSP_PORT="${MEDIAMTX_RTSP_PORT:-18554}"
  export MEDIAMTX_WEBRTC_PORT="${MEDIAMTX_WEBRTC_PORT:-8889}"
  export MEDIAMTX_WEBRTC_ICE_UDP_PORT="${MEDIAMTX_WEBRTC_ICE_UDP_PORT:-8189}"
  export MEDIAMTX_API_PORT="${MEDIAMTX_API_PORT:-19997}"
  export FFPROBE_BIN="${FFPROBE_BIN:-ffprobe}"
  export MEDIAMTX_WEBRTC_ALLOW_ORIGINS="${MEDIAMTX_WEBRTC_ALLOW_ORIGINS:-http://smartfactory-main.local:8088,http://localhost:8088,http://127.0.0.1:8088}"
  export WEBRTC_SIDECAR_PUBLIC_HOST="${WEBRTC_SIDECAR_PUBLIC_HOST:-${VISION_PUBLIC_HOST}}"
  export WEBRTC_SIDECAR_STREAMS="${WEBRTC_SIDECAR_STREAMS:-${GOPRO_SOURCE}/full,${GOPRO_SOURCE}/${GOPRO_ROI_VIEW}}"
  export VISION_WEBRTC_SIDECAR_STREAMS="${VISION_WEBRTC_SIDECAR_STREAMS:-${WEBRTC_SIDECAR_STREAMS}}"
  export WEBRTC_SIDECAR_COMPOSITOR_PUBLISHER_STREAMS="${WEBRTC_SIDECAR_COMPOSITOR_PUBLISHER_STREAMS:-${VISION_WEBRTC_COMPOSITOR_PUBLISHER_STREAMS:-}}"
  export VISION_WEBRTC_COMPOSITOR_PUBLISHER_STREAMS="${VISION_WEBRTC_COMPOSITOR_PUBLISHER_STREAMS:-${WEBRTC_SIDECAR_COMPOSITOR_PUBLISHER_STREAMS}}"
  export VISION_WEBRTC_COMPOSITOR_METRICS_DIR="${VISION_WEBRTC_COMPOSITOR_METRICS_DIR:-${SMARTFACTORY_VISION_RUN_DIR:-.run/vision}/compositor-metrics}"
  export WEBRTC_SIDECAR_COMPOSITOR_METRICS_DIR="${WEBRTC_SIDECAR_COMPOSITOR_METRICS_DIR:-${VISION_WEBRTC_COMPOSITOR_METRICS_DIR}}"
  export VISION_WEBRTC_COMPOSITOR_HEARTBEAT_MAX_AGE_S="${VISION_WEBRTC_COMPOSITOR_HEARTBEAT_MAX_AGE_S:-5}"
  export WEBRTC_SIDECAR_INPUT_MAX_FPS="${WEBRTC_SIDECAR_INPUT_MAX_FPS:-15}"
  export WEBRTC_SIDECAR_TARGET_FPS="${WEBRTC_SIDECAR_TARGET_FPS:-15}"
  export SF_VISION_TMUX_GUARD_ENABLED="${SF_VISION_TMUX_GUARD_ENABLED:-false}"
  export SF_VISION_TMUX_REQUIRED_CONTEXT="${SF_VISION_TMUX_REQUIRED_CONTEXT:-Smartfactory:3:Development}"
  if is_truthy "${SF_VISION_WEBRTC_SIDECAR_ENABLED}"; then
    if [ -z "${VISION_WEBRTC_SIDECAR_WHEP_URL_TEMPLATE:-}" ]; then
      VISION_WEBRTC_SIDECAR_WHEP_URL_TEMPLATE="http://${WEBRTC_SIDECAR_PUBLIC_HOST}:${MEDIAMTX_WEBRTC_PORT}/{source}_{view}/whep"
    fi
    if [ -z "${VISION_WEBRTC_SIDECAR_BROWSER_URL_TEMPLATE:-}" ]; then
      VISION_WEBRTC_SIDECAR_BROWSER_URL_TEMPLATE="http://${WEBRTC_SIDECAR_PUBLIC_HOST}:${MEDIAMTX_WEBRTC_PORT}/{source}_{view}"
    fi
    if [ -z "${VISION_WEBRTC_SIDECAR_HEALTH_URL:-}" ]; then
      VISION_WEBRTC_SIDECAR_HEALTH_URL="http://127.0.0.1:${MEDIAMTX_WEBRTC_PORT}/"
    fi
    export VISION_WEBRTC_SIDECAR_WHEP_URL_TEMPLATE
    export VISION_WEBRTC_SIDECAR_BROWSER_URL_TEMPLATE
    export VISION_WEBRTC_SIDECAR_HEALTH_URL
    export VISION_WEBRTC_SIDECAR_PATHS_API_URL="${VISION_WEBRTC_SIDECAR_PATHS_API_URL:-http://127.0.0.1:${MEDIAMTX_API_PORT}/v3/paths/list}"
    export VISION_WEBRTC_SIDECAR_HEALTH_TIMEOUT_S="${VISION_WEBRTC_SIDECAR_HEALTH_TIMEOUT_S:-0.25}"
  else
    export VISION_WEBRTC_SIDECAR_WHEP_URL_TEMPLATE="${VISION_WEBRTC_SIDECAR_WHEP_URL_TEMPLATE:-}"
    export VISION_WEBRTC_SIDECAR_BROWSER_URL_TEMPLATE="${VISION_WEBRTC_SIDECAR_BROWSER_URL_TEMPLATE:-}"
    export VISION_WEBRTC_SIDECAR_HEALTH_URL="${VISION_WEBRTC_SIDECAR_HEALTH_URL:-}"
    export VISION_WEBRTC_SIDECAR_PATHS_API_URL="${VISION_WEBRTC_SIDECAR_PATHS_API_URL:-}"
    export VISION_WEBRTC_SIDECAR_HEALTH_TIMEOUT_S="${VISION_WEBRTC_SIDECAR_HEALTH_TIMEOUT_S:-0.25}"
  fi
}

public_base_url() {
  printf 'http://%s:%s\n' "${VISION_PUBLIC_HOST}" "${VISION_STREAM_GATEWAY_PORT:-8090}"
}

api_base_url() {
  printf 'http://%s:%s\n' "${VISION_PUBLIC_HOST}" "${AI_SERVER_PORT:-8100}"
}

print_config() {
  local ip
  ip="$(sf_lan_ip "${VISION_MAIN_HOST:-}" || true)"
  ip="${ip:-127.0.0.1}"
  cat << CONFIG
SmartFactory Vision operator config
  profile: ${PROFILE}
  profile_file: ${PROFILE_FILE}
  description: ${SF_VISION_DESCRIPTION:-<none>}
  run_dir: ${RUN_DIR}
  logs: ${LOG_DIR}

Processes selected by profile:
  mdns_alias: ${SF_VISION_MDNS_ENABLED}
  local_bundle: ${SF_VISION_BUNDLE_ENABLED}
  gopro_stream_adapter: ${SF_VISION_GOPRO_ENABLED}
  gopro_required: ${SF_VISION_GOPRO_REQUIRED}
  source1_enabled: ${VISION_SOURCE_1_ENABLED:-true} (${VISION_SOURCE_1_ID:-tb3_1_picam}, domain=${VISION_SOURCE_1_DOMAIN:-2})
  source2_enabled: ${VISION_SOURCE_2_ENABLED:-true} (${VISION_SOURCE_2_ID:-tb3_2_picam}, domain=${VISION_SOURCE_2_DOMAIN:-5})
  picam_publish_webrtc: ${PICAM_PUBLISH_WEBRTC}

Main-facing URLs:
  VISION_API_BASE_URL=$(api_base_url)
  VISION_STREAM_BASE_URL=$(public_base_url)
  LMS_VISION_STREAM_BASE_URL=$(public_base_url)
  detected_lan_fallback=http://${ip}:${VISION_STREAM_GATEWAY_PORT}

WebRTC status:
  VISION_WEBRTC_ENABLED=${VISION_WEBRTC_ENABLED}
  SF_VISION_WEBRTC_SIDECAR_ENABLED=${SF_VISION_WEBRTC_SIDECAR_ENABLED}
  VISION_WEBRTC_SIDECAR_OFFER_URL_TEMPLATE=${VISION_WEBRTC_SIDECAR_OFFER_URL_TEMPLATE:-<empty>}
  VISION_WEBRTC_SIDECAR_WHEP_URL_TEMPLATE=${VISION_WEBRTC_SIDECAR_WHEP_URL_TEMPLATE:-<empty>}
  VISION_WEBRTC_SIDECAR_BROWSER_URL_TEMPLATE=${VISION_WEBRTC_SIDECAR_BROWSER_URL_TEMPLATE:-<empty>}
  VISION_WEBRTC_SIDECAR_HEALTH_URL=${VISION_WEBRTC_SIDECAR_HEALTH_URL:-<empty>}
  sidecar_streams=${WEBRTC_SIDECAR_STREAMS:-<empty>}
  ai_server_sidecar_streams=${VISION_WEBRTC_SIDECAR_STREAMS:-<empty>}
  compositor_publisher_streams=${WEBRTC_SIDECAR_COMPOSITOR_PUBLISHER_STREAMS:-<empty>}
  compositor_metrics_dir=${VISION_WEBRTC_COMPOSITOR_METRICS_DIR:-<empty>}
  compositor_heartbeat_max_age_s=${VISION_WEBRTC_COMPOSITOR_HEARTBEAT_MAX_AGE_S:-<empty>}
  sidecar_ports=rtsp:${MEDIAMTX_RTSP_PORT:-18554}/tcp,webrtc:${MEDIAMTX_WEBRTC_PORT:-8889}/tcp,ice:${MEDIAMTX_WEBRTC_ICE_UDP_PORT:-8189}/udp
  tmux_guard=${SF_VISION_TMUX_GUARD_ENABLED} required=${SF_VISION_TMUX_REQUIRED_CONTEXT}
  note: without sidecar templates, WebRTC offer intentionally selects MJPEG fallback.

GoPro:
  enabled=${SF_VISION_GOPRO_ENABLED}
  protocol/resolution/fov/port=${GOPRO_PROTOCOL}/${GOPRO_RESOLUTION}/${GOPRO_FOV}/${GOPRO_PORT}
  input=${GOPRO_INPUT}
  adapter_input=${GOPRO_ADAPTER_INPUT}
  adapter_after_webrtc_sidecar=${SF_VISION_GOPRO_ADAPTER_AFTER_WEBRTC_SIDECAR}
  mediamtx_ready_path=${SF_VISION_GOPRO_MEDIAMTX_READY_PATH}
  source/view=${GOPRO_SOURCE}/${GOPRO_ROI_VIEW}
  stream_target_fps=${GOPRO_STREAM_TARGET_FPS}
  ai_monitor_fps=${GOPRO_AI_MONITOR_FPS}
  ai_monitor_imgsz=${GOPRO_AI_MONITOR_IMGSZ}
  evidence_imgsz=${GOPRO_EVIDENCE_IMGSZ}
  dropped_item_conf=${GOPRO_DROPPED_ITEM_CONF}
  publish_webrtc=${GOPRO_PUBLISH_WEBRTC}
  publish_roi_webrtc=${GOPRO_PUBLISH_ROI_WEBRTC}
  webrtc_metrics_dir=${GOPRO_WEBRTC_METRICS_DIR}
  webrtc_stale_overlay_after_ms=${GOPRO_WEBRTC_STALE_OVERLAY_AFTER_MS}
  webrtc_full_output=${GOPRO_WEBRTC_FULL_OUTPUT_WIDTH:-1280}x${GOPRO_WEBRTC_FULL_OUTPUT_HEIGHT:-720}
  webrtc_roi_output=${GOPRO_WEBRTC_ROI_OUTPUT_WIDTH:-640}x${GOPRO_WEBRTC_ROI_OUTPUT_HEIGHT:-480}
  evidence_capture_mode=${GOPRO_EVIDENCE_CAPTURE_MODE}
  evidence_runtime_scope=${GOPRO_EVIDENCE_RUNTIME_SCOPE}
  map_roi_overlay=${VISION_MAP_ROI_ENABLED:-false}
  zone_roi_overlay=${VISION_ZONE_ROI_ENABLED:-false} config=${VISION_ZONE_ROI_CONFIG_PATH:-<unset>}
  legacy_target_fps_alias=${GOPRO_TARGET_FPS}
CONFIG
}

ensure_dirs() {
  mkdir -p "${LOG_DIR}"
}

alive_pid() {
  local pid="${1:-}"
  [ -n "${pid}" ] && kill -0 "${pid}" 2> /dev/null
}

terminate_pid() {
  local label="$1" pid="$2" signal="${3:-TERM}"
  [ -n "${pid:-}" ] || return 0
  [ "${pid}" != "$$" ] || return 0
  if alive_pid "${pid}"; then
    echo "[sf-vision] stopping ${label} pid=${pid}"
    kill "-${signal}" "${pid}" 2> /dev/null || true
    return 0
  fi
}

terminate_processes_matching() {
  local label="$1" needle="$2" signal="${3:-TERM}"
  [ -n "${needle:-}" ] || return 0
  local pid cmd matched=0
  while read -r pid cmd; do
    [ -n "${pid:-}" ] || continue
    [ "${pid}" != "$$" ] || continue
    case "${cmd}" in
      *"${needle}"*)
        terminate_pid "${label}" "${pid}" "${signal}"
        matched=1
        ;;
    esac
  done < <(ps -eo pid=,args=)
  return "${matched}"
}

process_is_ffmpeg() {
  local pid="$1"
  local comm args first
  comm="$(ps -p "${pid}" -o comm= 2> /dev/null | awk '{print $1}' || true)"
  case "${comm}" in
    ffmpeg) return 0 ;;
  esac
  args="$(process_cmd "${pid}")"
  first="${args%% *}"
  case "$(basename -- "${first}")" in
    ffmpeg) return 0 ;;
  esac
  return 1
}

terminate_ffmpeg_processes_matching_all() {
  local label="$1" signal="$2"
  shift 2
  [ "$#" -gt 0 ] || return 0
  local pid cmd needle matched=0 ok
  while read -r pid cmd; do
    [ -n "${pid:-}" ] || continue
    [ "${pid}" != "$$" ] || continue
    process_is_ffmpeg "${pid}" || continue
    ok=1
    for needle in "$@"; do
      case "${cmd}" in
        *"${needle}"*) ;;
        *)
          ok=0
          break
          ;;
      esac
    done
    if [ "${ok}" -eq 1 ]; then
      terminate_pid "${label}" "${pid}" "${signal}"
      matched=1
    fi
  done < <(ps -eo pid=,args=)
  return "${matched}"
}

process_cmd() {
  local pid="$1"
  ps -p "${pid}" -o args= 2> /dev/null || true
}

terminate_recorded_sidecar_pids() {
  local sidecar_run_dir="${RUN_DIR}/webrtc-sidecar"
  local sidecar_pid_file="${sidecar_run_dir}/pids.tsv"
  local mediamtx_config="${sidecar_run_dir}/mediamtx.yml"
  local name pid log cmd

  if [ -f "${sidecar_pid_file}" ]; then
    while IFS=$'\t' read -r name pid log; do
      [ -n "${pid:-}" ] || continue
      cmd="$(process_cmd "${pid}")"
      case "${name}:${cmd}" in
        mediamtx:*"${mediamtx_config}"* | publisher-*:*"${ROOT_DIR}/scripts/vision/run_webrtc_sidecar_mediamtx.sh"*)
          terminate_pid "recorded WebRTC sidecar ${name}" "${pid}" TERM
          ;;
      esac
    done < "${sidecar_pid_file}"
  fi

  local status_file="${sidecar_run_dir}/status.env"
  if [ -f "${status_file}" ]; then
    local mediamtx_pid=""
    mediamtx_pid="$(grep -E '^MEDIAMTX_PID=' "${status_file}" 2> /dev/null | tail -1 | cut -d= -f2- || true)"
    if [ -n "${mediamtx_pid}" ]; then
      cmd="$(process_cmd "${mediamtx_pid}")"
      case "${cmd}" in
        *"${mediamtx_config}"*) terminate_pid "recorded WebRTC sidecar mediamtx" "${mediamtx_pid}" TERM ;;
      esac
    fi
  fi
}

stop_stale_webrtc_sidecar_processes() {
  is_truthy "${SF_VISION_SWEEP_STALE_WEBRTC:-true}" || return 0

  local sidecar_run_dir="${RUN_DIR}/webrtc-sidecar"
  local rtsp_output="rtsp://127.0.0.1:${MEDIAMTX_RTSP_PORT:-18554}/"

  if [ ! -f "${sidecar_run_dir}/pids.tsv" ] && [ ! -f "${sidecar_run_dir}/status.env" ]; then
    return 0
  fi

  terminate_recorded_sidecar_pids
  terminate_ffmpeg_processes_matching_all \
    "stale SmartFactory MJPEG WebRTC publisher" \
    TERM \
    "ffmpeg" \
    "${rtsp_output}" \
    "/api/v1/vision/overlay/stream?source=" || true
}

ensure_not_running() {
  if [ -f "${SUPERVISOR_PID_FILE}" ]; then
    local old_pid
    old_pid="$(cat "${SUPERVISOR_PID_FILE}" 2> /dev/null || true)"
    if alive_pid "${old_pid}"; then
      echo "ERROR: Vision runtime already appears to be running (supervisor pid=${old_pid})." >&2
      echo "Run: ./scripts/vision/sf_vision.sh status or down" >&2
      return 1
    fi
  fi
  rm -f "${PID_FILE}" "${SUPERVISOR_PID_FILE}" "${SUMMARY_FILE}" "${WARNINGS_FILE}"
}

record_summary() {
  cat > "${SUMMARY_FILE}" << SUMMARY
PROFILE=${PROFILE}
PROFILE_FILE=${PROFILE_FILE}
SF_VISION_RUNTIME_OVERRIDE_FILE=${SF_VISION_RUNTIME_OVERRIDE_FILE:-}
SF_RUNTIME_CONTROL_RUN_ID=${SF_RUNTIME_CONTROL_RUN_ID:-}
VISION_API_BASE_URL=$(api_base_url)
VISION_STREAM_BASE_URL=$(public_base_url)
LMS_VISION_STREAM_BASE_URL=$(public_base_url)
AI_SERVER_URL=${AI_SERVER_URL}
MAIN_SERVER_URL=${MAIN_SERVER_URL}
MEDIAMTX_WEBRTC_ALLOW_ORIGINS=${MEDIAMTX_WEBRTC_ALLOW_ORIGINS}
AI_SERVER_CORS_ALLOW_ORIGINS=${AI_SERVER_CORS_ALLOW_ORIGINS}
SF_VISION_WEBRTC_SIDECAR_ENABLED=${SF_VISION_WEBRTC_SIDECAR_ENABLED}
VISION_WEBRTC_SIDECAR_WHEP_URL_TEMPLATE=${VISION_WEBRTC_SIDECAR_WHEP_URL_TEMPLATE:-}
VISION_WEBRTC_SIDECAR_BROWSER_URL_TEMPLATE=${VISION_WEBRTC_SIDECAR_BROWSER_URL_TEMPLATE:-}
VISION_WEBRTC_SIDECAR_HEALTH_URL=${VISION_WEBRTC_SIDECAR_HEALTH_URL:-}
VISION_WEBRTC_SIDECAR_PATHS_API_URL=${VISION_WEBRTC_SIDECAR_PATHS_API_URL:-}
VISION_WEBRTC_SIDECAR_STREAMS=${VISION_WEBRTC_SIDECAR_STREAMS:-}
VISION_WEBRTC_COMPOSITOR_PUBLISHER_STREAMS=${VISION_WEBRTC_COMPOSITOR_PUBLISHER_STREAMS:-}
VISION_WEBRTC_COMPOSITOR_METRICS_DIR=${VISION_WEBRTC_COMPOSITOR_METRICS_DIR:-}
VISION_WEBRTC_COMPOSITOR_HEARTBEAT_MAX_AGE_S=${VISION_WEBRTC_COMPOSITOR_HEARTBEAT_MAX_AGE_S:-}
WEBRTC_SIDECAR_COMPOSITOR_PUBLISHER_STREAMS=${WEBRTC_SIDECAR_COMPOSITOR_PUBLISHER_STREAMS:-}
WEBRTC_SIDECAR_COMPOSITOR_METRICS_DIR=${WEBRTC_SIDECAR_COMPOSITOR_METRICS_DIR:-}
GOPRO_STREAM_TARGET_FPS=${GOPRO_STREAM_TARGET_FPS}
GOPRO_ADAPTER_INPUT=${GOPRO_ADAPTER_INPUT}
GOPRO_AI_MONITOR_FPS=${GOPRO_AI_MONITOR_FPS}
GOPRO_AI_MONITOR_IMGSZ=${GOPRO_AI_MONITOR_IMGSZ}
GOPRO_PUBLISH_WEBRTC=${GOPRO_PUBLISH_WEBRTC}
GOPRO_PUBLISH_ROI_WEBRTC=${GOPRO_PUBLISH_ROI_WEBRTC}
GOPRO_WEBRTC_STALE_OVERLAY_AFTER_MS=${GOPRO_WEBRTC_STALE_OVERLAY_AFTER_MS}
GOPRO_WEBRTC_METRICS_DIR=${GOPRO_WEBRTC_METRICS_DIR}
GOPRO_EVIDENCE_IMGSZ=${GOPRO_EVIDENCE_IMGSZ}
GOPRO_DROPPED_ITEM_CONF=${GOPRO_DROPPED_ITEM_CONF}
GOPRO_EVIDENCE_CAPTURE_MODE=${GOPRO_EVIDENCE_CAPTURE_MODE}
GOPRO_EVIDENCE_RUNTIME_SCOPE=${GOPRO_EVIDENCE_RUNTIME_SCOPE}
VISION_MAP_ROI_ENABLED=${VISION_MAP_ROI_ENABLED:-}
VISION_ZONE_ROI_ENABLED=${VISION_ZONE_ROI_ENABLED:-}
VISION_ZONE_ROI_CONFIG_PATH=${VISION_ZONE_ROI_CONFIG_PATH:-}
PICAM_PUBLISH_WEBRTC=${PICAM_PUBLISH_WEBRTC}
PICAM_WEBRTC_TARGET_FPS=${PICAM_WEBRTC_TARGET_FPS}
PICAM_WEBRTC_AI_FPS=${PICAM_WEBRTC_AI_FPS}
PICAM_WEBRTC_METRICS_DIR=${PICAM_WEBRTC_METRICS_DIR}
SF_VISION_TMUX_REQUIRED_CONTEXT=${SF_VISION_TMUX_REQUIRED_CONTEXT}
SF_VISION_GOPRO_ADAPTER_AFTER_WEBRTC_SIDECAR=${SF_VISION_GOPRO_ADAPTER_AFTER_WEBRTC_SIDECAR}
SF_VISION_GOPRO_MEDIAMTX_READY_PATH=${SF_VISION_GOPRO_MEDIAMTX_READY_PATH}
SF_VISION_GOPRO_REQUIRED=${SF_VISION_GOPRO_REQUIRED}
SUMMARY
}

record_warning() {
  local message="$1"
  OPTIONAL_WARNINGS+=("${message}")
  printf '%s %s\n' "$(date -Is)" "${message}" >> "${WARNINGS_FILE}"
  echo "${message}" >&2
}

record_process() {
  local name="$1" pid="$2" log="$3"
  printf '%s\t%s\t%s\n' "${name}" "${pid}" "${log}" >> "${PID_FILE}"
}

start_logged() {
  local name="$1"
  shift
  local log="${LOG_DIR}/${name}.log"
  {
    printf '[sf-vision] start %s at %s\n' "${name}" "$(date -Is)"
    printf '[sf-vision] command:'
    printf ' %q' "$@"
    printf '\n--- output ---\n'
  } > "${log}"
  (cd "${ROOT_DIR}" && exec "$@" >> "${log}" 2>&1) &
  local pid=$!
  PIDS+=("${pid}")
  REQUIRED_PIDS+=("${pid}")
  NAMES+=("${name}")
  LOGS+=("${log}")
  LAST_STARTED_PID="${pid}"
  LAST_STARTED_LOG="${log}"
  LAST_STARTED_NAME="${name}"
  record_process "${name}" "${pid}" "${log}"
  echo "[sf-vision] ${name} pid=${pid} log=${log}"
}

start_optional_logged() {
  local name="$1"
  shift
  local log="${LOG_DIR}/${name}.log"
  {
    printf '[sf-vision] start optional %s at %s\n' "${name}" "$(date -Is)"
    printf '[sf-vision] command:'
    printf ' %q' "$@"
    printf '\n--- output ---\n'
  } > "${log}"
  (cd "${ROOT_DIR}" && exec "$@" >> "${log}" 2>&1) &
  local pid=$!
  PIDS+=("${pid}")
  NAMES+=("${name}")
  LOGS+=("${log}")
  LAST_STARTED_PID="${pid}"
  LAST_STARTED_LOG="${log}"
  LAST_STARTED_NAME="${name}"
  record_process "${name}" "${pid}" "${log}"
  echo "[sf-vision] optional ${name} pid=${pid} log=${log}"
}

optional_child_alive_after_grace() {
  local label="$1" pid="$2" log="$3" hint="$4"
  local grace="${SF_VISION_OPTIONAL_CHILD_GRACE_SEC:-1}"
  sleep "${grace}"
  if alive_pid "${pid}"; then
    return 0
  fi
  local status=0
  wait "${pid}" 2> /dev/null || status=$?
  record_warning "WARN: optional ${label} exited early (status=${status}); ${hint}; keeping core AI Server/PiCam runtime alive. log=${log}"
  return 1
}

print_optional_warnings() {
  if [ "${#OPTIONAL_WARNINGS[@]}" -eq 0 ]; then
    return 0
  fi
  echo "[sf-vision] optional hardware/media warnings:"
  local warning
  for warning in "${OPTIONAL_WARNINGS[@]}"; do
    echo "[sf-vision]   ${warning}"
  done
  echo "[sf-vision] warnings recorded at ${WARNINGS_FILE}"
}

wait_for_url() {
  local label="$1" url="$2" timeout_s="${3:-45}"
  local start now
  start="$(date +%s)"
  echo "[sf-vision] waiting for ${label}: ${url}"
  while true; do
    if command -v curl > /dev/null 2>&1 && curl -fsS --max-time 1 "${url}" > /dev/null 2>&1; then
      echo "[sf-vision] ${label}: ok"
      return 0
    fi
    now="$(date +%s)"
    if [ $((now - start)) -ge "${timeout_s}" ]; then
      echo "ERROR: timeout waiting for ${label}: ${url}" >&2
      return 1
    fi
    sleep 1
  done
}

current_tmux_context() {
  if [ -z "${TMUX:-}" ] || ! command -v tmux > /dev/null 2>&1; then
    return 1
  fi
  if [ -n "${TMUX_PANE:-}" ]; then
    tmux display-message -p -t "${TMUX_PANE}" '#S:#I:#W' 2> /dev/null && return 0
  fi
  tmux display-message -p '#S:#I:#W' 2> /dev/null
}

require_live_tmux_context() {
  if ! is_truthy "${SF_VISION_TMUX_GUARD_ENABLED:-true}"; then
    return 0
  fi
  local current
  current="$(current_tmux_context || true)"
  if [ "${current}" = "${SF_VISION_TMUX_REQUIRED_CONTEXT}" ]; then
    return 0
  fi
  cat >&2 << ERROR
ERROR: live Vision processes must run in tmux ${SF_VISION_TMUX_REQUIRED_CONTEXT}.
Current context: ${current:-<not inside tmux>}
Open/switch to that tmux window before running: ./scripts/vision/sf_vision.sh up ${PROFILE:-${DEFAULT_PROFILE}}
ERROR
  return 1
}

run_enabled_preflights() {
  bash -n "${BASH_SOURCE[0]}"
  bash -n "${ROOT_DIR}/scripts/vision/run_d1_vision_multi_source_gateway_bundle.sh"
  bash -n "${ROOT_DIR}/scripts/vision/run_webrtc_sidecar_mediamtx.sh"
  if is_truthy "${SF_VISION_BUNDLE_ENABLED}"; then
    "${ROOT_DIR}/scripts/vision/run_d1_vision_multi_source_gateway_bundle.sh" --check
  fi
  if is_truthy "${SF_VISION_GOPRO_ENABLED}"; then
    local py="${AI_SERVER_VENV_DIR}/bin/python"
    "${py}" "${ROOT_DIR}/scripts/vision/run_gopro_smart_roi_adapter.py" --check
    "${py}" "${ROOT_DIR}/scripts/vision/start_gopro_webcam_stream.py" --help > /dev/null
  fi
  if is_truthy "${SF_VISION_WEBRTC_SIDECAR_ENABLED}"; then
    "${ROOT_DIR}/scripts/vision/run_webrtc_sidecar_mediamtx.sh" --check
  fi
}

start_mdns() {
  if is_truthy "${SF_VISION_MDNS_ENABLED}"; then
    start_logged mdns-alias python3 scripts/vision/publish_vision_mdns_alias.py
  fi
}

start_bundle() {
  if is_truthy "${SF_VISION_BUNDLE_ENABLED}"; then
    start_logged vision-bundle ./scripts/vision/run_d1_vision_multi_source_gateway_bundle.sh
    wait_for_url "AI Server" "${AI_SERVER_URL%/}/api/v1/health" "${AI_SERVER_START_TIMEOUT_SEC:-60}"
    wait_for_url "Vision Stream Gateway" "http://127.0.0.1:${VISION_STREAM_GATEWAY_PORT}/api/v1/vision/bridge/status" "${VISION_GATEWAY_START_TIMEOUT_SEC:-45}"
  fi
}

start_gopro() {
  if ! is_truthy "${SF_VISION_GOPRO_ENABLED}"; then
    return 0
  fi
  start_gopro_stream
  if is_truthy "${GOPRO_STREAM_AVAILABLE:-false}"; then
    start_gopro_adapter
  else
    record_warning "WARN: optional GoPro stream is unavailable; skipping GoPro adapter and global_cam_01 WebRTC publisher"
  fi
}

start_gopro_stream() {
  if ! is_truthy "${SF_VISION_GOPRO_ENABLED}"; then
    return 0
  fi
  local py="${AI_SERVER_VENV_DIR}/bin/python"
  if [ ! -x "${py}" ]; then
    echo "ERROR: AI Server python not found: ${py}" >&2
    return 1
  fi

  local stream_cmd=("${py}" scripts/vision/start_gopro_webcam_stream.py --protocol "${GOPRO_PROTOCOL}" --resolution "${GOPRO_RESOLUTION}" --fov "${GOPRO_FOV}" --port "${GOPRO_PORT}")
  if is_truthy "${GOPRO_TEST_READ}"; then
    stream_cmd+=(--test-read)
  fi
  GOPRO_STREAM_AVAILABLE=false
  if is_truthy "${SF_VISION_GOPRO_REQUIRED}"; then
    start_logged gopro-stream "${stream_cmd[@]}"
    GOPRO_STREAM_AVAILABLE=true
  else
    start_optional_logged gopro-stream "${stream_cmd[@]}"
    if ! optional_child_alive_after_grace \
      "GoPro stream" \
      "${LAST_STARTED_PID}" \
      "${LAST_STARTED_LOG}" \
      "GoPro/global_cam_01 is unavailable"; then
      return 0
    fi
    GOPRO_STREAM_AVAILABLE=true
  fi

  echo "[sf-vision] warming up GoPro stream for ${GOPRO_STREAM_WARMUP_SEC}s"
  sleep "${GOPRO_STREAM_WARMUP_SEC}"
  if ! alive_pid "${LAST_STARTED_PID}"; then
    wait "${LAST_STARTED_PID}" 2> /dev/null || true
    if is_truthy "${SF_VISION_GOPRO_REQUIRED}"; then
      echo "ERROR: required GoPro stream exited during warmup; see ${LAST_STARTED_LOG}" >&2
      return 1
    fi
    record_warning "WARN: optional GoPro stream exited during warmup; GoPro/global_cam_01 unavailable; keeping core AI Server/PiCam runtime alive. log=${LAST_STARTED_LOG}"
    GOPRO_STREAM_AVAILABLE=false
    return 0
  fi
}

start_gopro_adapter() {
  if ! is_truthy "${SF_VISION_GOPRO_ENABLED}"; then
    return 0
  fi
  local py="${AI_SERVER_VENV_DIR}/bin/python"
  if [ ! -x "${py}" ]; then
    echo "ERROR: AI Server python not found: ${py}" >&2
    return 1
  fi
  local adapter_cmd=(
    "${py}" scripts/vision/run_gopro_smart_roi_adapter.py
    --input "${GOPRO_ADAPTER_INPUT}"
    --source "${GOPRO_SOURCE}"
    --roi-view "${GOPRO_ROI_VIEW}"
    --ai-server-url "${AI_SERVER_URL}"
    --target-fps "${GOPRO_AI_MONITOR_FPS}"
    --stream-target-fps "${GOPRO_STREAM_TARGET_FPS}"
    --model-input-size "${GOPRO_AI_MONITOR_IMGSZ}"
    --operation "${GOPRO_OPERATION}"
  )
  if is_truthy "${GOPRO_BUFFERLESS}"; then
    adapter_cmd+=(--bufferless)
  else
    adapter_cmd+=(--no-bufferless)
  fi
  if is_truthy "${GOPRO_PUBLISH_WEBRTC}"; then
    adapter_cmd+=(--publish-webrtc)
  else
    adapter_cmd+=(--no-publish-webrtc)
  fi
  if is_truthy "${GOPRO_PUBLISH_ROI_WEBRTC}"; then
    adapter_cmd+=(--publish-roi-webrtc)
  else
    adapter_cmd+=(--no-publish-roi-webrtc)
  fi
  adapter_cmd+=(--webrtc-metrics-dir "${GOPRO_WEBRTC_METRICS_DIR}")
  adapter_cmd+=(--webrtc-stale-overlay-after-ms "${GOPRO_WEBRTC_STALE_OVERLAY_AFTER_MS}")
  if is_truthy "${SF_VISION_GOPRO_REQUIRED}"; then
    start_logged gopro-adapter "${adapter_cmd[@]}"
  else
    start_optional_logged gopro-adapter "${adapter_cmd[@]}"
    optional_child_alive_after_grace \
      "GoPro adapter" \
      "${LAST_STARTED_PID}" \
      "${LAST_STARTED_LOG}" \
      "global_cam_01 AI/WebRTC publisher is unavailable" || true
  fi
}

start_picam_compositor() {
  local source_id="$1"
  if ! is_truthy "${PICAM_PUBLISH_WEBRTC}"; then
    return 0
  fi
  [ -n "${source_id}" ] || return 0
  local py="${AI_SERVER_VENV_DIR}/bin/python"
  if [ ! -x "${py}" ]; then
    echo "ERROR: AI Server python not found for PiCam compositor: ${py}" >&2
    return 1
  fi
  local cmd=(
    "${py}" scripts/vision/run_latest_frame_compositor.py
    --source "${source_id}"
    --view full
    --ai-server-url "${AI_SERVER_URL}"
    --target-fps "${PICAM_WEBRTC_TARGET_FPS}"
    --ai-fps "${PICAM_WEBRTC_AI_FPS}"
    --metrics-dir "${PICAM_WEBRTC_METRICS_DIR}"
    --mediamtx-rtsp-port "${MEDIAMTX_RTSP_PORT}"
  )
  start_logged "picam-compositor-${source_id}" "${cmd[@]}"
}

start_picam_compositors() {
  if ! is_truthy "${SF_VISION_WEBRTC_SIDECAR_ENABLED}"; then
    return 0
  fi
  if is_truthy "${VISION_SOURCE_1_ENABLED:-true}"; then
    start_picam_compositor "${VISION_SOURCE_1_ID:-tb3_1_picam}"
  fi
  if is_truthy "${VISION_SOURCE_2_ENABLED:-true}"; then
    start_picam_compositor "${VISION_SOURCE_2_ID:-tb3_2_picam}"
  fi
}

start_webrtc_sidecar() {
  if ! is_truthy "${SF_VISION_WEBRTC_SIDECAR_ENABLED}"; then
    return 0
  fi
  "${ROOT_DIR}/scripts/vision/run_webrtc_sidecar_mediamtx.sh" --check
  start_logged webrtc-sidecar ./scripts/vision/run_webrtc_sidecar_mediamtx.sh
}

mediamtx_path_ready() {
  local path="$1"
  if ! command -v curl > /dev/null 2>&1; then
    return 1
  fi
  local body
  body="$(curl -fsS --max-time 1 "http://127.0.0.1:${MEDIAMTX_API_PORT}/v3/paths/list" 2> /dev/null || true)"
  [ -n "${body}" ] || return 1
  python3 - "${path}" "${body}" << 'PY'
import json
import sys

path = sys.argv[1]
try:
    payload = json.loads(sys.argv[2])
except Exception:
    raise SystemExit(1)
for item in payload.get("items", []):
    if not isinstance(item, dict):
        continue
    name = item.get("name") or item.get("path")
    if name != path:
        continue
    if any(item.get(key) is True for key in ("ready", "available", "online", "sourceReady")):
        raise SystemExit(0)
raise SystemExit(1)
PY
}

rtsp_stream_readable() {
  local url="$1"
  if ! command -v "${FFPROBE_BIN}" > /dev/null 2>&1; then
    return 1
  fi
  local body
  local ffprobe_cmd=(
    "${FFPROBE_BIN}"
    -v error
    -rtsp_transport tcp
    -timeout "${FFPROBE_TIMEOUT_US}"
    -rw_timeout "${FFPROBE_TIMEOUT_US}"
    -select_streams v:0
    -show_entries stream=codec_name,width,height,r_frame_rate,avg_frame_rate
    -of json
    "${url}"
  )
  if command -v timeout > /dev/null 2>&1; then
    body="$(timeout "${FFPROBE_TIMEOUT_SEC}" "${ffprobe_cmd[@]}" 2> /dev/null || true)"
  else
    body="$("${ffprobe_cmd[@]}" 2> /dev/null || true)"
  fi
  [ -n "${body}" ] || return 1
  python3 - "${body}" << 'PY'
import json
import sys

try:
    payload = json.loads(sys.argv[1])
except Exception:
    raise SystemExit(1)
streams = payload.get("streams") or []
raise SystemExit(0 if streams else 1)
PY
}

wait_for_rtsp_stream() {
  local label="$1" url="$2" timeout_s="${3:-30}"
  local start now
  start="$(date +%s)"
  echo "[sf-vision] waiting for ${label} RTSP stream: ${url}"
  while true; do
    if rtsp_stream_readable "${url}"; then
      echo "[sf-vision] ${label} RTSP stream: ok"
      return 0
    fi
    now="$(date +%s)"
    if [ $((now - start)) -ge "${timeout_s}" ]; then
      echo "ERROR: timeout waiting for ${label} RTSP stream: ${url}" >&2
      return 1
    fi
    sleep 0.5
  done
}

wait_for_mediamtx_path() {
  local path="$1" timeout_s="${2:-30}"
  local start now
  start="$(date +%s)"
  echo "[sf-vision] waiting for MediaMTX path ${path} via api :${MEDIAMTX_API_PORT}"
  while true; do
    if mediamtx_path_ready "${path}"; then
      echo "[sf-vision] MediaMTX path ${path}: ok"
      return 0
    fi
    now="$(date +%s)"
    if [ $((now - start)) -ge "${timeout_s}" ]; then
      echo "ERROR: timeout waiting for MediaMTX path ${path}" >&2
      return 1
    fi
    sleep 0.5
  done
}

start_gopro_mediamtx_first() {
  if ! is_truthy "${SF_VISION_GOPRO_ENABLED}"; then
    start_webrtc_sidecar
    start_picam_compositors
    return 0
  fi
  start_gopro_stream
  start_webrtc_sidecar
  start_picam_compositors
  if ! is_truthy "${GOPRO_STREAM_AVAILABLE:-false}"; then
    record_warning "WARN: optional GoPro/global_cam_01 is unavailable; MediaMTX/PiCam/WebRTC fallback processes remain alive"
    return 0
  fi
  if is_truthy "${SF_VISION_WEBRTC_SIDECAR_ENABLED}"; then
    if [ -n "${SF_VISION_GOPRO_MEDIAMTX_READY_PATH}" ]; then
      if ! wait_for_mediamtx_path "${SF_VISION_GOPRO_MEDIAMTX_READY_PATH}" "${SF_VISION_GOPRO_MEDIAMTX_READY_TIMEOUT_SEC}"; then
        echo "WARN: GoPro MediaMTX raw path '${SF_VISION_GOPRO_MEDIAMTX_READY_PATH}' did not become ready; keeping AI Server/gateway/sidecar alive and skipping GoPro adapter so MJPEG/Pi fallback remains available" >&2
        return 0
      fi
    else
      echo "[sf-vision] MediaMTX receiver mode: starting GoPro compositor publisher before path readiness wait"
    fi
    case "${GOPRO_ADAPTER_INPUT}" in
      rtsp://*)
        if ! wait_for_rtsp_stream "GoPro adapter input" "${GOPRO_ADAPTER_INPUT}" "${SF_VISION_GOPRO_MEDIAMTX_READY_TIMEOUT_SEC}"; then
          echo "WARN: GoPro adapter RTSP input is not readable; keeping AI Server/gateway/sidecar alive and skipping GoPro adapter so MJPEG/Pi fallback remains available" >&2
          return 0
        fi
        ;;
    esac
  fi
  start_gopro_adapter
}

cleanup() {
  local status=$?
  trap - INT TERM EXIT
  if [ "${#PIDS[@]}" -gt 0 ]; then
    echo "[sf-vision] stopping ${#PIDS[@]} child process(es)"
    local i
    for ((i = ${#PIDS[@]} - 1; i >= 0; i--)); do
      kill -INT "${PIDS[$i]}" 2> /dev/null || true
    done
    sleep 2
    for ((i = ${#PIDS[@]} - 1; i >= 0; i--)); do
      kill -TERM "${PIDS[$i]}" 2> /dev/null || true
    done
    wait 2> /dev/null || true
  fi
  rm -f "${SUPERVISOR_PID_FILE}"
  exit "${status}"
}

run_up() {
  load_profile "${1:-${DEFAULT_PROFILE}}"
  require_live_tmux_context
  print_config
  run_enabled_preflights
  ensure_dirs
  ensure_not_running
  echo "$$" > "${SUPERVISOR_PID_FILE}"
  : > "${PID_FILE}"
  record_summary
  trap cleanup INT TERM EXIT
  start_mdns
  start_bundle
  if is_truthy "${SF_VISION_GOPRO_ADAPTER_AFTER_WEBRTC_SIDECAR}"; then
    start_gopro_mediamtx_first
  else
    start_gopro
    start_webrtc_sidecar
    start_picam_compositors
  fi
  print_optional_warnings
  echo "[sf-vision] running. Ctrl-C or ./scripts/vision/sf_vision.sh down stops all child processes."
  set +e
  if [ "${#REQUIRED_PIDS[@]}" -gt 0 ]; then
    wait -n "${REQUIRED_PIDS[@]}"
  else
    wait -n "${PIDS[@]}"
  fi
  local child_status=$?
  set -e
  echo "[sf-vision] a child process exited (status=${child_status}); shutting down runtime"
  exit "${child_status}"
}

run_check() {
  load_profile "${1:-${DEFAULT_PROFILE}}"
  print_config
  run_enabled_preflights
  echo "[sf-vision] check ok: ${PROFILE}"
}

status() {
  echo "SmartFactory Vision runtime status"
  if [ -f "${SUMMARY_FILE}" ]; then
    sed 's/^/  /' "${SUMMARY_FILE}"
  else
    echo "  no summary file: ${SUMMARY_FILE}"
  fi
  if [ -f "${SUPERVISOR_PID_FILE}" ]; then
    local spid
    spid="$(cat "${SUPERVISOR_PID_FILE}" 2> /dev/null || true)"
    if alive_pid "${spid}"; then
      echo "  supervisor: alive pid=${spid}"
    else
      echo "  supervisor: stale pid=${spid}"
    fi
  else
    echo "  supervisor: not recorded"
  fi
  if [ -f "${PID_FILE}" ]; then
    while IFS=$'\t' read -r name pid log; do
      [ -n "${name:-}" ] || continue
      if alive_pid "${pid}"; then
        printf '  %-18s alive pid=%s log=%s\n' "${name}" "${pid}" "${log}"
      else
        printf '  %-18s stopped pid=%s log=%s\n' "${name}" "${pid}" "${log}"
      fi
    done < "${PID_FILE}"
  else
    echo "  process table: not recorded"
  fi
  if [ -s "${WARNINGS_FILE}" ]; then
    echo "  optional warnings:"
    sed 's/^/    /' "${WARNINGS_FILE}"
  fi
}

smoke() {
  local api="http://127.0.0.1:${AI_SERVER_PORT:-8100}"
  local stream="http://127.0.0.1:${VISION_STREAM_GATEWAY_PORT:-8090}"
  echo "[sf-vision] smoke AI health"
  curl -fsS --max-time 2 "${api}/api/v1/health" > /dev/null
  echo "[sf-vision] smoke gateway status"
  curl -fsS --max-time 2 "${stream}/api/v1/vision/bridge/status" > /dev/null
  echo "[sf-vision] smoke stream discovery: global_cam_01"
  curl -fsS --max-time 2 "${api}/api/v1/vision/streams?source=global_cam_01" > /dev/null
  echo "[sf-vision] smoke WebRTC candidate/fallback offer"
  curl -fsS --max-time 2 -X POST "${api}/api/v1/vision/streams/global_cam_01/webrtc/offer?view=full" -H 'Content-Type: application/json' -d '{}' > /dev/null
  if [ -f "${SUMMARY_FILE}" ] && grep -q '^SF_VISION_WEBRTC_SIDECAR_ENABLED=true$' "${SUMMARY_FILE}"; then
    echo "[sf-vision] smoke WebRTC sidecar status"
    "${ROOT_DIR}/scripts/vision/run_webrtc_sidecar_mediamtx.sh" --status > /dev/null
  fi
  echo "[sf-vision] smoke ok"
}

logs() {
  local name="${1:-}"
  if [ -n "${name}" ]; then
    if [ ! -f "${LOG_DIR}/${name}.log" ]; then
      echo "ERROR: log not found: ${LOG_DIR}/${name}.log" >&2
      return 1
    fi
    tail -n 80 -f "${LOG_DIR}/${name}.log"
  else
    local logs=()
    while IFS= read -r log; do
      logs+=("${log}")
    done < <(find "${LOG_DIR}" -maxdepth 1 -type f -name '*.log' 2> /dev/null | sort)
    if [ "${#logs[@]}" -eq 0 ]; then
      echo "No logs found under ${LOG_DIR}"
      return 0
    fi
    printf '%s\n' "${logs[@]}"
    tail -n 40 -f "${logs[@]}"
  fi
}

down() {
  local stopped=0
  if [ -f "${SUPERVISOR_PID_FILE}" ]; then
    local spid
    spid="$(cat "${SUPERVISOR_PID_FILE}" 2> /dev/null || true)"
    if alive_pid "${spid}"; then
      echo "[sf-vision] stopping supervisor pid=${spid}"
      kill -INT "${spid}" 2> /dev/null || true
      stopped=1
      sleep 3
    fi
  fi
  if [ -f "${PID_FILE}" ]; then
    while IFS=$'\t' read -r name pid log; do
      [ -n "${pid:-}" ] || continue
      if alive_pid "${pid}"; then
        echo "[sf-vision] stopping child ${name} pid=${pid}"
        kill -TERM "${pid}" 2> /dev/null || true
        stopped=1
      fi
    done < "${PID_FILE}"
  fi
  if [ "${stopped}" -eq 0 ]; then
    echo "[sf-vision] no live recorded runtime found"
  fi
  stop_stale_webrtc_sidecar_processes
}

cmd="${1:-}"
case "${cmd}" in
  profiles) list_profiles ;;
  print-config)
    load_profile "${2:-${DEFAULT_PROFILE}}"
    print_config
    ;;
  check) run_check "${2:-${DEFAULT_PROFILE}}" ;;
  up) run_up "${2:-${DEFAULT_PROFILE}}" ;;
  status) status ;;
  smoke) smoke ;;
  logs) logs "${2:-}" ;;
  down) down ;;
  --help | -h | help | "") usage ;;
  *)
    echo "ERROR: unknown command: ${cmd}" >&2
    usage >&2
    exit 2
    ;;
esac
