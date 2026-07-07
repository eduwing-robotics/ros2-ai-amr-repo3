#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/../.." && pwd)"

DEFAULT_PROFILE="lab-gopro-tb3-ffmpeg-first"
DEFAULT_AI_SERVER_URL="http://127.0.0.1:8100"
DEFAULT_PUBLIC_HOST="smartfactory-vision.local"
DEFAULT_AI_SERVER_PORT="8100"
DEFAULT_WEBRTC_PORT="8889"
DEFAULT_STREAM_PORT="8090"
DEFAULT_MAIN_SERVER_URL="http://smartfactory-main.local:8088"

PROFILE="${SF_LAB_PROFILE:-${PROFILE:-${DEFAULT_PROFILE}}}"
AI_SERVER_URL="${AI_SERVER_URL:-${DEFAULT_AI_SERVER_URL}}"
VISION_PUBLIC_HOST="${VISION_PUBLIC_HOST:-${DEFAULT_PUBLIC_HOST}}"
AI_SERVER_PORT="${AI_SERVER_PORT:-${DEFAULT_AI_SERVER_PORT}}"
VISION_API_BASE_URL="${VISION_API_BASE_URL:-http://${VISION_PUBLIC_HOST}:${AI_SERVER_PORT}}"
MEDIAMTX_WEBRTC_PORT="${MEDIAMTX_WEBRTC_PORT:-${DEFAULT_WEBRTC_PORT}}"
VISION_STREAM_GATEWAY_PORT="${VISION_STREAM_GATEWAY_PORT:-${DEFAULT_STREAM_PORT}}"
MAIN_SERVER_URL="${MAIN_SERVER_URL:-${DEFAULT_MAIN_SERVER_URL}}"
CURL_TIMEOUT="${SF_LAB_CURL_TIMEOUT:-5}"

usage() {
  cat << USAGE
Usage: $(basename "$0") <command> [args]

SmartFactory lab-friendly Vision entrypoint. It hides profile/env details for the
current GoPro global camera + TurtleBot Pi camera lab setup.

All-in-one live runtime:
  $(basename "$0") low-load            # low-load WebRTC: GoPro full + tb3_1/tb3_2, lift_roi WebRTC off
  $(basename "$0") all                 # full WebRTC: GoPro full+lift_roi + tb3_1/tb3_2 + MJPEG fallback
  $(basename "$0") stream              # same as all; operator-friendly alias
  $(basename "$0") down                # stop the bundled runtime

Separated checks / URLs:
  $(basename "$0") status              # bundle status + safe direct-media probe
  $(basename "$0") urls [profile]      # Main-facing WebRTC/MJPEG/API URLs
  $(basename "$0") check [profile]     # non-live dependency/profile preflight
  $(basename "$0") probe               # read-only direct-media/WebRTC path probe

API JSON helpers (call a running AI Server and print JSON for Main/connector checks):
  $(basename "$0") api health
  $(basename "$0") api streams [source]
  $(basename "$0") api worker-status [source]
  $(basename "$0") api worker-tick [source] [force]
  $(basename "$0") api webrtc-offer [source] [view]
  $(basename "$0") api evaluate-no-frame [source] [view] [operation]
  $(basename "$0") api evaluate-quality [source] [view]
  $(basename "$0") api runtime-status
  $(basename "$0") api restart-low-load [--dry-run] [--git-pull] KEY=VALUE...

Defaults:
  profile=${PROFILE}
  low_load_profile=lab-gopro-tb3-low-load
  ai_server=${AI_SERVER_URL}
  public_host=${VISION_PUBLIC_HOST}
  main_facing_api=${VISION_API_BASE_URL}

Safety boundary: this wrapper does not launch robot motion, Nav2, teleop,
/cmd_vel, ROS parameter mutation, or whole-graph rosbridge. Robot Pi camera
bringup remains manual on the TurtleBot.
USAGE
}

profile_name_for_arg() {
  local value="${1:-${PROFILE}}"
  case "${value}" in
    low-load | lowload | lite) printf '%s\n' "lab-gopro-tb3-low-load" ;;
    full | all | stream | ffmpeg-first) printf '%s\n' "lab-gopro-tb3-ffmpeg-first" ;;
    default | "") printf '%s\n' "${PROFILE}" ;;
    *) printf '%s\n' "${value}" ;;
  esac
}

