#!/usr/bin/env bash
#
# tb3_2 공장 E2E: 2호차대기 → 입고2 load → C슬롯 unload
# (도킹 정밀도 수정 후 재검증용)
#
set -euo pipefail

NAV_BASE="${NAV_BASE:-http://127.0.0.1:8002}"
ROBOT_ID="${ROBOT_ID:-tb3_2}"
TASK_ID="${TASK_ID:-9001}"
POLL_SEC="${POLL_SEC:-3}"
POLL_MAX="${POLL_MAX:-360}"
TS="$(date +%s)"
CALLBACK_URL="${CALLBACK_URL:-}"

post_command() {
  local cmd_id="$1" kind="$2" params_json="$3"
  local payload
  payload="$(cat <<JSON
{
  "command_id": "${cmd_id}",
  "task_id": ${TASK_ID},
  "robot_id": "${ROBOT_ID}",
  "kind": "${kind}",
  "dry_run": false,
  "params": ${params_json},
  "callback_url": "${CALLBACK_URL}"
}
JSON
)"
  echo ""
  echo "=== POST ${kind} id=${cmd_id} ==="
  curl -fsS -X POST "${NAV_BASE}/robot-commands" \
    -H "Content-Type: application/json" -d "$payload" | python3 -m json.tool
}

poll_until() {
  local cmd_id="$1" want_state="$2"
  local deadline=$((SECONDS + POLL_MAX))
  echo "[e2e] poll ${cmd_id} -> ${want_state} (max ${POLL_MAX}s)"
  while (( SECONDS < deadline )); do
    local body state stage reason
    body="$(curl -fsS "${NAV_BASE}/robot-commands/${cmd_id}" 2>/dev/null || echo '{}')"
    state="$(printf '%s' "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('state',''))" 2>/dev/null || echo "")"
    stage="$(printf '%s' "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('stage',''))" 2>/dev/null || echo "")"
  if [[ "$state" == "$want_state" ]]; then
      echo "[e2e] OK ${cmd_id} state=${state} stage=${stage}"
      printf '%s' "$body" | python3 -m json.tool
      return 0
    fi
    if [[ "$state" == "FAILED" || "$state" == "ABORTED" ]]; then
      reason="$(printf '%s' "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('reason',''))" 2>/dev/null || echo "")"
      echo "[e2e] FAIL ${cmd_id} state=${state} stage=${stage} reason=${reason}" >&2
      printf '%s' "$body" | python3 -m json.tool
      return 1
    fi
    echo "[e2e] ... ${cmd_id} state=${state:-?} stage=${stage:-?} (${SECONDS}s)"
    sleep "$POLL_SEC"
  done
  echo "[e2e] TIMEOUT ${cmd_id}" >&2
  curl -fsS "${NAV_BASE}/robot-commands/${cmd_id}" | python3 -m json.tool || true
  return 1
}

show_health() {
  echo "=== health ==="
  curl -fsS "${NAV_BASE}/movement-api/v1/health" | python3 -m json.tool
  echo "=== aruco ==="
  curl -fsS "${NAV_BASE}/movement-api/v1/aruco/latest" 2>/dev/null \
    | python3 -c "import sys,json; d=json.load(sys.stdin).get('detections',[]); print([(m['marker_id'], round(m.get('marker_width_px',0),1), round(m.get('center_error_norm',0),3)) for m in d] if d else 'none')" \
    || echo "aruco unavailable"
}

show_health

CMD1="e2e-${TS}-vehicle2"
CMD2="e2e-${TS}-inbound2"
CMD3="e2e-${TS}-dock-load-m1"
CMD4="e2e-${TS}-whc"
CMD5="e2e-${TS}-dock-unload-m10"

post_command "$CMD1" "move_to_point" '{"waypoint_id": "vehicle_2_approach"}'
poll_until "$CMD1" "ARRIVED"

post_command "$CMD2" "move_to_point" '{"waypoint_id": "inbound_slot_2_approach"}'
poll_until "$CMD2" "ARRIVED"

post_command "$CMD3" "dock_transfer" '{"aruco_marker_id": 1, "action": "load", "level": 1}'
poll_until "$CMD3" "DONE"

post_command "$CMD4" "move_to_point" '{"waypoint_id": "warehouse_c_approach"}'
poll_until "$CMD4" "ARRIVED"

post_command "$CMD5" "dock_transfer" '{"aruco_marker_id": 10, "action": "unload", "level": 1}'
poll_until "$CMD5" "DONE"

echo ""
echo "[e2e] ALL STEPS DONE"
show_health
