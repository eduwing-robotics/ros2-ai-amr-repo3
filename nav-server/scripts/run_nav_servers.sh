#!/usr/bin/env bash
# Internal worker for sf_nav.sh. Start one API process per selected robot.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
ROS_LOCALHOST_ONLY="${ROS_LOCALHOST_ONLY:-0}"
RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
ROBOTS_CONFIG_PATH="${ROBOTS_CONFIG_PATH:-$ROOT/config/robots.json}"
VALIDATOR="${VALIDATOR:-$SCRIPT_DIR/validate_robot_domains.py}"
PLAN_HELPER="${PLAN_HELPER:-$SCRIPT_DIR/nav_bringup_plan.py}"
RESOLVED_PROFILE_PATH="${SF_NAV_RESOLVED_PROFILE_PATH:-}"
CHILD_STATE_PATH="${SF_NAV_CHILD_STATE_PATH:-}"
HOST="${HOST:-0.0.0.0}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
DRY_RUN_MISSION="${DRY_RUN_MISSION:-0}"
DRY_RUN_STEP_DELAY_SEC="${DRY_RUN_STEP_DELAY_SEC:-0.2}"
# 2026-07-04 실측: 정렬 완료(마커 65px) 지점 기준. 출고2는 36.5cm 적정, 출고1은 34.5cm까지 후퇴 필요 → 안전값 34.5cm
FORK_INSERT_DISTANCE_M="${FORK_INSERT_DISTANCE_M:-0.345}"
FORK_INSERT_MAX_DURATION_SEC="${FORK_INSERT_MAX_DURATION_SEC:-15.0}"
NAV_GOAL_XY_TOLERANCE_M="${NAV_GOAL_XY_TOLERANCE_M:-0.02}"
NAV_GOAL_YAW_TOLERANCE_RAD="${NAV_GOAL_YAW_TOLERANCE_RAD:-0.035}"
NAV_APPROACH_XY_TOLERANCE_M="${NAV_APPROACH_XY_TOLERANCE_M:-0.02}"
NAV_APPROACH_YAW_TOLERANCE_RAD="${NAV_APPROACH_YAW_TOLERANCE_RAD:-0.035}"
NAV_APPROACH_SOFT_XY_TOLERANCE_M="${NAV_APPROACH_SOFT_XY_TOLERANCE_M:-0.07}"
NAV_APPROACH_SOFT_YAW_TOLERANCE_RAD="${NAV_APPROACH_SOFT_YAW_TOLERANCE_RAD:-0.25}"
RECORD_MAX_XY_ERROR_M="${RECORD_MAX_XY_ERROR_M:-0.02}"
ARUCO_DOCK_CENTER_TOLERANCE_NORM="${ARUCO_DOCK_CENTER_TOLERANCE_NORM:-0.03}"

mode="run"
pids=()
plan_file=""
plan_tsv=""

usage() {
  cat <<'EOF'
Usage:
  scripts/run_nav_servers.sh [--check|--print-plan]

Modes:
  --check       Run all preflight checks and exit without starting processes.
  --print-plan  Print deterministic JSON plan generated from robots.json and exit.

Process start is owned by sf_nav.sh. This file exposes read-only CLI modes only.

Environment:
  ROS_SETUP           ROS setup path. Default: /opt/ros/jazzy/setup.bash
  ROS_LOCALHOST_ONLY  ROS localhost setting. Default: 0
  RMW_IMPLEMENTATION  Nav PC middleware. Default: rmw_cyclonedds_cpp
  ROBOTS_CONFIG_PATH  robots.json path. Default: config/robots.json
  HOST                Bind host. Default: 0.0.0.0
  PYTHON_BIN          Python executable. Default: .venv/bin/python
  DRY_RUN_MISSION     1 to accept missions without moving robots. Default: 0
  DRY_RUN_STEP_DELAY_SEC  Delay used by dry-run missions. Default: 0.2

Robot id, ROS domain, API port, and active map are read from enabled entries in ROBOTS_CONFIG_PATH.
EOF
}

