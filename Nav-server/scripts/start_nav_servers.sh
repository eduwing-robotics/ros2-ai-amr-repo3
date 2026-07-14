#!/usr/bin/env bash
#
# Operator wrapper for starting/stopping the two Movement/Nav API servers.
#
# Default topology:
#   tb3_burger_01 -> ROS_DOMAIN_ID=2 -> http://0.0.0.0:8001
#   tb3_burger_02 -> ROS_DOMAIN_ID=5 -> http://0.0.0.0:8002
#
# This wraps scripts/run_nav_servers.sh with logs, pid tracking, and basic
# port-conflict checks. Use foreground when you want the original live logs.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
RUN_SCRIPT="$SCRIPT_DIR/run_nav_servers.sh"
STATUS_SCRIPT="$SCRIPT_DIR/nav_server_status.sh"
LOG_DIR="${LOG_DIR:-$ROOT/logs}"
LOG_FILE="${LOG_FILE:-$LOG_DIR/nav_servers.log}"
PID_FILE="${PID_FILE:-$LOG_DIR/nav_servers.pid}"
TB3_1_PORT="${TB3_1_PORT:-8001}"
TB3_2_PORT="${TB3_2_PORT:-8002}"
ONLY_ROBOT="${ONLY_ROBOT:-both}"
HOST="${HOST:-0.0.0.0}"
DRY_RUN_MISSION="${DRY_RUN_MISSION:-0}"
MAIN_API_BASE="${MAIN_API_BASE:-http://192.168.30.9:8088/api/v1}"

usage() {
  cat <<'EOF'
Usage:
  scripts/start_nav_servers.sh start       # background start, real robot mode
  scripts/start_nav_servers.sh dry-run     # background start with DRY_RUN_MISSION=1
  scripts/start_nav_servers.sh foreground  # run in foreground, real robot mode
  scripts/start_nav_servers.sh status      # show HTTP/process/ROS status
  scripts/start_nav_servers.sh stop        # stop tracked wrapper and nav_server children
  scripts/start_nav_servers.sh restart     # stop then start

Environment overrides:
  TB3_1_PORT=8001
  TB3_2_PORT=8002
  ONLY_ROBOT=both|tb3_1|tb3_2
  HOST=0.0.0.0
  MAIN_API_BASE=http://127.0.0.1:8088/api/v1
  LOG_DIR=/home/lucas/slam_nav_ws/logs
  DRY_RUN_MISSION=1

Examples:
  scripts/start_nav_servers.sh start
  ONLY_ROBOT=tb3_1 scripts/start_nav_servers.sh foreground
  scripts/start_nav_servers.sh status
  ONLY_ROBOT=tb3_2 scripts/start_nav_servers.sh stop
  DRY_RUN_MISSION=1 scripts/start_nav_servers.sh start
EOF
}

ports_for_only_robot() {
  case "$ONLY_ROBOT" in
    both|"") echo "$TB3_1_PORT" "$TB3_2_PORT" ;;
    tb3_1|tb3_burger_01) echo "$TB3_1_PORT" ;;
    tb3_2|tb3_burger_02) echo "$TB3_2_PORT" ;;
    *)
      echo "[nav_start] unknown ONLY_ROBOT=$ONLY_ROBOT" >&2
      exit 2
      ;;
  esac
}

pid_file_for_only_robot() {
  case "$ONLY_ROBOT" in
    both|"") echo "$LOG_DIR/nav_servers.pid" ;;
    tb3_1|tb3_burger_01) echo "$LOG_DIR/nav_servers_tb3_1.pid" ;;
    tb3_2|tb3_burger_02) echo "$LOG_DIR/nav_servers_tb3_2.pid" ;;
    *) echo "$LOG_DIR/nav_servers.pid" ;;
  esac
}

log_file_for_only_robot() {
  case "$ONLY_ROBOT" in
    both|"") echo "$LOG_DIR/nav_servers.log" ;;
    tb3_1|tb3_burger_01) echo "$LOG_DIR/nav_servers_tb3_1.log" ;;
    tb3_2|tb3_burger_02) echo "$LOG_DIR/nav_servers_tb3_2.log" ;;
    *) echo "$LOG_DIR/nav_servers.log" ;;
  esac
}

tracked_pid_alive() {
  [[ -f "$PID_FILE" ]] || return 1
  local pid
  pid="$(cat "$PID_FILE" 2>/dev/null || true)"
  [[ -n "$pid" ]] || return 1
  kill -0 "$pid" 2>/dev/null
}

port_owner() {
  local port="$1"
  ss -ltnp 2>/dev/null | awk -v needle=":${port}" '$4 ~ needle { print; found=1 } END { exit found ? 0 : 1 }'
}

apply_only_robot_paths() {
  PID_FILE="$(pid_file_for_only_robot)"
  LOG_FILE="$(log_file_for_only_robot)"
}

