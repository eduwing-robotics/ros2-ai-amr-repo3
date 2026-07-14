#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=scripts/lib/vision_bundle_common.sh
source "${SCRIPT_DIR}/../lib/vision_bundle_common.sh"
ROOT_DIR="$(sf_repo_root_from_script "${BASH_SOURCE[0]}")"

RUN_DIR="${SMARTFACTORY_VISION_RUN_DIR:-${ROOT_DIR}/.run/vision}/webrtc-sidecar"
LOG_DIR="${RUN_DIR}/logs"
PID_FILE="${RUN_DIR}/pids.tsv"
STATUS_FILE="${RUN_DIR}/status.env"
CONFIG_FILE="${WEBRTC_SIDECAR_CONFIG_FILE:-${RUN_DIR}/mediamtx.yml}"

MEDIAMTX_BIN="${MEDIAMTX_BIN:-mediamtx}"
FFMPEG_BIN="${FFMPEG_BIN:-ffmpeg}"
FFPROBE_BIN="${FFPROBE_BIN:-ffprobe}"
CURL_BIN="${CURL_BIN:-curl}"

MEDIAMTX_RTSP_PORT="${MEDIAMTX_RTSP_PORT:-18554}"
MEDIAMTX_WEBRTC_PORT="${MEDIAMTX_WEBRTC_PORT:-8889}"
MEDIAMTX_WEBRTC_ICE_UDP_PORT="${MEDIAMTX_WEBRTC_ICE_UDP_PORT:-8189}"
MEDIAMTX_API_PORT="${MEDIAMTX_API_PORT:-19997}"
MEDIAMTX_WEBRTC_ALLOW_ORIGINS="${MEDIAMTX_WEBRTC_ALLOW_ORIGINS:-http://smartfactory-main.local:8088,http://localhost:8088,http://127.0.0.1:8088}"
MEDIAMTX_WEBRTC_ADDITIONAL_HOSTS="${MEDIAMTX_WEBRTC_ADDITIONAL_HOSTS:-}"
WEBRTC_SIDECAR_PUBLIC_HOST="${WEBRTC_SIDECAR_PUBLIC_HOST:-${VISION_PUBLIC_HOST:-smartfactory-vision.local}}"
WEBRTC_SIDECAR_STREAMS="${WEBRTC_SIDECAR_STREAMS:-global_cam_01/full,global_cam_01/lift_roi}"
WEBRTC_SIDECAR_INPUT_MAX_FPS="${WEBRTC_SIDECAR_INPUT_MAX_FPS:-15}"
WEBRTC_SIDECAR_TARGET_FPS="${WEBRTC_SIDECAR_TARGET_FPS:-15}"
WEBRTC_SIDECAR_BITRATE="${WEBRTC_SIDECAR_BITRATE:-2500k}"
WEBRTC_SIDECAR_BUFSIZE="${WEBRTC_SIDECAR_BUFSIZE:-5000k}"
WEBRTC_SIDECAR_GOP="${WEBRTC_SIDECAR_GOP:-${WEBRTC_SIDECAR_TARGET_FPS}}"
WEBRTC_SIDECAR_RESTART_SEC="${WEBRTC_SIDECAR_RESTART_SEC:-2}"
WEBRTC_SIDECAR_VIDEO_FILTER="${WEBRTC_SIDECAR_VIDEO_FILTER:-scale=trunc(iw/2)*2:trunc(ih/2)*2}"
WEBRTC_SIDECAR_INPUT_PROBESIZE="${WEBRTC_SIDECAR_INPUT_PROBESIZE:-2048}"
WEBRTC_SIDECAR_INPUT_ANALYZEDURATION="${WEBRTC_SIDECAR_INPUT_ANALYZEDURATION:-0}"
WEBRTC_SIDECAR_INPUT_MAX_DELAY="${WEBRTC_SIDECAR_INPUT_MAX_DELAY:-0}"
WEBRTC_SIDECAR_DIRECT_INPUT_PROBESIZE="${WEBRTC_SIDECAR_DIRECT_INPUT_PROBESIZE:-32768}"
WEBRTC_SIDECAR_DIRECT_INPUT_ANALYZEDURATION="${WEBRTC_SIDECAR_DIRECT_INPUT_ANALYZEDURATION:-1000000}"
WEBRTC_SIDECAR_DIRECT_INPUT_MAX_DELAY="${WEBRTC_SIDECAR_DIRECT_INPUT_MAX_DELAY:-${WEBRTC_SIDECAR_INPUT_MAX_DELAY}}"
WEBRTC_SIDECAR_CAMERA_INPUT_PROBESIZE="${WEBRTC_SIDECAR_CAMERA_INPUT_PROBESIZE:-${WEBRTC_SIDECAR_INPUT_PROBESIZE}}"
WEBRTC_SIDECAR_CAMERA_INPUT_ANALYZEDURATION="${WEBRTC_SIDECAR_CAMERA_INPUT_ANALYZEDURATION:-${WEBRTC_SIDECAR_INPUT_ANALYZEDURATION}}"
WEBRTC_SIDECAR_CAMERA_INPUT_MAX_DELAY="${WEBRTC_SIDECAR_CAMERA_INPUT_MAX_DELAY:-${WEBRTC_SIDECAR_INPUT_MAX_DELAY}}"
WEBRTC_SIDECAR_MJPEG_INPUT_PROBESIZE="${WEBRTC_SIDECAR_MJPEG_INPUT_PROBESIZE:-${WEBRTC_SIDECAR_INPUT_PROBESIZE}}"
WEBRTC_SIDECAR_MJPEG_INPUT_ANALYZEDURATION="${WEBRTC_SIDECAR_MJPEG_INPUT_ANALYZEDURATION:-${WEBRTC_SIDECAR_INPUT_ANALYZEDURATION}}"
WEBRTC_SIDECAR_MJPEG_INPUT_MAX_DELAY="${WEBRTC_SIDECAR_MJPEG_INPUT_MAX_DELAY:-${WEBRTC_SIDECAR_INPUT_MAX_DELAY}}"
WEBRTC_SIDECAR_AVIOFLAGS_DIRECT="${WEBRTC_SIDECAR_AVIOFLAGS_DIRECT:-false}"
WEBRTC_SIDECAR_OUTPUT_MUXDELAY="${WEBRTC_SIDECAR_OUTPUT_MUXDELAY:-0}"
WEBRTC_SIDECAR_OUTPUT_MUXPRELOAD="${WEBRTC_SIDECAR_OUTPUT_MUXPRELOAD:-0}"
WEBRTC_SIDECAR_CANDIDATE_START_TIMEOUT_S="${WEBRTC_SIDECAR_CANDIDATE_START_TIMEOUT_S:-20}"
WEBRTC_SIDECAR_NETWORK_RW_TIMEOUT_US="${WEBRTC_SIDECAR_NETWORK_RW_TIMEOUT_US:-3000000}"
WEBRTC_SIDECAR_INPUT_PRIORITY="${WEBRTC_SIDECAR_INPUT_PRIORITY:-direct,camera,mjpeg}"
WEBRTC_SIDECAR_COMPOSITOR_PUBLISHER_STREAMS="${WEBRTC_SIDECAR_COMPOSITOR_PUBLISHER_STREAMS:-${VISION_WEBRTC_COMPOSITOR_PUBLISHER_STREAMS:-}}"
WEBRTC_SIDECAR_COMPOSITOR_METRICS_DIR="${WEBRTC_SIDECAR_COMPOSITOR_METRICS_DIR:-${VISION_WEBRTC_COMPOSITOR_METRICS_DIR:-${SMARTFACTORY_VISION_RUN_DIR:-${ROOT_DIR}/.run/vision}/compositor-metrics}}"
WEBRTC_SIDECAR_DIRECT_INPUT_URL_TEMPLATE="${WEBRTC_SIDECAR_DIRECT_INPUT_URL_TEMPLATE:-${DIRECT_CLEAN_MEDIA_URL:-${GOPRO_DIRECT_MEDIA_URL:-}}}"
WEBRTC_SIDECAR_CAMERA_INPUT_URL_TEMPLATE="${WEBRTC_SIDECAR_CAMERA_INPUT_URL_TEMPLATE:-${WEBRTC_CAMERA_INPUT_URL:-${CAMERA_INPUT_URL:-}}}"
WEBRTC_SIDECAR_DIRECT_INPUT_FORMAT="${WEBRTC_SIDECAR_DIRECT_INPUT_FORMAT:-auto}"
WEBRTC_SIDECAR_CAMERA_INPUT_FORMAT="${WEBRTC_SIDECAR_CAMERA_INPUT_FORMAT:-auto}"
WEBRTC_SIDECAR_MJPEG_INPUT_FORMAT="${WEBRTC_SIDECAR_MJPEG_INPUT_FORMAT:-mpjpeg}"
WEBRTC_SIDECAR_MJPEG_INPUT_URL_TEMPLATE="${WEBRTC_SIDECAR_MJPEG_INPUT_URL_TEMPLATE:-}"
WEBRTC_SIDECAR_CAMERA_INPUT_FPS="${WEBRTC_SIDECAR_CAMERA_INPUT_FPS:-${WEBRTC_SIDECAR_TARGET_FPS}}"
WEBRTC_SIDECAR_CAMERA_INPUT_SIZE="${WEBRTC_SIDECAR_CAMERA_INPUT_SIZE:-}"
WEBRTC_SIDECAR_INPUT_URL_TEMPLATE="${WEBRTC_SIDECAR_INPUT_URL_TEMPLATE:-}"
if [ -z "${WEBRTC_SIDECAR_INPUT_URL_TEMPLATE}" ]; then
  WEBRTC_SIDECAR_INPUT_URL_TEMPLATE="http://127.0.0.1:${VISION_STREAM_GATEWAY_PORT:-8090}/api/v1/vision/overlay/stream?source={source}&view={view}&max_fps={max_fps}"