cleanup() {
  if ((${#pids[@]} > 0)); then
    echo
    echo "[nav_servers] stopping child processes..."
    kill "${pids[@]}" 2>/dev/null || true
    wait 2>/dev/null || true
  fi
  if [[ -n "$plan_file" && -f "$plan_file" ]]; then
    rm -f "$plan_file"
  fi
  if [[ -n "$plan_tsv" && -f "$plan_tsv" ]]; then
    rm -f "$plan_tsv"
  fi
  return 0
}

require_file() {
  local path="$1"
  local label="$2"
  if [[ ! -f "$path" ]]; then
    echo "[nav_servers] missing ${label}: $path" >&2
    exit 1
  fi
}

require_executable() {
  local path="$1"
  local label="$2"
  if [[ "$path" == */* ]]; then
    if [[ ! -x "$path" ]]; then
      echo "[nav_servers] missing executable ${label}: $path" >&2
      exit 1
    fi
  elif ! command -v "$path" >/dev/null 2>&1; then
    echo "[nav_servers] missing executable ${label}: $path" >&2
    exit 1
  fi
}

build_plan() {
  if [[ -n "$RESOLVED_PROFILE_PATH" ]]; then
    if [[ "${1:-}" == "--tsv" ]]; then
      "$PYTHON_BIN" - "$RESOLVED_PROFILE_PATH" <<'PY'
import json, sys
for robot in json.load(open(sys.argv[1], encoding="utf-8"))["robots"]:
    print("\t".join(str(robot[key]) for key in ("robot_id", "ros_domain_id", "nav_local_domain_id", "api_port", "active_map_yaml")))
PY
    else
      cat "$RESOLVED_PROFILE_PATH"
    fi
    return
  fi
  "$PYTHON_BIN" "$PLAN_HELPER" \
    --config "$ROBOTS_CONFIG_PATH" \
    --host "$HOST" \
    --python-bin "$PYTHON_BIN" \
    "$@"
}

preflight() {
  require_file "$ROS_SETUP" "ROS setup"
  require_file "$ROBOTS_CONFIG_PATH" "robots config"
  require_file "$VALIDATOR" "robot domain validator"
  require_file "$PLAN_HELPER" "bringup plan helper"
  [[ -z "$RESOLVED_PROFILE_PATH" ]] || require_file "$RESOLVED_PROFILE_PATH" "resolved runtime profile"
  require_executable "$PYTHON_BIN" "Python"

  # A resolved profile narrows selection; it never replaces validation of the
  # canonical robots/domain-bridge facts from which it was resolved.
  "$PYTHON_BIN" "$VALIDATOR" --config "$ROBOTS_CONFIG_PATH" --bridge-dir "$ROOT/config/domain_bridge"
  build_plan --print-plan >"$plan_file"

  # shellcheck source=/dev/null
  set +u
  source "$ROS_SETUP"
  set -u
  export ROS_LOCALHOST_ONLY
  export RMW_IMPLEMENTATION

  if ! command -v ros2 >/dev/null 2>&1; then
    echo "[nav_servers] ros2 command not found after sourcing $ROS_SETUP" >&2
    exit 1
  fi
  if ! ros2 pkg prefix "$RMW_IMPLEMENTATION" >/dev/null 2>&1; then
    echo "[nav_servers] missing ROS middleware package: $RMW_IMPLEMENTATION" >&2
    exit 1
  fi

  if ! "$PYTHON_BIN" -c 'import uvicorn; import nav_app.app' >/dev/null 2>&1; then
    echo "[nav_servers] Python import failed: uvicorn and/or nav_app.app" >&2
    echo "[nav_servers] expected Python: $PYTHON_BIN" >&2
    exit 1
  fi
}

start_nav_server() {
  local robot_id="$1"
  local hardware_domain_id="$2"
  local local_domain_id="$3"
  local port="$4"
  local map_yaml="$5"
  local child_pid

  echo "[nav_servers] starting ${robot_id}: hardware_domain=${hardware_domain_id}, local_domain=${local_domain_id}, port=${port}, map=${map_yaml}"
  (
    cd "$ROOT"
    export ROS_DOMAIN_ID="$local_domain_id"
    export NAV_LOCAL_ROS_DOMAIN_ID="$local_domain_id"
    if [[ "$local_domain_id" != "$hardware_domain_id" ]]; then
      # shellcheck source=configure_cyclonedds_local_domain.sh
      source "$SCRIPT_DIR/configure_cyclonedds_local_domain.sh"
    else
      # Backward-compatible direct mode for profiles without a local bridge.
      # shellcheck source=configure_cyclonedds_lan.sh
      source "$SCRIPT_DIR/configure_cyclonedds_lan.sh"
    fi
    ROBOT_ID="$robot_id" \
    ROS_DOMAIN_ID="$local_domain_id" \
    NAV_LOCAL_ROS_DOMAIN_ID="$local_domain_id" \
    ACTIVE_MAP_YAML="$map_yaml" \
    ROBOTS_CONFIG_PATH="$ROBOTS_CONFIG_PATH" \
    ROS_LOCALHOST_ONLY="$ROS_LOCALHOST_ONLY" \
    DRY_RUN_MISSION="$DRY_RUN_MISSION" \
    DRY_RUN_STEP_DELAY_SEC="$DRY_RUN_STEP_DELAY_SEC" \
    FORK_INSERT_DISTANCE_M="$FORK_INSERT_DISTANCE_M" \
    FORK_INSERT_MAX_DURATION_SEC="$FORK_INSERT_MAX_DURATION_SEC" \
    NAV_GOAL_XY_TOLERANCE_M="$NAV_GOAL_XY_TOLERANCE_M" \
    NAV_GOAL_YAW_TOLERANCE_RAD="$NAV_GOAL_YAW_TOLERANCE_RAD" \
    NAV_APPROACH_XY_TOLERANCE_M="$NAV_APPROACH_XY_TOLERANCE_M" \
    NAV_APPROACH_YAW_TOLERANCE_RAD="$NAV_APPROACH_YAW_TOLERANCE_RAD" \
    NAV_APPROACH_SOFT_XY_TOLERANCE_M="$NAV_APPROACH_SOFT_XY_TOLERANCE_M" \
    NAV_APPROACH_SOFT_YAW_TOLERANCE_RAD="$NAV_APPROACH_SOFT_YAW_TOLERANCE_RAD" \
    RECORD_MAX_XY_ERROR_M="$RECORD_MAX_XY_ERROR_M" \
    ARUCO_DOCK_CENTER_TOLERANCE_NORM="$ARUCO_DOCK_CENTER_TOLERANCE_NORM" \
    "$PYTHON_BIN" -m uvicorn nav_app.app:app --host "$HOST" --port "$port"
  ) &
  child_pid=$!
  pids+=("$child_pid")
  if [[ -n "$CHILD_STATE_PATH" ]]; then
    "$PYTHON_BIN" - "$CHILD_STATE_PATH" "$robot_id" "$port" "$child_pid" <<'PY'
import json
import os
import sys
import tempfile
from pathlib import Path

path = Path(sys.argv[1])
path.parent.mkdir(parents=True, exist_ok=True)
data = {"schema_version": 1, "children": []}
if path.is_file():
    data = json.loads(path.read_text(encoding="utf-8"))
data["children"].append({"robot_id": sys.argv[2], "api_port": int(sys.argv[3]), "pid": int(sys.argv[4])})
fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
try:
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(data, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
finally:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
PY
  fi
}

sf_nav_supervise() {
  [[ -n "$RESOLVED_PROFILE_PATH" && -n "$CHILD_STATE_PATH" ]] || {
    echo "[nav_servers] sf_nav supervisor context is incomplete" >&2
    return 2
  }
  trap cleanup EXIT INT TERM
  plan_file="$(mktemp)"
  plan_tsv="$(mktemp)"
  preflight
  build_plan --tsv >"$plan_tsv"
  while IFS=$'\t' read -r robot_id hardware_domain_id local_domain_id port map_yaml; do
    [[ -z "$robot_id" ]] && continue
    start_nav_server "$robot_id" "$hardware_domain_id" "$local_domain_id" "$port" "$map_yaml"
  done <"$plan_tsv"
  echo "[nav_servers] up from $ROBOTS_CONFIG_PATH."
  wait
}

main() {
  while (($# > 0)); do
    case "$1" in
      --check) mode="check" ;;
      --print-plan) mode="print-plan" ;;
      --resolved-profile)
        RESOLVED_PROFILE_PATH="${2:?--resolved-profile requires a path}"
        shift
        ;;
      -h|--help) usage; return 0 ;;
      *) echo "[nav_servers] unknown argument: $1" >&2; usage >&2; return 2 ;;
    esac
    shift
  done

  if [[ "$mode" == run ]]; then
    echo "[nav_servers] process start is owned by sf_nav.sh; use sf_nav.sh up" >&2
    return 2
  fi
  require_file "$ROBOTS_CONFIG_PATH" "robots config"
  require_file "$PLAN_HELPER" "bringup plan helper"
  require_executable "$PYTHON_BIN" "Python"
  if [[ "$mode" == print-plan ]]; then
    build_plan --print-plan
    return
  fi
  trap cleanup EXIT INT TERM
  plan_file="$(mktemp)"
  plan_tsv="$(mktemp)"
  preflight
  echo "[nav_servers] preflight OK"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  main "$@"
fi