load_profile_for_read() {
  local selected="$1"
  local profile_file="${ROOT_DIR}/config/vision/profiles/${selected}.env"
  if [ ! -f "${profile_file}" ]; then
    echo "ERROR: unknown profile '${selected}'" >&2
    echo "Available profiles:" >&2
    find "${ROOT_DIR}/config/vision/profiles" -maxdepth 1 -type f -name '*.env' \
      -printf '%f\n' | sed 's/\.env$//' | sort >&2
    return 2
  fi
  set -a
  # shellcheck disable=SC1090
  source "${profile_file}"
  set +a
  PROFILE="${selected}"
}

need_cmd() {
  local name="$1"
  if ! command -v "${name}" > /dev/null 2>&1; then
    echo "ERROR: required command not found: ${name}" >&2
    return 127
  fi
}

curl_json_get() {
  need_cmd curl
  curl -fsS --max-time "${CURL_TIMEOUT}" "$1"
}

curl_json_post() {
  need_cmd curl
  local url="$1"
  local payload="$2"
  curl -fsS --max-time "${CURL_TIMEOUT}" \
    -H 'Content-Type: application/json' \
    -d "${payload}" \
    "${url}"
}

curl_json_get_operator() {
  need_cmd curl
  local url="$1"
  local curl_args=(-fsS --max-time "${CURL_TIMEOUT}")
  if [ -n "${SF_RUNTIME_CONTROL_TOKEN:-}" ]; then
    curl_args+=(-H "X-SF-Operator-Token: ${SF_RUNTIME_CONTROL_TOKEN}")
  fi
  curl "${curl_args[@]}" "${url}"
}

curl_json_post_operator() {
  need_cmd curl
  local url="$1"
  local payload="$2"
  local curl_args=(
    -fsS
    --max-time "${CURL_TIMEOUT}"
    -H 'Content-Type: application/json'
  )
  if [ -n "${SF_RUNTIME_CONTROL_TOKEN:-}" ]; then
    curl_args+=(-H "X-SF-Operator-Token: ${SF_RUNTIME_CONTROL_TOKEN}")
  fi
  curl "${curl_args[@]}" -d "${payload}" "${url}"
}

python_json() {
  python3 - "$@"
}

url_quote() {
  need_cmd python3
  python3 - "$1" << 'PY'
from urllib.parse import quote
import sys
print(quote(sys.argv[1], safe=""))
PY
}

upper_value() {
  printf '%s' "$1" | tr '[:lower:]' '[:upper:]'
}

normalize_plan_operation() {
  local operation
  operation="$(upper_value "${1:-PICKUP}")"
  case "${operation}" in
    PICKUP | DROPOFF | MONITOR) printf '%s\n' "${operation}" ;;
    *)
      echo "ERROR: operation must be PICKUP, DROPOFF, or MONITOR: ${1:-}" >&2
      return 2
      ;;
  esac
}

normalize_transition_operation() {
  local operation
  operation="$(upper_value "${1:-PICKUP}")"
  case "${operation}" in
    PICKUP | DROPOFF) printf '%s\n' "${operation}" ;;
    *)
      echo "ERROR: evaluate-no-frame operation must be PICKUP or DROPOFF: ${1:-}" >&2
      return 2
      ;;
  esac
}

cmd_all() {
  local selected
  selected="$(profile_name_for_arg "${1:-${PROFILE}}")"
  exec "${SCRIPT_DIR}/sf_vision.sh" up "${selected}"
}

cmd_low_load() {
  exec "${SCRIPT_DIR}/sf_vision.sh" up "lab-gopro-tb3-low-load"
}

cmd_down() {
  exec "${SCRIPT_DIR}/sf_vision.sh" down
}

cmd_check() {
  local selected
  selected="$(profile_name_for_arg "${1:-${PROFILE}}")"
  "${SCRIPT_DIR}/sf_vision.sh" check "${selected}"
}