fi
if [ -z "${WEBRTC_SIDECAR_MJPEG_INPUT_URL_TEMPLATE}" ]; then
  WEBRTC_SIDECAR_MJPEG_INPUT_URL_TEMPLATE="${WEBRTC_SIDECAR_INPUT_URL_TEMPLATE}"
fi
WEBRTC_SIDECAR_ENCODER="${WEBRTC_SIDECAR_ENCODER:-libx264}"
WEBRTC_SIDECAR_X264_PRESET="${WEBRTC_SIDECAR_X264_PRESET:-veryfast}"
WEBRTC_SIDECAR_X264_PARAMS="${WEBRTC_SIDECAR_X264_PARAMS:-keyint=${WEBRTC_SIDECAR_GOP}:min-keyint=${WEBRTC_SIDECAR_GOP}:scenecut=0}"
WEBRTC_SIDECAR_COPY_VIDEO_PATHS="${WEBRTC_SIDECAR_COPY_VIDEO_PATHS:-}"
SF_VISION_TMUX_GUARD_ENABLED="${SF_VISION_TMUX_GUARD_ENABLED:-false}"
SF_VISION_TMUX_REQUIRED_CONTEXT="${SF_VISION_TMUX_REQUIRED_CONTEXT:-Smartfactory:3:Development}"

PIDS=()
NAMES=()

usage() {
  cat << USAGE
Usage: $(basename "$0") [--check|--print-config|--status|--smoke|run]

Run a MediaMTX WebRTC sidecar for SmartFactory Vision overlay streams.
The sidecar is media-only: it does not expose ROS control, Nav2, /cmd_vel,
DB writes, or evidence truth mutation.

Typical operator path:
  ./scripts/vision/sf_vision.sh up lab-gopro-tb3-ffmpeg-first
  ./scripts/vision/sf_vision.sh status
  ./scripts/vision/run_webrtc_sidecar_mediamtx.sh --status

Prerequisites:
  - mediamtx on PATH, or MEDIAMTX_BIN=/path/to/mediamtx
  - ffmpeg/ffprobe on PATH
  - optional: set SF_VISION_TMUX_GUARD_ENABLED=true to require tmux ${SF_VISION_TMUX_REQUIRED_CONTEXT}
USAGE
}

log() {
  printf '[webrtc-sidecar] %s\n' "$*"
}

is_truthy() {
  case "${1:-}" in
    1 | true | TRUE | yes | YES | y | Y | on | ON) return 0 ;;
    *) return 1 ;;
  esac
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
  if ! is_truthy "${SF_VISION_TMUX_GUARD_ENABLED}"; then
    return 0
  fi
  local current
  current="$(current_tmux_context || true)"
  if [ "${current}" = "${SF_VISION_TMUX_REQUIRED_CONTEXT}" ]; then
    return 0
  fi
  cat >&2 << ERROR
ERROR: live WebRTC sidecar processes must run in tmux ${SF_VISION_TMUX_REQUIRED_CONTEXT}.
Current context: ${current:-<not inside tmux>}
Use ./scripts/vision/sf_vision.sh up lab-gopro-tb3-ffmpeg-first from that tmux window.
ERROR
  return 1
}

is_executable_cmd() {
  local cmd="$1"
  if [[ "${cmd}" == */* ]]; then
    [ -x "${cmd}" ]
  else
    command -v "${cmd}" > /dev/null 2>&1
  fi
}

slug() {
  printf '%s' "$1" | tr -c 'A-Za-z0-9_-' '_' | sed -e 's/^_*//' -e 's/_*$//'
}

env_suffix() {
  slug "$1" | tr '[:lower:]-' '[:upper:]_'
}

redact_url() {
  local raw="$1"
  if ! command -v python3 > /dev/null 2>&1; then
    printf '%s' "${raw}" | sed -E 's#(://)[^/@]+@#\\1<redacted>@#'
    return
  fi
  python3 - "$raw" << 'PY'
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import sys

raw = sys.argv[1]
sensitive = {"token", "access_token", "auth", "authorization", "password", "passwd", "pass", "secret", "api_key", "apikey", "key"}
try:
    parts = urlsplit(raw)
except ValueError:
    print(raw)
    raise SystemExit(0)

if not parts.scheme or not parts.netloc:
    print(raw)
    raise SystemExit(0)

netloc = parts.netloc
if "@" in netloc:
    netloc = "<redacted>@" + netloc.rsplit("@", 1)[1]

if parts.query:
    query = urlencode(
        [(k, "REDACTED" if k.lower() in sensitive else v) for k, v in parse_qsl(parts.query, keep_blank_values=True)],
        doseq=True,
    )
else:
    query = parts.query

print(urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment)))
PY
}

redact_stream() {
  if ! command -v python3 > /dev/null 2>&1; then
    sed -E \
      -e 's#(://)[^/@[:space:]]+@#\1<redacted>@#g' \
      -e 's#([?&](token|access_token|auth|authorization|password|passwd|pass|secret|api_key|apikey|key)=)[^&[:space:]]+#\1REDACTED#gI'
    return
  fi
  python3 - << 'PY'
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
import re
import sys

sensitive = {"token", "access_token", "auth", "authorization", "password", "passwd", "pass", "secret", "api_key", "apikey", "key"}
url_re = re.compile(r"\b(?:https?|rtsp|rtmp|tcp|udp)://[^\s\"'<>]+")

def redact_url(raw: str) -> str:
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw
    if not parts.scheme or not parts.netloc:
        return raw
    netloc = parts.netloc
    if "@" in netloc:
        netloc = "<redacted>@" + netloc.rsplit("@", 1)[1]
    query = parts.query
    if query:
        query = urlencode(
            [(k, "REDACTED" if k.lower() in sensitive else v) for k, v in parse_qsl(query, keep_blank_values=True)],
            doseq=True,
        )
    return urlunsplit((parts.scheme, netloc, parts.path, query, parts.fragment))

for line in sys.stdin:
    sys.stdout.write(url_re.sub(lambda match: redact_url(match.group(0)), line))
    sys.stdout.flush()
PY
}

csv_to_json_array() {
  local raw="$1"
  if command -v python3 > /dev/null 2>&1; then
    python3 - "$raw" << 'PY'
import json
import sys
print(json.dumps([item.strip() for item in sys.argv[1].split(",") if item.strip()]))
PY
    return
  fi
  local IFS=',' item first=1
  printf '['
  for item in ${raw}; do
    item="${item#${item%%[![:space:]]*}}"
    item="${item%${item##*[![:space:]]}}"
    [ -n "${item}" ] || continue
    if [ "${first}" -eq 0 ]; then printf ','; fi
    first=0
    item="${item//\"/}"
    printf '"%s"' "${item}"
  done
  printf ']'
}

stream_source() {
  local spec="$1"
  spec="${spec//[[:space:]]/}"
  printf '%s' "${spec%%/*}"
}

