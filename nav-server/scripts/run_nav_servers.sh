#!/usr/bin/env bash
# Start one Nav server API process per enabled robot in config/robots.json.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
ROS_LOCALHOST_ONLY="${ROS_LOCALHOST_ONLY:-0}"
ROBOTS_CONFIG_PATH="${ROBOTS_CONFIG_PATH:-$ROOT/config/robots.json}"
VALIDATOR="${VALIDATOR:-$SCRIPT_DIR/validate_robot_domains.py}"
PLAN_HELPER="${PLAN_HELPER:-$SCRIPT_DIR/nav_bringup_plan.py}"
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

Environment:
  ROS_SETUP           ROS setup path. Default: /opt/ros/jazzy/setup.bash
  ROS_LOCALHOST_ONLY  ROS localhost setting. Default: 0
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
  require_executable "$PYTHON_BIN" "Python"

  "$PYTHON_BIN" "$VALIDATOR" --config "$ROBOTS_CONFIG_PATH" --bridge-dir "$ROOT/config/domain_bridge"
  build_plan --print-plan >"$plan_file"

  # shellcheck source=/dev/null
  set +u
  source "$ROS_SETUP"
  set -u
  export ROS_LOCALHOST_ONLY

  if ! command -v ros2 >/dev/null 2>&1; then
    echo "[nav_servers] ros2 command not found after sourcing $ROS_SETUP" >&2
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
  local domain_id="$2"
  local port="$3"
  local map_yaml="$4"

  echo "[nav_servers] starting ${robot_id}: ROS_DOMAIN_ID=${domain_id}, port=${port}, map=${map_yaml}"
  (
    cd "$ROOT"
    ROBOT_ID="$robot_id" \
    ROS_DOMAIN_ID="$domain_id" \
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
  pids+=("$!")
}

while (($# > 0)); do
  case "$1" in
    --check)
      mode="check"
      ;;
    --print-plan)
      mode="print-plan"
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[nav_servers] unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

trap cleanup EXIT INT TERM

require_file "$ROBOTS_CONFIG_PATH" "robots config"
require_file "$PLAN_HELPER" "bringup plan helper"
require_executable "$PYTHON_BIN" "Python"

if [[ "$mode" == "print-plan" ]]; then
  build_plan --print-plan
  exit 0
fi

plan_file="$(mktemp)"
plan_tsv="$(mktemp)"
preflight

if [[ "$mode" == "check" ]]; then
  echo "[nav_servers] preflight OK"
  exit 0
fi

build_plan --tsv >"$plan_tsv"
while IFS=$'\t' read -r robot_id domain_id port map_yaml; do
  [[ -z "$robot_id" ]] && continue
  start_nav_server "$robot_id" "$domain_id" "$port" "$map_yaml"
done <"$plan_tsv"

echo "[nav_servers] up from $ROBOTS_CONFIG_PATH. Ctrl+C to stop."
wait
