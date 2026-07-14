#!/usr/bin/env bash
# Shared, source-only helpers for SmartFactory Vision bundle entrypoint scripts.
# Keep this file side-effect free: no exports, no process starts, no filesystem mutation.

sf_repo_root_from_script() {
  local script_path="$1"
  local dir
  dir="$(cd "$(dirname "${script_path}")" && pwd)"
  while [ "${dir}" != "/" ]; do
    # Standalone deploy root: ai-server/app + ai-server/scripts.
    if [ -d "${dir}/app" ] && [ -d "${dir}/scripts" ]; then
      printf '%s\n' "${dir}"
      return 0
    fi
    dir="$(dirname "${dir}")"
  done
  return 1
}

sf_default_model_extra_pythonpath() {
  # The deploy package has no host-specific model Python environment default.
  # Set AI_SERVER_EXTRA_PYTHONPATH explicitly only for a local model env.
  printf '%s\n' ''
}

sf_is_site_lan_ipv4() {
  local ip="${1:-}"
  local prefix="${SMARTFACTORY_LAN_IPV4_PREFIX:-192.168.30.}"
  [[ -n "${ip}" && "${ip}" == "${prefix}"* ]]
}

sf_route_source_ip() {
  local target="${1:-}"
  [ -n "${target}" ] || return 1
  command -v ip > /dev/null 2>&1 || return 1
  ip route get "${target}" 2> /dev/null | awk '
    {
      for (i = 1; i <= NF; i++) {
        if ($i == "src" && (i + 1) <= NF) {
          print $(i + 1)
          exit
        }
      }
    }'
}

sf_lan_ip() {
  local route_target="${1:-}"
  local routed=""
  if [ -n "${route_target}" ]; then
    routed="$(sf_route_source_ip "${route_target}" || true)"
    if sf_is_site_lan_ipv4 "${routed}"; then
      printf '%s\n' "${routed}"
      return 0
    fi
  fi
  local candidate
  candidate="$(hostname -I 2> /dev/null | tr ' ' '\n' | grep -F "${SMARTFACTORY_LAN_IPV4_PREFIX:-192.168.30.}" | head -n1 || true)"
  [ -n "${candidate}" ] || return 1
  printf '%s\n' "${candidate}"
}

sf_ros_double() {
  local value="${1:-}"
  if [[ "${value}" =~ ^[+-]?[0-9]+$ ]]; then
    printf '%s.0\n' "${value}"
  else
    printf '%s\n' "${value}"
  fi
}

sf_env_truthy() {
  case "${1:-}" in
    1 | true | TRUE | yes | YES | y | Y | on | ON) return 0 ;;
    *) return 1 ;;
  esac
}

sf_load_ros_network_env() {
  local root_dir="${1:?root_dir is required}"
  local default_file="${root_dir}/config/ros/fastdds-smartfactory.env"
  local env_file="${SF_VISION_ROS_ENV_FILE:-}"
  local loaded=""

  if ! sf_env_truthy "${SF_VISION_ROS_ENV_ENABLED:-true}"; then
    export SF_VISION_ROS_ENV_FILE_LOADED="<disabled>"
    return 0
  fi

  if [ -n "${env_file}" ]; then
    case "${env_file}" in
      /*) ;;
      *) env_file="${root_dir}/${env_file}" ;;
    esac
    if [ ! -f "${env_file}" ]; then
      echo "ERROR: ROS network env file not found: ${env_file}" >&2
      return 2
    fi
    # shellcheck disable=SC1090
    source "${env_file}"
    loaded="${env_file}"
  fi

  # Load the deploy default after an optional operator file so local peer
  # variables from that file can shape the generated FastDDS defaults.
  if sf_env_truthy "${SF_VISION_DEFAULT_ROS_ENV_ENABLED:-true}" &&
    [ -f "${default_file}" ] &&
    [ "${env_file:-}" != "${default_file}" ]; then
    # shellcheck disable=SC1090
    source "${default_file}"
    loaded="${loaded:+${loaded};}${default_file}"
  fi

  export SF_VISION_ROS_ENV_FILE_LOADED="${loaded}"
}

sf_validate_vision_model_source_config_json() {
  local payload="${1:-}"
  [ -n "${payload}" ] || return 0
  VISION_MODEL_SOURCE_CONFIG_JSON="${payload}" python3 - << 'PY'
import json
import os
from pathlib import Path

payload = os.environ.get("VISION_MODEL_SOURCE_CONFIG_JSON", "").strip()
try:
    config = json.loads(payload) if payload else {}
except json.JSONDecodeError as exc:
    raise SystemExit(f"ERROR: VISION_MODEL_SOURCE_CONFIG_JSON is invalid JSON: {exc}") from exc
if not isinstance(config, dict):
    raise SystemExit("ERROR: VISION_MODEL_SOURCE_CONFIG_JSON must be a JSON object")

def falsey(value):
    return value is False or (isinstance(value, str) and value.strip().lower() in {"0", "false", "no", "off", "disabled"})

def positive_int(value, field, source):
    if isinstance(value, bool):
        raise SystemExit(f"ERROR: {field} for {source!r} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"ERROR: {field} for {source!r} must be a positive integer") from exc
    if parsed <= 0:
        raise SystemExit(f"ERROR: {field} for {source!r} must be a positive integer")

def unit_float(value, field, source):
    if isinstance(value, bool):
        raise SystemExit(f"ERROR: {field} for {source!r} must be a number between 0 and 1")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise SystemExit(f"ERROR: {field} for {source!r} must be a number between 0 and 1") from exc
    if not 0.0 <= parsed <= 1.0:
        raise SystemExit(f"ERROR: {field} for {source!r} must be a number between 0 and 1")

for source, item in config.items():
    if not isinstance(source, str) or not source.strip():
        raise SystemExit("ERROR: source model config key must be a non-empty string")
    if not isinstance(item, dict):
        raise SystemExit(f"ERROR: source model config for {source!r} must be an object")
    if falsey(item.get("enabled", True)):
        continue
    for field in ("model_path", "path"):
        if field in item and not isinstance(item[field], str):
            raise SystemExit(f"ERROR: {field} for {source!r} must be a string")
    model_path = str(item.get("model_path") or item.get("path") or "").strip()
    if model_path and not Path(model_path).is_file():
        raise SystemExit(f"ERROR: source model path for {source!r} does not exist: {model_path}")
    task = item.get("task")
    if task is not None and str(task) not in {"segment", "detect"}:
        raise SystemExit(f"ERROR: task for {source!r} must be 'segment' or 'detect'")
    for field in ("image_size", "imgsz"):
        if field in item:
            positive_int(item[field], field, source)
    for field in ("confidence", "conf", "iou"):
        if field in item:
            unit_float(item[field], field, source)
    if "class_map" in item and not isinstance(item["class_map"], dict):
        raise SystemExit(f"ERROR: class_map for {source!r} must be an object")
    if "class_map_json" in item:
        if not isinstance(item["class_map_json"], str):
            raise SystemExit(f"ERROR: class_map_json for {source!r} must be a JSON object string")
        try:
            parsed_class_map = json.loads(item["class_map_json"])
        except json.JSONDecodeError as exc:
            raise SystemExit(f"ERROR: class_map_json for {source!r} is invalid JSON: {exc}") from exc
        if not isinstance(parsed_class_map, dict):
            raise SystemExit(f"ERROR: class_map_json for {source!r} must be a JSON object string")
print("source model config check: ok")
PY
}