stream_view() {
  local spec="$1"
  spec="${spec//[[:space:]]/}"
  if [[ "${spec}" == */* ]]; then
    printf '%s' "${spec#*/}"
  else
    printf 'full'
  fi
}

stream_path_id() {
  local source view
  source="$(slug "$(stream_source "$1")")"
  view="$(slug "$(stream_view "$1")")"
  printf '%s_%s' "${source}" "${view}"
}

render_url_template() {
  local template="$1" source="$2" view="$3" path="$4"
  local url="${template}"
  url="${url//\{source\}/${source}}"
  url="${url//\{source_id\}/${source}}"
  url="${url//\{view\}/${view}}"
  url="${url//\{view_id\}/${view}}"
  url="${url//\{path\}/${path}}"
  url="${url//\{path_id\}/${path}}"
  url="${url//\{max_fps\}/${WEBRTC_SIDECAR_INPUT_MAX_FPS}}"
  printf '%s' "${url}"
}

render_input_url() {
  local source="$1" view="$2"
  local path
  path="$(slug "${source}_${view}")"
  render_url_template "${WEBRTC_SIDECAR_INPUT_URL_TEMPLATE}" "${source}" "${view}" "${path}"
}

first_set_env_value() {
  local name
  for name in "$@"; do
    if [ -n "${!name:-}" ]; then
      printf '%s' "${!name}"
      return 0
    fi
  done
  return 1
}

stream_template_value() {
  local kind="$1" source="$2" view="$3" path="$4"
  local source_suffix view_suffix path_suffix template_var legacy_var
  source_suffix="$(env_suffix "${source}")"
  view_suffix="$(env_suffix "${view}")"
  path_suffix="$(env_suffix "${path}")"
  template_var="WEBRTC_SIDECAR_${kind}_INPUT_URL_TEMPLATE"
  legacy_var="WEBRTC_SIDECAR_${kind}_INPUT_URL"
  first_set_env_value \
    "${template_var}_${path_suffix}" \
    "${template_var}_${source_suffix}_${view_suffix}" \
    "WEBRTC_SIDECAR_${path_suffix}_${kind}_INPUT_URL_TEMPLATE" \
    "WEBRTC_SIDECAR_${source_suffix}_${view_suffix}_${kind}_INPUT_URL_TEMPLATE" \
    "${legacy_var}_${path_suffix}" \
    "${legacy_var}_${source_suffix}_${view_suffix}" \
    "${template_var}" \
    "${legacy_var}" || true
}

stream_mjpeg_template_value() {
  local source="$1" view="$2" path="$3"
  local source_suffix view_suffix path_suffix
  source_suffix="$(env_suffix "${source}")"
  view_suffix="$(env_suffix "${view}")"
  path_suffix="$(env_suffix "${path}")"
  first_set_env_value \
    "WEBRTC_SIDECAR_MJPEG_INPUT_URL_TEMPLATE_${path_suffix}" \
    "WEBRTC_SIDECAR_MJPEG_INPUT_URL_TEMPLATE_${source_suffix}_${view_suffix}" \
    "WEBRTC_SIDECAR_${path_suffix}_MJPEG_INPUT_URL_TEMPLATE" \
    "WEBRTC_SIDECAR_${source_suffix}_${view_suffix}_MJPEG_INPUT_URL_TEMPLATE" \
    "WEBRTC_SIDECAR_MJPEG_INPUT_URL_${path_suffix}" \
    "WEBRTC_SIDECAR_MJPEG_INPUT_URL_${source_suffix}_${view_suffix}" \
    "WEBRTC_SIDECAR_MJPEG_INPUT_URL_TEMPLATE" \
    "WEBRTC_SIDECAR_MJPEG_INPUT_URL" || printf '%s' "${WEBRTC_SIDECAR_INPUT_URL_TEMPLATE}"
}

stream_mediamtx_source_template_value() {
  local source="$1" view="$2" path="$3"
  local source_suffix view_suffix path_suffix
  source_suffix="$(env_suffix "${source}")"
  view_suffix="$(env_suffix "${view}")"
  path_suffix="$(env_suffix "${path}")"
  first_set_env_value \
    "WEBRTC_SIDECAR_MEDIAMTX_SOURCE_TEMPLATE_${path_suffix}" \
    "WEBRTC_SIDECAR_MEDIAMTX_SOURCE_TEMPLATE_${source_suffix}_${view_suffix}" \
    "WEBRTC_SIDECAR_${path_suffix}_MEDIAMTX_SOURCE_TEMPLATE" \
    "WEBRTC_SIDECAR_${source_suffix}_${view_suffix}_MEDIAMTX_SOURCE_TEMPLATE" \
    "WEBRTC_SIDECAR_MEDIAMTX_SOURCE_${path_suffix}" \
    "WEBRTC_SIDECAR_MEDIAMTX_SOURCE_${source_suffix}_${view_suffix}" \
    "WEBRTC_SIDECAR_${path_suffix}_MEDIAMTX_SOURCE" \
    "WEBRTC_SIDECAR_${source_suffix}_${view_suffix}_MEDIAMTX_SOURCE" \
    "WEBRTC_SIDECAR_MEDIAMTX_SOURCE_TEMPLATE" \
    "WEBRTC_SIDECAR_MEDIAMTX_SOURCE" || true
}

stream_mediamtx_source_value() {
  local source="$1" view="$2" path="$3"
  local template
  template="$(stream_mediamtx_source_template_value "${source}" "${view}" "${path}")"
  [ -n "${template}" ] || return 0
  render_url_template "${template}" "${source}" "${view}" "${path}"
}

stream_has_direct_mediamtx_source() {
  local source="$1" view="$2" path="$3"
  [ -n "$(stream_mediamtx_source_value "${source}" "${view}" "${path}")" ]
}

stream_format_value() {
  local kind="$1" source="$2" view="$3" path="$4" fallback="$5"
  local source_suffix view_suffix path_suffix format_var
  source_suffix="$(env_suffix "${source}")"
  view_suffix="$(env_suffix "${view}")"
  path_suffix="$(env_suffix "${path}")"
  format_var="WEBRTC_SIDECAR_${kind}_INPUT_FORMAT"
  first_set_env_value \
    "${format_var}_${path_suffix}" \
    "${format_var}_${source_suffix}_${view_suffix}" \
    "WEBRTC_SIDECAR_${path_suffix}_${kind}_INPUT_FORMAT" \
    "WEBRTC_SIDECAR_${source_suffix}_${view_suffix}_${kind}_INPUT_FORMAT" \
    "${format_var}" || printf '%s' "${fallback}"
}

stream_input_priority_value() {
  local source="$1" view="$2" path="$3"
  local source_suffix view_suffix path_suffix
  source_suffix="$(env_suffix "${source}")"
  view_suffix="$(env_suffix "${view}")"
  path_suffix="$(env_suffix "${path}")"
  first_set_env_value \
    "WEBRTC_SIDECAR_INPUT_PRIORITY_${path_suffix}" \
    "WEBRTC_SIDECAR_INPUT_PRIORITY_${source_suffix}_${view_suffix}" \
    "WEBRTC_SIDECAR_${path_suffix}_INPUT_PRIORITY" \
    "WEBRTC_SIDECAR_${source_suffix}_${view_suffix}_INPUT_PRIORITY" ||
    printf '%s' "${WEBRTC_SIDECAR_INPUT_PRIORITY}"
}

normalize_transport_token() {
  case "${1//[[:space:]]/}" in
    direct | direct_clean_media | direct_clean_media_webrtc) printf 'direct_clean_media_webrtc' ;;
    camera | camera_input | camera_input_h264 | camera_input_h264_transcode_webrtc) printf 'camera_input_h264_transcode_webrtc' ;;
    mjpeg | overlay | mjpeg_overlay | mjpeg_overlay_h264_transcode_webrtc | fallback) printf 'mjpeg_overlay_h264_transcode_webrtc' ;;
    *) return 1 ;;
  esac
}