assert_ports_free() {
  local busy=0
  local port
  for port in $(ports_for_only_robot); do
    if owner="$(port_owner "$port")"; then
      echo "[nav_start] port ${port} is already in use:" >&2
      echo "$owner" | sed 's/^/  /' >&2
      busy=1
    fi
  done
  if [[ "$busy" == "1" ]]; then
    echo "[nav_start] stop the existing server first: ONLY_ROBOT=$ONLY_ROBOT scripts/start_nav_servers.sh stop" >&2
    exit 1
  fi
}

start_background() {
  apply_only_robot_paths
  mkdir -p "$LOG_DIR"
  if tracked_pid_alive; then
    echo "[nav_start] already running with wrapper pid $(cat "$PID_FILE") (ONLY_ROBOT=$ONLY_ROBOT)"
    "$0" status || true
    return 0
  fi
  rm -f "$PID_FILE"
  assert_ports_free
  echo "[nav_start] starting Nav servers in background (ONLY_ROBOT=$ONLY_ROBOT)"
  echo "[nav_start] log: $LOG_FILE"
  setsid env HOST="$HOST" TB3_1_PORT="$TB3_1_PORT" TB3_2_PORT="$TB3_2_PORT" ONLY_ROBOT="$ONLY_ROBOT" MAIN_API_BASE="$MAIN_API_BASE" DRY_RUN_MISSION="$DRY_RUN_MISSION" \
    bash -c 'cd "$0" && exec "$1"' "$ROOT" "$RUN_SCRIPT" >"$LOG_FILE" 2>&1 < /dev/null &
  local pid="$!"
  echo "$pid" >"$PID_FILE"
  sleep 2
  if ! kill -0 "$pid" 2>/dev/null; then
    echo "[nav_start] failed to start. Last log lines:" >&2
    tail -80 "$LOG_FILE" >&2 || true
    rm -f "$PID_FILE"
    exit 1
  fi
  echo "[nav_start] started wrapper pid $pid"
  "$0" status || true
}

start_foreground() {
  apply_only_robot_paths
  assert_ports_free
  echo "[nav_start] starting Nav servers in foreground (ONLY_ROBOT=$ONLY_ROBOT). Ctrl+C stops this robot's API."
  cd "$ROOT"
  exec env HOST="$HOST" TB3_1_PORT="$TB3_1_PORT" TB3_2_PORT="$TB3_2_PORT" ONLY_ROBOT="$ONLY_ROBOT" MAIN_API_BASE="$MAIN_API_BASE" DRY_RUN_MISSION="$DRY_RUN_MISSION" "$RUN_SCRIPT"
}

stop_servers() {
  apply_only_robot_paths
  local stopped=0
  if tracked_pid_alive; then
    local pid
    pid="$(cat "$PID_FILE")"
    echo "[nav_start] stopping wrapper pid $pid (ONLY_ROBOT=$ONLY_ROBOT)"
    kill "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
    stopped=1
  fi
  rm -f "$PID_FILE"

  # Kill only the uvicorn(s) for the selected port(s).
  local port children
  for port in $(ports_for_only_robot); do
    children="$(pgrep -f "uvicorn nav_server:app --host .* --port ${port}" || true)"
    if [[ -z "$children" ]]; then
      # Fallback: match port anywhere in the uvicorn cmdline
      children="$(pgrep -f "uvicorn nav_server:app.*--port ${port}" || true)"
    fi
    if [[ -n "$children" ]]; then
      echo "[nav_start] stopping nav_server on :${port}: $children"
      kill $children 2>/dev/null || true
      stopped=1
    fi
  done

  if [[ "$stopped" == "0" ]]; then
    echo "[nav_start] no tracked Nav server process found (ONLY_ROBOT=$ONLY_ROBOT)"
  else
    sleep 1
    echo "[nav_start] stopped (ONLY_ROBOT=$ONLY_ROBOT)"
  fi
}

show_status() {
  apply_only_robot_paths
  if [[ -x "$STATUS_SCRIPT" ]]; then
    "$STATUS_SCRIPT"
  else
    echo "[nav_start] missing status script: $STATUS_SCRIPT" >&2
    exit 1
  fi
  if [[ -f "$LOG_FILE" ]]; then
    echo
    echo "== Last log lines ($LOG_FILE) =="
    tail -30 "$LOG_FILE" || true
  fi
}

cmd="${1:-start}"
case "$cmd" in
  start)
    start_background
    ;;
  dry-run)
    DRY_RUN_MISSION=1
    start_background
    ;;
  foreground)
    start_foreground
    ;;
  status)
    show_status
    ;;
  stop)
    stop_servers
    ;;
  restart)
    stop_servers
    start_background
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    echo "[nav_start] unknown command: $cmd" >&2
    usage >&2
    exit 2
    ;;
esac
