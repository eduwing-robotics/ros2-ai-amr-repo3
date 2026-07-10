#!/usr/bin/env bash
#
# Replay LMS task 206 — tb3_2 inbound slot 2 (입고2)
# Captured from live run 2026-07-03.
#
# Usage:
#   scripts/scenarios/replay_task206_inbound2_tb3_2.sh
#   NAV_BASE=http://127.0.0.1:8002 DRY_RUN=1 scripts/scenarios/replay_task206_inbound2_tb3_2.sh
#   STEP=2 scripts/scenarios/replay_task206_inbound2_tb3_2.sh   # move only
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

NAV_BASE="${NAV_BASE:-http://127.0.0.1:8002}"
TASK_ID="${TASK_ID:-206}"
ROBOT_ID="${ROBOT_ID:-tb3_2}"
DRY_RUN="${DRY_RUN:-0}"
STEP="${STEP:-all}"
POLL_SEC="${POLL_SEC:-2}"
POLL_MAX="${POLL_MAX:-180}"
TS="$(date -u +%Y%m%dT%H%M%S)"
CALLBACK_URL="${CALLBACK_URL:-http://smartfactory-main.local:8088/api/v1/movement/command-events}"

CMD_LEAVE="task-${TASK_ID}-${ROBOT_ID}-leave_dock-${TS}"
CMD_MOVE="task-${TASK_ID}-${ROBOT_ID}-move_inbound2-${TS}"
CMD_DOCK="task-${TASK_ID}-${ROBOT_ID}-dock_inbound2-${TS}"

# Observed move goal from 2026-07-03 log (LMS direct x/y)
MOVE_X="${MOVE_X:--0.050}"
MOVE_Y="${MOVE_Y:-0.079}"
MOVE_YAW="${MOVE_YAW:--1.57}"

usage() {
  cat <<EOF
Replay LMS task ${TASK_ID} inbound2 on ${ROBOT_ID}

  NAV_BASE=${NAV_BASE}
  DRY_RUN=${DRY_RUN}  (1 = API only, robot does not move)
  STEP=all|1|2|3     (leave_dock | move_to_point | dock_transfer)

Preflight:
  scripts/start_nav_servers.sh start
  Nav2 + 2D Pose Estimate on robot2_map
  For step 3: scripts/run_pi_camera_aruco.sh (ArUco detector)
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

post_command() {
  local cmd_id="$1"
  local kind="$2"
  local params_json="$3"
  local dry_run_json="false"
  if [[ "$DRY_RUN" == "1" ]]; then
    dry_run_json="true"
  fi

  local payload
  payload="$(cat <<JSON
{
  "command_id": "${cmd_id}",
  "task_id": ${TASK_ID},
  "robot_id": "${ROBOT_ID}",
  "kind": "${kind}",
  "dry_run": ${dry_run_json},
  "params": ${params_json},
  "callback_url": "${CALLBACK_URL}"
}
JSON
)"

  echo "[replay] POST /robot-commands kind=${kind} id=${cmd_id}"
  curl -fsS -X POST "${NAV_BASE}/robot-commands" \
    -H "Content-Type: application/json" \
    -d "$payload" | python3 -m json.tool
  echo
}

poll_until() {
  local cmd_id="$1"
  local want_state="$2"
  local deadline=$((SECONDS + POLL_MAX))
  echo "[replay] polling ${cmd_id} until state=${want_state} (max ${POLL_MAX}s)..."

  while (( SECONDS < deadline )); do
    local state
    state="$(curl -fsS "${NAV_BASE}/robot-commands/${cmd_id}" | python3 -c "import sys,json; print(json.load(sys.stdin).get('state',''))" 2>/dev/null || echo "")"
    if [[ "$state" == "$want_state" ]]; then
      echo "[replay] ${cmd_id} -> ${state}"
      curl -fsS "${NAV_BASE}/robot-commands/${cmd_id}" | python3 -m json.tool
      return 0
    fi
    if [[ "$state" == "FAILED" || "$state" == "ABORTED" ]]; then
      echo "[replay] ${cmd_id} ended with ${state}" >&2
      curl -fsS "${NAV_BASE}/robot-commands/${cmd_id}" | python3 -m json.tool
      return 1
    fi
    sleep "$POLL_SEC"
  done

  echo "[replay] timeout waiting for ${want_state} on ${cmd_id}" >&2
  curl -fsS "${NAV_BASE}/robot-commands/${cmd_id}" | python3 -m json.tool || true
  return 1
}

echo "=== preflight health ==="
curl -fsS "${NAV_BASE}/movement-api/v1/health" | python3 -m json.tool
echo

run_step() {
  local n="$1"
  case "$n" in
    1)
      post_command "$CMD_LEAVE" "leave_dock" "{}"
      poll_until "$CMD_LEAVE" "DONE"
      ;;
    2)
      post_command "$CMD_MOVE" "move_to_point" "{\"x\": ${MOVE_X}, \"y\": ${MOVE_Y}, \"yaw\": ${MOVE_YAW}}"
      poll_until "$CMD_MOVE" "ARRIVED"
      ;;
    3)
      post_command "$CMD_DOCK" "dock_transfer" "{\"aruco_marker_id\": 1, \"action\": \"load\", \"level\": 1}"
      poll_until "$CMD_DOCK" "DONE"
      ;;
    *)
      echo "unknown step: $n" >&2
      exit 2
      ;;
  esac
}

if [[ "$STEP" == "all" ]]; then
  run_step 1
  run_step 2
  run_step 3
else
  run_step "$STEP"
fi

echo "[replay] done"