candidate_line_for_transport() {
  local transport="$1" source="$2" view="$3" path="$4" template url format
  case "${transport}" in
    direct_clean_media_webrtc)
      template="$(stream_template_value DIRECT "${source}" "${view}" "${path}")"
      [ -n "${template}" ] || return 0
      url="$(render_url_template "${template}" "${source}" "${view}" "${path}")"
      format="$(stream_format_value DIRECT "${source}" "${view}" "${path}" "${WEBRTC_SIDECAR_DIRECT_INPUT_FORMAT}")"
      ;;
    camera_input_h264_transcode_webrtc)
      template="$(stream_template_value CAMERA "${source}" "${view}" "${path}")"
      [ -n "${template}" ] || return 0
      url="$(render_url_template "${template}" "${source}" "${view}" "${path}")"
      format="$(stream_format_value CAMERA "${source}" "${view}" "${path}" "${WEBRTC_SIDECAR_CAMERA_INPUT_FORMAT}")"
      if [ "${format}" = "auto" ] && [[ "${url}" == /dev/video* ]]; then
        format="v4l2"
      fi
      ;;
    mjpeg_overlay_h264_transcode_webrtc)
      template="$(stream_mjpeg_template_value "${source}" "${view}" "${path}")"
      url="$(render_url_template "${template}" "${source}" "${view}" "${path}")"
      format="${WEBRTC_SIDECAR_MJPEG_INPUT_FORMAT}"
      ;;
    *) return 0 ;;
  esac
  [ -n "${url}" ] || return 0
  printf '%s\t%s\t%s\n' "${transport}" "${format}" "${url}"
}

render_input_candidates() {
  local source="$1" view="$2" path="$3"
  local token transport priority seen="," emitted_mjpeg=0
  priority="$(stream_input_priority_value "${source}" "${view}" "${path}")"
  local IFS=','
  for token in ${priority}; do
    transport="$(normalize_transport_token "${token}" || true)"
    [ -n "${transport}" ] || continue
    case "${seen}" in
      *",${transport},"*) continue ;;
    esac
    seen="${seen}${transport},"
    [ "${transport}" = "mjpeg_overlay_h264_transcode_webrtc" ] && emitted_mjpeg=1
    candidate_line_for_transport "${transport}" "${source}" "${view}" "${path}"
  done
  if [ "${emitted_mjpeg}" -eq 0 ]; then
    candidate_line_for_transport "mjpeg_overlay_h264_transcode_webrtc" "${source}" "${view}" "${path}"
  fi
}

write_input_candidates_file() {
  local source="$1" view="$2" path="$3"
  local candidate_file="${RUN_DIR}/input-candidates-${path}.tsv"
  local old_umask
  old_umask="$(umask)"
  umask 077
  render_input_candidates "${source}" "${view}" "${path}" > "${candidate_file}"
  umask "${old_umask}"
  chmod 600 "${candidate_file}" 2> /dev/null || true
  printf '%s' "${candidate_file}"
}

read_stream_specs() {
  local -n _out="$1"
  local raw spec
  IFS=',' read -r -a _out <<< "${WEBRTC_SIDECAR_STREAMS}"
  local cleaned=()
  for raw in "${_out[@]}"; do
    spec="${raw//[[:space:]]/}"
    [ -n "${spec}" ] || continue
    cleaned+=("${spec}")
  done
  _out=("${cleaned[@]}")
}

stream_paths_csv() {
  local specs=() spec path paths=()
  read_stream_specs specs
  for spec in "${specs[@]}"; do
    path="$(stream_path_id "${spec}")"
    paths+=("${path}")
  done
  local IFS=','
  printf '%s' "${paths[*]}"
}

csv_contains() {
  local needle="$1" raw="$2" item
  local IFS=','
  for item in ${raw}; do
    item="${item//[[:space:]]/}"
    [ -n "${item}" ] || continue
    if [ "${item}" = "${needle}" ]; then
      return 0
    fi
  done
  return 1
}

stream_is_compositor_publisher() {
  local spec="$1" path="$2" raw="${WEBRTC_SIDECAR_COMPOSITOR_PUBLISHER_STREAMS:-}" item
  [ -n "${raw}" ] || return 1
  local IFS=','
  for item in ${raw}; do
    item="${item//[[:space:]]/}"
    [ -n "${item}" ] || continue
    if [ "${item}" = "${spec}" ] || [ "${item}" = "${path}" ]; then
      return 0
    fi
  done
  return 1
}

publisher_stream_count() {
  local specs=() spec source view path count=0
  read_stream_specs specs
  for spec in "${specs[@]}"; do
    source="$(stream_source "${spec}")"
    view="$(stream_view "${spec}")"
    path="$(stream_path_id "${spec}")"
    if stream_has_direct_mediamtx_source "${source}" "${view}" "${path}"; then
      continue
    fi
    if stream_is_compositor_publisher "${spec}" "${path}"; then
      continue
    fi
    count=$((count + 1))
  done
  printf '%s' "${count}"
}

mediamtx_webrtc_additional_hosts_csv() {
  if [ -n "${MEDIAMTX_WEBRTC_ADDITIONAL_HOSTS}" ]; then
    printf '%s' "${MEDIAMTX_WEBRTC_ADDITIONAL_HOSTS}"
    return 0
  fi
  if [ -z "${WEBRTC_SIDECAR_PUBLIC_HOST}" ]; then
    return 0
  fi
  case "${WEBRTC_SIDECAR_PUBLIC_HOST}" in
    *.local)
      # MediaMTX is written in Go and resolves webrtcAdditionalHosts through
      # regular DNS, not always through NSS/mDNS.  Keep the user-facing
      # smartfactory-vision.local URLs, but advertise the LAN IP in ICE.
      sf_lan_ip "${VISION_MAIN_HOST:-}" || true
      ;;
    *)
      printf '%s' "${WEBRTC_SIDECAR_PUBLIC_HOST}"
      ;;
  esac
}