cmd_status() {
  local status_code=0
  "${SCRIPT_DIR}/sf_vision.sh" status || status_code=$?
  echo
  echo "[sf-lab] safe direct-media/WebRTC probe"
  if command -v python3 > /dev/null 2>&1; then
    python3 "${SCRIPT_DIR}/probe_direct_media_candidates.py" || true
  else
    echo "python3 not found; skipping probe" >&2
  fi
  return "${status_code}"
}

cmd_probe() {
  need_cmd python3
  python3 "${SCRIPT_DIR}/probe_direct_media_candidates.py" "$@"
}

stream_spec_is_active() {
  local needle="$1"
  local specs="${2:-}"
  case ",${specs}," in
    *",${needle},"*) return 0 ;;
    *) return 1 ;;
  esac
}

stream_path_id() {
  printf '%s_%s\n' "$1" "$2" | tr '/-' '__'
}

cmd_urls() {
  local selected active_streams api_base stream_port public_host webrtc_port
  selected="$(profile_name_for_arg "${1:-${PROFILE}}")"
  load_profile_for_read "${selected}"
  public_host="${VISION_PUBLIC_HOST:-${DEFAULT_PUBLIC_HOST}}"
  api_base="${VISION_API_BASE_URL:-http://${public_host}:${AI_SERVER_PORT:-${DEFAULT_AI_SERVER_PORT}}}"
  webrtc_port="${MEDIAMTX_WEBRTC_PORT:-${DEFAULT_WEBRTC_PORT}}"
  stream_port="${VISION_STREAM_GATEWAY_PORT:-${DEFAULT_STREAM_PORT}}"
  active_streams="${VISION_WEBRTC_COMPOSITOR_PUBLISHER_STREAMS:-${WEBRTC_SIDECAR_COMPOSITOR_PUBLISHER_STREAMS:-${VISION_WEBRTC_SIDECAR_STREAMS:-${WEBRTC_SIDECAR_STREAMS:-}}}}"
  local disabled=()
  local print_active_stream
  print_active_stream() {
    local source="$1" view="$2" label="$3" spec path_id
    spec="${source}/${view}"
    path_id="$(stream_path_id "${source}" "${view}")"
    if stream_spec_is_active "${spec}" "${active_streams}"; then
      printf '  http://%s:%s/%s/  # %s\n' "${public_host}" "${webrtc_port}" "${path_id}" "${label}"
      printf '  http://%s:%s/%s/whep\n' "${public_host}" "${webrtc_port}" "${path_id}"
    else
      disabled+=("${spec}")
    fi
  }

  cat << URLS
SmartFactory lab Vision URLs

Selected profile:
  ${selected}

Main dashboard:
  ${MAIN_SERVER_URL%/}/operate/control

AI Server API/discovery (Main-facing):
  ${api_base%/}/api/v1/health
  ${api_base%/}/api/v1/vision/streams
  ${api_base%/}/api/v1/evidence/evaluate

Local API helper target:
  ${AI_SERVER_URL%/}

Active WebRTC browser/WHEP URLs for this profile:
URLS
  print_active_stream "global_cam_01" "full" "burned-overlay GoPro full video"
  print_active_stream "global_cam_01" "lift_roi" "burned-overlay GoPro lift ROI crop"
  print_active_stream "tb3_1_picam" "full" "burned-overlay PiCam full"
  print_active_stream "tb3_2_picam" "full" "burned-overlay PiCam full"
  if [ "${#disabled[@]}" -gt 0 ]; then
    printf '\nDisabled WebRTC streams in this profile (use full profile if needed):\n'
    local item
    for item in "${disabled[@]}"; do
      printf '  %s\n' "${item}"
    done
  fi
  cat << URLS

MJPEG fallback/diagnostic URLs:
  http://${public_host}:${stream_port}/api/v1/vision/overlay/stream?source=global_cam_01&view=full&max_fps=30
  http://${public_host}:${stream_port}/api/v1/vision/overlay/stream?source=global_cam_01&view=lift_roi&max_fps=30
  http://${public_host}:${stream_port}/api/v1/vision/overlay/stream?source=tb3_1_picam&view=full&max_fps=30
  http://${public_host}:${stream_port}/api/v1/vision/overlay/stream?source=tb3_2_picam&view=full&max_fps=30

Latest-frame MJPEG diagnostic URLs (no Main streaming overlay contract):
  http://${public_host}:${stream_port}/api/v1/vision/frame/stream?source=global_cam_01&view=full&max_fps=30
  http://${public_host}:${stream_port}/api/v1/vision/frame/stream?source=tb3_1_picam&view=full&max_fps=30
  http://${public_host}:${stream_port}/api/v1/vision/frame/stream?source=tb3_2_picam&view=full&max_fps=30

AI overlay metadata diagnostic URLs (not required for Main streaming overlay):
  ${api_base%/}/api/v1/vision/overlay/metadata?source=global_cam_01&view=full&limit=20
  ${api_base%/}/api/v1/vision/overlay/metadata?source=tb3_1_picam&view=full&limit=20

Operator commands:
  ./scripts/vision/sf_lab.sh low-load
  ./scripts/vision/sf_lab.sh all
  ./scripts/vision/sf_lab.sh status
  ./scripts/vision/sf_lab.sh urls ${selected}
  ./scripts/vision/sf_lab.sh api streams
  ./scripts/vision/sf_lab.sh api evaluate-no-frame
URLS
}