validate_site_network_hosts() {
  local additional_hosts prefix host
  prefix="${SMARTFACTORY_LAN_IPV4_PREFIX:-192.168.30.}"
  additional_hosts="$(mediamtx_webrtc_additional_hosts_csv)"
  if [[ "${WEBRTC_SIDECAR_PUBLIC_HOST}" == *.local && -z "${additional_hosts}" ]]; then
    echo "ERROR: no WebRTC address found on SmartFactory site prefix ${prefix}" >&2
    return 1
  fi
  local IFS=','
  for host in ${additional_hosts}; do
    host="${host//[[:space:]]/}"
    if [[ "${host}" =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && [[ "${host}" != "${prefix}"* ]]; then
      echo "ERROR: WebRTC address ${host} is outside SmartFactory site prefix ${prefix}" >&2
      return 1
    fi
  done
}

print_config() {
  validate_site_network_hosts
  local specs=() spec source view path input_url input_priority candidates first_transport first_format first_url mediamtx_source transport_origin
  read_stream_specs specs
  local additional_hosts
  additional_hosts="$(mediamtx_webrtc_additional_hosts_csv)"
  cat << CONFIG
SmartFactory Vision WebRTC sidecar config
  run_dir: ${RUN_DIR}
  config_file: ${CONFIG_FILE}
  mediamtx_bin: ${MEDIAMTX_BIN}
  ffmpeg_bin: ${FFMPEG_BIN}
  ffprobe_bin: ${FFPROBE_BIN}
  public_host: ${WEBRTC_SIDECAR_PUBLIC_HOST}
  rtsp: rtsp://127.0.0.1:${MEDIAMTX_RTSP_PORT}/<path>
  browser_url_template: http://${WEBRTC_SIDECAR_PUBLIC_HOST}:${MEDIAMTX_WEBRTC_PORT}/{source}_{view}
  whep_url_template: http://${WEBRTC_SIDECAR_PUBLIC_HOST}:${MEDIAMTX_WEBRTC_PORT}/{source}_{view}/whep
  mediamtx_ports: rtsp=${MEDIAMTX_RTSP_PORT}/tcp, webrtc=${MEDIAMTX_WEBRTC_PORT}/tcp, ice=${MEDIAMTX_WEBRTC_ICE_UDP_PORT}/udp, api=127.0.0.1:${MEDIAMTX_API_PORT}/tcp
  webrtc_allow_origins: ${MEDIAMTX_WEBRTC_ALLOW_ORIGINS}
  webrtc_additional_hosts: ${additional_hosts:-<auto-interface-only>}
  input_priority: ${WEBRTC_SIDECAR_INPUT_PRIORITY}
  direct_input_url_template: $(redact_url "${WEBRTC_SIDECAR_DIRECT_INPUT_URL_TEMPLATE:-<unset>}")
  camera_input_url_template: $(redact_url "${WEBRTC_SIDECAR_CAMERA_INPUT_URL_TEMPLATE:-<unset>}")
  mjpeg_fallback_input_url_template: $(redact_url "${WEBRTC_SIDECAR_INPUT_URL_TEMPLATE}")
  mjpeg_input_url_template: $(redact_url "${WEBRTC_SIDECAR_MJPEG_INPUT_URL_TEMPLATE}")
  input_url_template: $(redact_url "${WEBRTC_SIDECAR_INPUT_URL_TEMPLATE}")
  candidate_start_timeout_s: ${WEBRTC_SIDECAR_CANDIDATE_START_TIMEOUT_S}
  network_rw_timeout_us: ${WEBRTC_SIDECAR_NETWORK_RW_TIMEOUT_US}
  video_filter: ${WEBRTC_SIDECAR_VIDEO_FILTER}
  encoder: ${WEBRTC_SIDECAR_ENCODER}
  x264_preset: ${WEBRTC_SIDECAR_X264_PRESET}
  x264_params: ${WEBRTC_SIDECAR_X264_PARAMS}
  copy_video_paths: ${WEBRTC_SIDECAR_COPY_VIDEO_PATHS:-<empty>}
  compositor_publisher_streams: ${WEBRTC_SIDECAR_COMPOSITOR_PUBLISHER_STREAMS:-<empty>}
  compositor_metrics_dir: ${WEBRTC_SIDECAR_COMPOSITOR_METRICS_DIR}
  target_fps: ${WEBRTC_SIDECAR_TARGET_FPS}
  gop: ${WEBRTC_SIDECAR_GOP}
  bitrate: ${WEBRTC_SIDECAR_BITRATE}
  bufsize: ${WEBRTC_SIDECAR_BUFSIZE}
  input_probesize: ${WEBRTC_SIDECAR_INPUT_PROBESIZE}
  input_analyzeduration: ${WEBRTC_SIDECAR_INPUT_ANALYZEDURATION}
  input_max_delay: ${WEBRTC_SIDECAR_INPUT_MAX_DELAY}
  direct_input_probesize: ${WEBRTC_SIDECAR_DIRECT_INPUT_PROBESIZE}
  direct_input_analyzeduration: ${WEBRTC_SIDECAR_DIRECT_INPUT_ANALYZEDURATION}
  direct_input_max_delay: ${WEBRTC_SIDECAR_DIRECT_INPUT_MAX_DELAY}
  camera_input_probesize: ${WEBRTC_SIDECAR_CAMERA_INPUT_PROBESIZE}
  camera_input_analyzeduration: ${WEBRTC_SIDECAR_CAMERA_INPUT_ANALYZEDURATION}
  camera_input_max_delay: ${WEBRTC_SIDECAR_CAMERA_INPUT_MAX_DELAY}
  mjpeg_input_probesize: ${WEBRTC_SIDECAR_MJPEG_INPUT_PROBESIZE}
  mjpeg_input_analyzeduration: ${WEBRTC_SIDECAR_MJPEG_INPUT_ANALYZEDURATION}
  mjpeg_input_max_delay: ${WEBRTC_SIDECAR_MJPEG_INPUT_MAX_DELAY}
  avioflags_direct: ${WEBRTC_SIDECAR_AVIOFLAGS_DIRECT}
  output_muxdelay: ${WEBRTC_SIDECAR_OUTPUT_MUXDELAY}
  output_muxpreload: ${WEBRTC_SIDECAR_OUTPUT_MUXPRELOAD}
  streams:
CONFIG
  for spec in "${specs[@]}"; do
    source="$(stream_source "${spec}")"
    view="$(stream_view "${spec}")"
    path="$(stream_path_id "${spec}")"
    input_priority="$(stream_input_priority_value "${source}" "${view}" "${path}")"
    mediamtx_source="$(stream_mediamtx_source_value "${source}" "${view}" "${path}")"
    candidates=""
    first_transport=""
    first_format=""
    first_url=""
    transport_origin="publisher"
    if [ -n "${mediamtx_source}" ]; then
      first_transport="direct_mediamtx_source"
      first_format="mediamtx_source"
      first_url="${mediamtx_source}"
      transport_origin="direct_mediamtx_source"
    elif stream_is_compositor_publisher "${spec}" "${path}"; then
      first_transport="vision_pc_compositor_publisher"
      first_format="rtsp_publisher"
      first_url="rtsp://127.0.0.1:${MEDIAMTX_RTSP_PORT}/${path}"
      transport_origin="vision_pc_compositor_publisher"
    else
      candidates="$(render_input_candidates "${source}" "${view}" "${path}")"
    fi
    if [ -n "${candidates}" ] && [ -z "${first_url}" ]; then
      IFS=$'\t' read -r first_transport first_format first_url <<< "$(printf '%s\n' "${candidates}" | head -n 1)"
    fi
    input_url="${first_url:-$(render_input_url "${source}" "${view}")}"
    cat << CONFIG
    - spec=${spec} path=${path}
      input=$(redact_url "${input_url}")
      input_transport=${first_transport:-<none>}
      input_format=${first_format:-<none>}
      effective_input_priority=${input_priority}
      transport_origin=${transport_origin}
      mediamtx_source=$(redact_url "${mediamtx_source:-publisher}")
      input_candidates:
CONFIG
    if [ -n "${mediamtx_source}" ]; then
      cat << CONFIG
        - transport=direct_mediamtx_source format=mediamtx_source url=$(redact_url "${mediamtx_source}")
CONFIG
    elif stream_is_compositor_publisher "${spec}" "${path}"; then
      cat << CONFIG
        - transport=vision_pc_compositor_publisher format=rtsp_publisher url=rtsp://127.0.0.1:${MEDIAMTX_RTSP_PORT}/${path}
          metrics=${WEBRTC_SIDECAR_COMPOSITOR_METRICS_DIR}/${path}.json
CONFIG
    else
      while IFS=$'\t' read -r candidate_transport candidate_format candidate_url; do
        [ -n "${candidate_transport:-}" ] || continue
        cat << CONFIG
        - transport=${candidate_transport} format=${candidate_format} url=$(redact_url "${candidate_url}")
CONFIG
      done <<< "${candidates}"
    fi
    cat << CONFIG
      rtsp=rtsp://127.0.0.1:${MEDIAMTX_RTSP_PORT}/${path}
      browser=http://${WEBRTC_SIDECAR_PUBLIC_HOST}:${MEDIAMTX_WEBRTC_PORT}/${path}/
      whep=http://${WEBRTC_SIDECAR_PUBLIC_HOST}:${MEDIAMTX_WEBRTC_PORT}/${path}/whep
CONFIG
  done
}

install_guidance() {
  cat << 'GUIDANCE' >&2

Install MediaMTX before using the WebRTC sidecar:
  1) Download the Linux amd64 release from https://github.com/bluenviron/mediamtx/releases
  2) Extract it and place the `mediamtx` binary on PATH, or set:
       export MEDIAMTX_BIN=/absolute/path/to/mediamtx
  3) Verify:
       ./scripts/vision/run_webrtc_sidecar_mediamtx.sh --check

ffmpeg is also required. On Ubuntu it is usually available with:
  sudo apt install ffmpeg
GUIDANCE
}

port_tcp_in_use() {
  local port="$1"
  if command -v ss > /dev/null 2>&1; then
    ss -H -ltn 2> /dev/null | awk '{print $4}' | grep -Eq "(^|:)${port}$"
  else
    return 1
  fi
}

port_udp_in_use() {
  local port="$1"
  if command -v ss > /dev/null 2>&1; then
    ss -H -lun 2> /dev/null | awk '{print $4}' | grep -Eq "(^|:)${port}$"
  else
    return 1
  fi
}

check_port_free() {
  local kind="$1" port="$2" label="$3"
  if [ "${kind}" = "tcp" ]; then
    if port_tcp_in_use "${port}"; then
      echo "ERROR: ${label} tcp/${port} is already in use" >&2
      return 1
    fi
  else
    if port_udp_in_use "${port}"; then
      echo "ERROR: ${label} udp/${port} is already in use" >&2
      return 1
    fi
  fi
}

validate_specs() {
  local specs=() spec source view path count=0
  read_stream_specs specs
  if [ "${#specs[@]}" -eq 0 ]; then
    echo "ERROR: WEBRTC_SIDECAR_STREAMS is empty" >&2
    return 1
  fi
  for spec in "${specs[@]}"; do
    source="$(stream_source "${spec}")"
    view="$(stream_view "${spec}")"
    path="$(stream_path_id "${spec}")"
    if [ -z "${source}" ] || [ -z "${view}" ] || [ -z "${path}" ]; then
      echo "ERROR: invalid stream spec: ${spec}" >&2
      return 1
    fi
    count=$((count + 1))
  done
}