api_health() {
  curl_json_get "${AI_SERVER_URL%/}/api/v1/health"
}

api_streams() {
  local source="${1:-}"
  local url="${AI_SERVER_URL%/}/api/v1/vision/streams"
  if [ -n "${source}" ]; then
    url="${url}?source=$(url_quote "${source}")"
  fi
  curl_json_get "${url}"
}

api_worker_status() {
  local source="${1:-global_cam_01}"
  curl_json_get "${AI_SERVER_URL%/}/api/v1/vision/worker/status?source=$(url_quote "${source}")"
}

api_worker_tick() {
  local source="${1:-global_cam_01}"
  local force="${2:-false}"
  local payload
  payload="$(
    python_json "${source}" "${force}" << 'PY'
import json
import sys
source = sys.argv[1]
force = sys.argv[2].lower() in {"1", "true", "yes", "y", "on", "force"}
print(json.dumps({"source": source, "force": force}, separators=(",", ":")))
PY
  )"
  curl_json_post "${AI_SERVER_URL%/}/api/v1/vision/worker/tick" "${payload}"
}

api_webrtc_offer() {
  local source="${1:-global_cam_01}"
  local view="${2:-full}"
  curl_json_post "${AI_SERVER_URL%/}/api/v1/vision/streams/$(url_quote "${source}")/webrtc/offer?view=$(url_quote "${view}")" '{}'
}

api_evaluate_no_frame() {
  local source="${1:-global_cam_01}"
  local view="${2:-lift_roi}"
  local operation
  local expected
  operation="$(normalize_transition_operation "${3:-PICKUP}")"
  case "${operation}" in
    PICKUP) expected="ITEM_PICKED" ;;
    DROPOFF) expected="ITEM_PLACED" ;;
  esac
  local payload
  payload="$(
    python_json "${source}" "${view}" "${operation}" "${expected}" << 'PY'
import json
import sys
source, view, operation, expected = sys.argv[1:5]
print(json.dumps({
    "source": source,
    "view": view,
    "operation": operation,
    "expected_evidence_type": expected,
    "expected_count": 1,
    "task_ref": {"task_id": "OPERATOR-NO-FRAME-CHECK"},
}, separators=(",", ":")))
PY
  )"
  curl_json_post "${AI_SERVER_URL%/}/api/v1/evidence/evaluate" "${payload}"
}