direct_mediamtx_udp_port() {
  local url="$1"
  python3 - "${url}" << 'PY' 2> /dev/null || true
import re
import sys
url = sys.argv[1]
match = re.match(r"^udp\\+mpegts://(?:\\[[^\\]]+\\]|[^:/?#]*):(\\d+)(?:[/?#].*)?$", url)
if match:
    print(match.group(1))
PY
}

check_direct_mediamtx_source_ports_free() {
  local specs=() spec source view path mediamtx_source udp_port ok=0
  read_stream_specs specs
  for spec in "${specs[@]}"; do
    source="$(stream_source "${spec}")"
    view="$(stream_view "${spec}")"
    path="$(stream_path_id "${spec}")"
    mediamtx_source="$(stream_mediamtx_source_value "${source}" "${view}" "${path}")"
    [ -n "${mediamtx_source}" ] || continue
    udp_port="$(direct_mediamtx_udp_port "${mediamtx_source}")"
    if [ -n "${udp_port}" ]; then
      check_port_free udp "${udp_port}" "MediaMTX direct source ${path}" || ok=1
    fi
  done
  return "${ok}"
}

run_check() {
  local ok=0
  validate_site_network_hosts || ok=1
  validate_specs || ok=1
  if ! is_executable_cmd "${MEDIAMTX_BIN}"; then
    echo "ERROR: mediamtx executable not found: ${MEDIAMTX_BIN}" >&2
    install_guidance
    ok=1
  fi
  if ! is_executable_cmd "${FFMPEG_BIN}"; then
    echo "ERROR: ffmpeg executable not found: ${FFMPEG_BIN}" >&2
    ok=1
  fi
  if ! is_executable_cmd "${FFPROBE_BIN}"; then
    echo "WARN: ffprobe executable not found: ${FFPROBE_BIN}; --smoke RTSP readability check will be unavailable" >&2
  fi
  if ! is_executable_cmd "${CURL_BIN}"; then
    echo "ERROR: curl executable not found: ${CURL_BIN}" >&2
    ok=1
  fi
  check_port_free tcp "${MEDIAMTX_RTSP_PORT}" "MediaMTX RTSP" || ok=1
  check_port_free tcp "${MEDIAMTX_WEBRTC_PORT}" "MediaMTX WebRTC HTTP" || ok=1
  check_port_free tcp "${MEDIAMTX_API_PORT}" "MediaMTX API" || ok=1
  check_port_free udp "${MEDIAMTX_WEBRTC_ICE_UDP_PORT}" "MediaMTX WebRTC ICE" || ok=1
  check_direct_mediamtx_source_ports_free || ok=1
  if [ "${ok}" -ne 0 ]; then
    return 1
  fi
  log "check ok"
}

write_config() {
  mkdir -p "${RUN_DIR}" "${LOG_DIR}"
  chmod 700 "${RUN_DIR}" "${LOG_DIR}" 2> /dev/null || true
  local specs=() spec source view path mediamtx_source
  read_stream_specs specs
  local additional_hosts="[]"
  local additional_hosts_csv
  local allow_origins
  allow_origins="$(csv_to_json_array "${MEDIAMTX_WEBRTC_ALLOW_ORIGINS}")"
  additional_hosts_csv="$(mediamtx_webrtc_additional_hosts_csv)"
  additional_hosts="$(csv_to_json_array "${additional_hosts_csv}")"
  cat > "${CONFIG_FILE}" << YAML
logLevel: info
logDestinations: [stdout]

api: true
apiAddress: 127.0.0.1:${MEDIAMTX_API_PORT}
metrics: false
pprof: false
playback: false

rtsp: true
rtspTransports: [tcp]
rtspAddress: 127.0.0.1:${MEDIAMTX_RTSP_PORT}
rtmp: false
hls: false
srt: false
moq: false

webrtc: true
webrtcAddress: :${MEDIAMTX_WEBRTC_PORT}
webrtcEncryption: false
webrtcAllowOrigins: ${allow_origins}
webrtcLocalUDPAddress: :${MEDIAMTX_WEBRTC_ICE_UDP_PORT}
webrtcLocalTCPAddress: ""
webrtcIPsFromInterfaces: true
webrtcAdditionalHosts: ${additional_hosts}

pathDefaults:
  source: publisher
  overridePublisher: false

paths:
YAML
  for spec in "${specs[@]}"; do
    source="$(stream_source "${spec}")"
    view="$(stream_view "${spec}")"
    path="$(stream_path_id "${spec}")"
    mediamtx_source="$(stream_mediamtx_source_value "${source}" "${view}" "${path}")"
    if [ -n "${mediamtx_source}" ]; then
      cat >> "${CONFIG_FILE}" << YAML
  ${path}:
    source: ${mediamtx_source}
YAML
    else
      cat >> "${CONFIG_FILE}" << YAML
  ${path}:
    source: publisher
YAML
    fi
  done
  chmod 600 "${CONFIG_FILE}" 2> /dev/null || true
}

record_process() {
  local name="$1" pid="$2" log_file="$3"
  printf '%s\t%s\t%s\n' "${name}" "${pid}" "${log_file}" >> "${PID_FILE}"
}

write_status() {
  local status="$1" mediamtx_pid="${2:-}" expected="${3:-0}"
  cat > "${STATUS_FILE}" << STATUS
STATUS=${status}
MEDIAMTX_PID=${mediamtx_pid}
EXPECTED_PUBLISHERS=${expected}
STREAM_PATHS=$(stream_paths_csv)
COMPOSITOR_PUBLISHER_STREAMS=${WEBRTC_SIDECAR_COMPOSITOR_PUBLISHER_STREAMS}
COMPOSITOR_METRICS_DIR=${WEBRTC_SIDECAR_COMPOSITOR_METRICS_DIR}
MEDIAMTX_RTSP_PORT=${MEDIAMTX_RTSP_PORT}
MEDIAMTX_WEBRTC_PORT=${MEDIAMTX_WEBRTC_PORT}
MEDIAMTX_WEBRTC_ICE_UDP_PORT=${MEDIAMTX_WEBRTC_ICE_UDP_PORT}
MEDIAMTX_API_PORT=${MEDIAMTX_API_PORT}
WEBRTC_SIDECAR_PUBLIC_HOST=${WEBRTC_SIDECAR_PUBLIC_HOST}
MEDIAMTX_WEBRTC_ADDITIONAL_HOSTS=$(mediamtx_webrtc_additional_hosts_csv)
CONFIG_FILE=${CONFIG_FILE}
STATUS
}

alive_pid() {
  local pid="${1:-}"
  [ -n "${pid}" ] && kill -0 "${pid}" 2> /dev/null
}

mediamtx_path_ready() {
  local path="$1"
  if ! is_executable_cmd "${CURL_BIN}"; then
    return 1
  fi
  local body
  body="$("${CURL_BIN}" -fsS --max-time 1 "http://127.0.0.1:${MEDIAMTX_API_PORT}/v3/paths/list" 2> /dev/null || true)"
  [ -n "${body}" ] || return 1
  if command -v python3 > /dev/null 2>&1; then
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
    return $?
  fi
  printf '%s' "${body}" | grep -q "\"name\":\"${path}\"" && printf '%s' "${body}" | grep -Eq '"(ready|available|online|sourceReady)":true'
}

wait_for_candidate_start() {
  local path="$1" ffmpeg_pid="$2" timeout_s="$3"
  if [ "${timeout_s}" -le 0 ]; then
    return 0
  fi
  local start now
  start="$(date +%s)"
  while alive_pid "${ffmpeg_pid}"; do
    if mediamtx_path_ready "${path}"; then
      return 0
    fi
    now="$(date +%s)"
    if [ $((now - start)) -ge "${timeout_s}" ]; then
      return 1
    fi
    sleep 0.25
  done
  return 2
}

publisher_loop() {
  local source="$1" view="$2" path="$3" candidate_file="$4" rtsp_url="$5"
  local restart_count=0
  local encoder_extra_args=()
  local input_extra_args=()
  local path_copy_video=false
  if csv_contains "${path}" "${WEBRTC_SIDECAR_COPY_VIDEO_PATHS}"; then
    path_copy_video=true
  fi
  if [[ "${WEBRTC_SIDECAR_ENCODER}" == libx264* ]] && [ -n "${WEBRTC_SIDECAR_X264_PARAMS}" ]; then
    encoder_extra_args=(-x264-params "${WEBRTC_SIDECAR_X264_PARAMS}")
  fi
  if is_truthy "${WEBRTC_SIDECAR_AVIOFLAGS_DIRECT}"; then
    input_extra_args=(-avioflags direct)
  fi
  while true; do
    restart_count=$((restart_count + 1))
    local candidate_transport candidate_format input_url tried=0
    while IFS=$'\t' read -r candidate_transport candidate_format input_url; do
      [ -n "${candidate_transport:-}" ] || continue
      tried=1
      local input_format_args=()
      local transport_args=()
      local input_probesize="${WEBRTC_SIDECAR_INPUT_PROBESIZE}"
      local input_analyzeduration="${WEBRTC_SIDECAR_INPUT_ANALYZEDURATION}"
      local input_max_delay="${WEBRTC_SIDECAR_INPUT_MAX_DELAY}"
      case "${candidate_format}" in
        "" | auto) ;;
        mjpeg | mpjpeg) input_format_args=(-f mpjpeg) ;;
        v4l2)
          input_format_args=(-f v4l2)
          [ -n "${WEBRTC_SIDECAR_CAMERA_INPUT_FPS}" ] && input_format_args+=(-framerate "${WEBRTC_SIDECAR_CAMERA_INPUT_FPS}")
          [ -n "${WEBRTC_SIDECAR_CAMERA_INPUT_SIZE}" ] && input_format_args+=(-video_size "${WEBRTC_SIDECAR_CAMERA_INPUT_SIZE}")
          ;;
        *) input_format_args=(-f "${candidate_format}") ;;
      esac
      case "${input_url}" in
        rtsp://*) transport_args=(-rtsp_transport tcp -rw_timeout "${WEBRTC_SIDECAR_NETWORK_RW_TIMEOUT_US}") ;;
        http://* | https://*) transport_args=(-rw_timeout "${WEBRTC_SIDECAR_NETWORK_RW_TIMEOUT_US}" -reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 2) ;;
        tcp://* | udp://*) transport_args=(-rw_timeout "${WEBRTC_SIDECAR_NETWORK_RW_TIMEOUT_US}") ;;
      esac
      case "${candidate_transport}" in
        direct_clean_media_webrtc)
          input_probesize="${WEBRTC_SIDECAR_DIRECT_INPUT_PROBESIZE}"
          input_analyzeduration="${WEBRTC_SIDECAR_DIRECT_INPUT_ANALYZEDURATION}"
          input_max_delay="${WEBRTC_SIDECAR_DIRECT_INPUT_MAX_DELAY}"
          ;;
        camera_input_h264_transcode_webrtc)
          input_probesize="${WEBRTC_SIDECAR_CAMERA_INPUT_PROBESIZE}"
          input_analyzeduration="${WEBRTC_SIDECAR_CAMERA_INPUT_ANALYZEDURATION}"
          input_max_delay="${WEBRTC_SIDECAR_CAMERA_INPUT_MAX_DELAY}"
          ;;
        mjpeg_overlay_h264_transcode_webrtc)
          input_probesize="${WEBRTC_SIDECAR_MJPEG_INPUT_PROBESIZE}"
          input_analyzeduration="${WEBRTC_SIDECAR_MJPEG_INPUT_ANALYZEDURATION}"
          input_max_delay="${WEBRTC_SIDECAR_MJPEG_INPUT_MAX_DELAY}"
          ;;
      esac
      local copy_video_candidate=false
      if [ "${path_copy_video}" = true ] && [ "${candidate_transport}" = "direct_clean_media_webrtc" ]; then
        copy_video_candidate=true
      fi
      printf '[webrtc-sidecar] publisher path=%s source=%s view=%s start attempt=%s transport=%s format=%s input=%s output=%s at %s\n' \
        "${path}" "${source}" "${view}" "${restart_count}" "${candidate_transport}" "${candidate_format}" "$(redact_url "${input_url}")" "${rtsp_url}" "$(date -Is)"
      set +e
      if [ "${copy_video_candidate}" = true ]; then
        "${FFMPEG_BIN}" \
          -hide_banner -loglevel warning \
          "${transport_args[@]}" \
          -analyzeduration "${input_analyzeduration}" \
          -probesize "${input_probesize}" \
          -max_delay "${input_max_delay}" \
          -fflags nobuffer -flags low_delay "${input_extra_args[@]}" \
          -use_wallclock_as_timestamps 1 \
          "${input_format_args[@]}" -i "${input_url}" \
          -an -c:v copy \
          -muxdelay "${WEBRTC_SIDECAR_OUTPUT_MUXDELAY}" -muxpreload "${WEBRTC_SIDECAR_OUTPUT_MUXPRELOAD}" \
          -flush_packets 1 \
          -f rtsp -rtsp_transport tcp "${rtsp_url}" \
          > >(redact_stream) 2> >(redact_stream >&2) &
      else
        "${FFMPEG_BIN}" \
          -hide_banner -loglevel warning \
          "${transport_args[@]}" \
          -analyzeduration "${input_analyzeduration}" \
          -probesize "${input_probesize}" \
          -max_delay "${input_max_delay}" \
          -fflags nobuffer -flags low_delay "${input_extra_args[@]}" \
          -use_wallclock_as_timestamps 1 \
          "${input_format_args[@]}" -i "${input_url}" \
          -vf "${WEBRTC_SIDECAR_VIDEO_FILTER}" \
          -an -c:v "${WEBRTC_SIDECAR_ENCODER}" -preset "${WEBRTC_SIDECAR_X264_PRESET}" \
          -tune zerolatency "${encoder_extra_args[@]}" -pix_fmt yuv420p -r "${WEBRTC_SIDECAR_TARGET_FPS}" \
          -g "${WEBRTC_SIDECAR_GOP}" -bf 0 \
          -b:v "${WEBRTC_SIDECAR_BITRATE}" -maxrate "${WEBRTC_SIDECAR_BITRATE}" -bufsize "${WEBRTC_SIDECAR_BUFSIZE}" \
          -muxdelay "${WEBRTC_SIDECAR_OUTPUT_MUXDELAY}" -muxpreload "${WEBRTC_SIDECAR_OUTPUT_MUXPRELOAD}" \
          -flush_packets 1 \
          -f rtsp -rtsp_transport tcp "${rtsp_url}" \
          > >(redact_stream) 2> >(redact_stream >&2) &
      fi
      local ffmpeg_pid=$!
      wait_for_candidate_start "${path}" "${ffmpeg_pid}" "${WEBRTC_SIDECAR_CANDIDATE_START_TIMEOUT_S}"
      local start_code=$?
      local code
      if [ "${start_code}" -eq 0 ]; then
        wait "${ffmpeg_pid}"
        code=$?
      elif [ "${start_code}" -eq 1 ]; then
        printf '[webrtc-sidecar] publisher path=%s transport=%s did not become ready within %ss; trying next candidate at %s\n' \
          "${path}" "${candidate_transport}" "${WEBRTC_SIDECAR_CANDIDATE_START_TIMEOUT_S}" "$(date -Is)"
        kill -INT "${ffmpeg_pid}" 2> /dev/null || true
        sleep 0.5
        kill -TERM "${ffmpeg_pid}" 2> /dev/null || true
        wait "${ffmpeg_pid}" 2> /dev/null
        code=124
      else
        wait "${ffmpeg_pid}"
        code=$?
      fi
      set -e
      printf '[webrtc-sidecar] publisher path=%s transport=%s exited status=%s at %s\n' \
        "${path}" "${candidate_transport}" "${code}" "$(date -Is)"
    done < "${candidate_file}"
    if [ "${tried}" -eq 0 ]; then
      printf '[webrtc-sidecar] publisher path=%s has no input candidates in %s\n' "${path}" "${candidate_file}"
    fi
    printf '[webrtc-sidecar] publisher path=%s exhausted candidates; retrying in %ss at %s\n' \
      "${path}" "${WEBRTC_SIDECAR_RESTART_SEC}" "$(date -Is)"
    sleep "${WEBRTC_SIDECAR_RESTART_SEC}"
  done
}