api_evaluate_quality() {
  local source="${1:-global_cam_01}"
  local view="${2:-full}"
  local payload
  payload="$(
    python_json "${source}" "${view}" << 'PY'
import json
import sys
source, view = sys.argv[1:3]
print(json.dumps({
    "source": source,
    "view": view,
    "operation": "MONITOR",
    "expected_evidence_type": "ITEM_DROPPED_CANDIDATE",
    "task_ref": {"task_id": "OPERATOR-QUALITY-REVIEW"},
    "quality_flags": {
        "low_pixel_budget": True,
        "details": {
            "object_size_m": 0.04,
            "note": "operator helper for GoPro dropped-item pixel-budget review",
        },
    },
}, separators=(",", ":")))
PY
  )"
  curl_json_post "${AI_SERVER_URL%/}/api/v1/evidence/evaluate" "${payload}"
}

api_runtime_status() {
  curl_json_get_operator "${AI_SERVER_URL%/}/api/v1/operator/runtime/status"
}

api_restart_low_load() {
  local dry_run="false"
  local git_pull="false"
  local require_clean_git="true"
  local reason="operator low-load parameter restart"
  local args=()
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --dry-run)
        dry_run="true"
        shift
        ;;
      --git-pull | --pull)
        git_pull="true"
        shift
        ;;
      --require-clean-git)
        require_clean_git="true"
        shift
        ;;
      --allow-dirty-git)
        require_clean_git="false"
        shift
        ;;
      --reason)
        reason="${2:-}"
        shift 2
        ;;
      --)
        shift
        break
        ;;
      *)
        args+=("$1")
        shift
        ;;
    esac
  done
  if [ "$#" -gt 0 ]; then
    args+=("$@")
  fi
  local payload
  payload="$(
    python_json "${dry_run}" "${git_pull}" "${require_clean_git}" "${reason}" "${args[@]}" << 'PY'
import json
import sys

dry_run = sys.argv[1].lower() in {"1", "true", "yes", "y", "on"}
git_pull = sys.argv[2].lower() in {"1", "true", "yes", "y", "on"}
require_clean_git = sys.argv[3].lower() in {"1", "true", "yes", "y", "on"}
reason = sys.argv[4]
params = {}
errors = []
for item in sys.argv[5:]:
    if "=" not in item:
        errors.append(f"expected KEY=VALUE, got {item!r}")
        continue
    key, value = item.split("=", 1)
    if not key:
        errors.append(f"empty key in {item!r}")
        continue
    params[key] = value
if errors:
    raise SystemExit("ERROR: " + "; ".join(errors))
print(json.dumps({
    "profile": "lab-gopro-tb3-low-load",
    "params": params,
    "reason": reason,
    "dry_run": dry_run,
    "git_pull": git_pull,
    "require_clean_git": require_clean_git,
}, separators=(",", ":")))
PY
  )"
  curl_json_post_operator "${AI_SERVER_URL%/}/api/v1/operator/runtime/low-load/restart" "${payload}"
}

cmd_api() {
  local subcommand="${1:-help}"
  shift || true
  case "${subcommand}" in
    health) api_health "$@" ;;
    streams) api_streams "$@" ;;
    worker-status | status) api_worker_status "$@" ;;
    worker-tick | tick) api_worker_tick "$@" ;;
    webrtc-offer | offer) api_webrtc_offer "$@" ;;
    evaluate-no-frame | no-frame) api_evaluate_no_frame "$@" ;;
    evaluate-quality | quality) api_evaluate_quality "$@" ;;
    runtime-status | operator-status) api_runtime_status "$@" ;;
    restart-low-load | restart-lowload | runtime-restart) api_restart_low_load "$@" ;;
    help | -h | --help) usage ;;
    *)
      echo "ERROR: unknown api command: ${subcommand}" >&2
      usage >&2
      return 2
      ;;
  esac
}

main() {
  local command="${1:-help}"
  shift || true
  cd "${ROOT_DIR}"
  case "${command}" in
    low-load | lowload | lite) cmd_low_load "$@" ;;
    all | up | stream) cmd_all "$@" ;;
    down | stop) cmd_down "$@" ;;
    check) cmd_check "$@" ;;
    status) cmd_status "$@" ;;
    probe) cmd_probe "$@" ;;
    urls | url) cmd_urls "$@" ;;
    api) cmd_api "$@" ;;
    help | -h | --help) usage ;;
    *)
      echo "ERROR: unknown command: ${command}" >&2
      usage >&2
      return 2
      ;;
  esac
}

main "$@"