cleanup() {
  local status=$?
  trap - INT TERM EXIT
  if [ "${#PIDS[@]}" -gt 0 ]; then
    log "stopping ${#PIDS[@]} child process(es)"
    local i
    for ((i = ${#PIDS[@]} - 1; i >= 0; i--)); do
      kill -INT "${PIDS[$i]}" 2> /dev/null || true
    done
    sleep 1
    for ((i = ${#PIDS[@]} - 1; i >= 0; i--)); do
      kill -TERM "${PIDS[$i]}" 2> /dev/null || true
    done
    wait 2> /dev/null || true
  fi
  write_status stopped "" 0 || true
  exit "${status}"
}

run_sidecar() {
  require_live_tmux_context
  run_check
  umask 077
  rm -f "${PID_FILE}"
  write_config
  local specs=() spec source view path mediamtx_source candidate_file rtsp_url publisher_log expected_publishers
  read_stream_specs specs
  expected_publishers="$(publisher_stream_count)"
  write_status starting "" "${expected_publishers}"
  log "starting MediaMTX with ${CONFIG_FILE}"
  "${MEDIAMTX_BIN}" "${CONFIG_FILE}" > "${LOG_DIR}/mediamtx.log" 2>&1 &
  local mediamtx_pid=$!
  PIDS+=("${mediamtx_pid}")
  NAMES+=("mediamtx")
  record_process mediamtx "${mediamtx_pid}" "${LOG_DIR}/mediamtx.log"
  write_status running "${mediamtx_pid}" "${expected_publishers}"
  sleep 1
  for spec in "${specs[@]}"; do
    source="$(stream_source "${spec}")"
    view="$(stream_view "${spec}")"
    path="$(stream_path_id "${spec}")"
    mediamtx_source="$(stream_mediamtx_source_value "${source}" "${view}" "${path}")"
    if [ -n "${mediamtx_source}" ]; then
      log "direct-source-${path} source=$(redact_url "${mediamtx_source}") publisher=disabled"
      continue
    fi
    if stream_is_compositor_publisher "${spec}" "${path}"; then
      log "compositor-receiver-${path} source=publisher external=vision_pc_compositor_publisher metrics=${WEBRTC_SIDECAR_COMPOSITOR_METRICS_DIR}/${path}.json"
      continue
    fi
    candidate_file="$(write_input_candidates_file "${source}" "${view}" "${path}")"
    rtsp_url="rtsp://127.0.0.1:${MEDIAMTX_RTSP_PORT}/${path}"
    publisher_log="${LOG_DIR}/publisher-${path}.log"
    publisher_loop "${source}" "${view}" "${path}" "${candidate_file}" "${rtsp_url}" > "${publisher_log}" 2>&1 &
    local publisher_pid=$!
    PIDS+=("${publisher_pid}")
    NAMES+=("publisher-${path}")
    record_process "publisher-${path}" "${publisher_pid}" "${publisher_log}"
    log "publisher-${path} pid=${publisher_pid} log=${publisher_log}"
  done
  log "running. Browser URL example: http://${WEBRTC_SIDECAR_PUBLIC_HOST}:${MEDIAMTX_WEBRTC_PORT}/$(stream_path_id "${specs[0]}")/"
  trap cleanup INT TERM EXIT
  wait -n "${PIDS[@]}"
  local child_status=$?
  log "a child exited status=${child_status}; shutting down sidecar"
  exit "${child_status}"
}

status_from_files() {
  local configured=0 mediamtx_pid="" expected=0 paths="" web_port="${MEDIAMTX_WEBRTC_PORT}" rtsp_port="${MEDIAMTX_RTSP_PORT}" public_host="${WEBRTC_SIDECAR_PUBLIC_HOST}" additional_hosts="${MEDIAMTX_WEBRTC_ADDITIONAL_HOSTS:-}"
  if [ -f "${STATUS_FILE}" ]; then
    configured=1
    # shellcheck disable=SC1090
    source "${STATUS_FILE}"
    mediamtx_pid="${MEDIAMTX_PID:-}"
    expected="${EXPECTED_PUBLISHERS:-0}"
    paths="${STREAM_PATHS:-}"
    web_port="${MEDIAMTX_WEBRTC_PORT:-${web_port}}"
    rtsp_port="${MEDIAMTX_RTSP_PORT:-${rtsp_port}}"
    public_host="${WEBRTC_SIDECAR_PUBLIC_HOST:-${public_host}}"
    additional_hosts="${MEDIAMTX_WEBRTC_ADDITIONAL_HOSTS:-${additional_hosts}}"
  elif [ -f "${CONFIG_FILE}" ]; then
    configured=1
  fi

  local alive_publishers=0 total_publishers=0 name pid log_file mediamtx_alive=false
  if [ -f "${PID_FILE}" ]; then
    while IFS=$'\t' read -r name pid log_file; do
      [ -n "${name:-}" ] || continue
      if [ "${name}" = "mediamtx" ]; then
        alive_pid "${pid}" && mediamtx_alive=true
      elif [[ "${name}" == publisher-* ]]; then
        total_publishers=$((total_publishers + 1))
        alive_pid "${pid}" && alive_publishers=$((alive_publishers + 1))
      fi
    done < "${PID_FILE}"
  fi
  if alive_pid "${mediamtx_pid}"; then
    mediamtx_alive=true
  fi

  local reachable=false
  if [ "${mediamtx_alive}" = true ] && is_executable_cmd "${CURL_BIN}"; then
    if "${CURL_BIN}" -fsS --max-time 1 "http://127.0.0.1:${web_port}/" > /dev/null 2>&1; then
      reachable=true
    elif "${CURL_BIN}" -sS --max-time 1 "http://127.0.0.1:${web_port}/" > /dev/null 2>&1; then
      reachable=true
    fi
  fi

  local state="not_configured" exit_code=1
  if [ "${configured}" -eq 1 ]; then
    state="configured"
    if [ "${reachable}" != true ]; then
      state="mediamtx_unreachable"
    elif [ "${expected}" -eq 0 ]; then
      state="receiver_ready"
      exit_code=0
    elif [ "${expected}" -gt 0 ] && [ "${alive_publishers}" -lt "${expected}" ]; then
      state="publisher_missing"
    elif [ "${alive_publishers}" -gt 0 ]; then
      state="publisher_alive"
      exit_code=0
    fi
  fi

  cat << STATUS
SmartFactory Vision WebRTC sidecar status
  state: ${state}
  run_dir: ${RUN_DIR}
  config_file: ${CONFIG_FILE}
  mediamtx_alive: ${mediamtx_alive}
  mediamtx_http_reachable: ${reachable}
  expected_publishers: ${expected}
  alive_publishers: ${alive_publishers}/${total_publishers}
  rtsp_port: ${rtsp_port}
  webrtc_port: ${web_port}
  webrtc_additional_hosts: ${additional_hosts:-<auto-interface-only>}
  paths: ${paths:-<unknown>}
STATUS
  if [ -n "${paths:-}" ]; then
    local IFS=',' path
    for path in ${paths}; do
      printf '  browser: http://%s:%s/%s/\n' "${public_host}" "${web_port}" "${path}"
      printf '  whep: http://%s:%s/%s/whep\n' "${public_host}" "${web_port}" "${path}"
    done
  fi
  return "${exit_code}"
}

smoke_readability() {
  status_from_files
  if ! is_executable_cmd "${FFPROBE_BIN}"; then
    echo "ERROR: ffprobe not found: ${FFPROBE_BIN}" >&2
    return 1
  fi
  local paths=""
  if [ -f "${STATUS_FILE}" ]; then
    # shellcheck disable=SC1090
    source "${STATUS_FILE}"
    paths="${STREAM_PATHS:-}"
  fi
  local first_path="${paths%%,*}"
  if [ -z "${first_path}" ]; then
    echo "ERROR: no sidecar path recorded" >&2
    return 1
  fi
  log "ffprobe RTSP readability: rtsp://127.0.0.1:${MEDIAMTX_RTSP_PORT}/${first_path}"
  "${FFPROBE_BIN}" -v error -rtsp_transport tcp -timeout 3000000 \
    -select_streams v:0 -show_entries stream=codec_name -of default=noprint_wrappers=1 \
    "rtsp://127.0.0.1:${MEDIAMTX_RTSP_PORT}/${first_path}" > /dev/null
  log "smoke ok: ${first_path} is readable via RTSP; WebRTC browser/WHEP endpoint is advertised by MediaMTX"
}

cmd="${1:-run}"
case "${cmd}" in
  run) run_sidecar ;;
  --check | check) run_check ;;
  --print-config | print-config) print_config ;;
  --status | status) status_from_files ;;
  --smoke | smoke) smoke_readability ;;
  --help | -h | help) usage ;;
  *)
    echo "ERROR: unknown command: ${cmd}" >&2
    usage >&2
    exit 2
    ;;
esac
