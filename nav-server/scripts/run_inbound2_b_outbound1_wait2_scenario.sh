#!/usr/bin/env bash
# inbound2 → insert/reverse → B슬롯 → insert/reverse → outbound1 → insert/reverse → 대기2 hold
set -euo pipefail

BASE="${MOVEMENT_API_URL:-http://127.0.0.1:8002}"
ROBOT_ID="${ROBOT_ID:-tb3_2}"
TASK_ID="${TASK_ID:-9022}"
TS=$(date +%s)

poll() {
  local cid="$1" want="$2" timeout="${3:-600}"
  local deadline=$((SECONDS + timeout))
  while (( SECONDS < deadline )); do
    local body state msg
    body=$(curl -sf "$BASE/robot-commands/$cid") || return 1
    state=$(echo "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('state',''))")
    msg=$(echo "$body" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('message','')[:90])")
    echo "[$(date +%H:%M:%S)] $cid -> $state | $msg"
    [[ "$state" == "$want" ]] && return 0
    [[ "$state" == "FAILED" || "$state" == "ABORTED" ]] && {
      echo "$body" | python3 -m json.tool
      return 1
    }
    sleep 4
  done
  echo "TIMEOUT $cid"
  return 1
}

post() {
  local cid="$1" kind="$2" params="$3"
  echo ""
  echo "======== $kind ($cid) ========"
  local code
  code=$(curl -s -o /tmp/scenario_post.json -w '%{http_code}' -X POST "$BASE/robot-commands" \
    -H 'Content-Type: application/json' \
    -d "{\"command_id\":\"$cid\",\"task_id\":$TASK_ID,\"robot_id\":\"$ROBOT_ID\",\"kind\":\"$kind\",\"params\":$params,\"callback_url\":\"\"}")
  echo "HTTP $code"
  python3 -m json.tool /tmp/scenario_post.json
  [[ "$code" == "200" ]]
}

curl -sf "$BASE/movement-api/v1/health" | python3 -c "
import sys,json
p=json.load(sys.stdin).get('pose') or {}
print(f'START ({p.get(\"x\",0):.3f},{p.get(\"y\",0):.3f}) yaw={p.get(\"yaw\",0):.3f}')
"

# 0) 대기장 hold 주차 상태면 후진 이탈 (미주차 시 no-op)
C0="in2b-${TS}-leave"
post "$C0" "leave_dock" '{}'
poll "$C0" "DONE" 120

# 1) 입고2 approach
C1="in2b-${TS}-in2"
post "$C1" "move_to_point" '{"waypoint_id":"inbound_slot_2_approach"}'
poll "$C1" "ARRIVED" 480

# 2) 입고2 dock: align + insert + 4s dwell + reverse
C2="in2b-${TS}-in2dock"
post "$C2" "dock_transfer" '{"aruco_marker_id":1,"action":"load","level":1}'
poll "$C2" "DONE" 300

# 3) B슬롯 approach
C3="in2b-${TS}-b"
post "$C3" "move_to_point" '{"waypoint_id":"warehouse_b_approach"}'
poll "$C3" "ARRIVED" 480

# 4) B슬롯 dock
C4="in2b-${TS}-bdock"
post "$C4" "dock_transfer" '{"aruco_marker_id":8,"action":"load","level":1}'
poll "$C4" "DONE" 300

# 5) 출고1 approach
C5="in2b-${TS}-out1"
post "$C5" "move_to_point" '{"waypoint_id":"outbound_slot_1_approach"}'
poll "$C5" "ARRIVED" 480

# 6) 출고1 dock
C6="in2b-${TS}-out1dock"
post "$C6" "dock_transfer" '{"aruco_marker_id":5,"action":"load","level":1}'
poll "$C6" "DONE" 300

# 7) 대기2 approach
C7="in2b-${TS}-v2"
post "$C7" "move_to_point" '{"waypoint_id":"vehicle_2_approach"}'
poll "$C7" "ARRIVED" 300

# 8) 대기2 hold park
C8="in2b-${TS}-park"
post "$C8" "aruco_align" '{"aruco_marker_id":4,"final":"hold","center_tolerance_norm":0.03,"docking_timeout_sec":90,"marker_search_on_miss":true,"marker_search_timeout_sec":45}'
poll "$C8" "DONE" 180

echo ""
echo "======== SCENARIO OK ========"
curl -sf "$BASE/movement-api/v1/health" | python3 -c "
import sys,json
p=json.load(sys.stdin).get('pose') or {}
print(f'END ({p.get(\"x\",0):.3f},{p.get(\"y\",0):.3f}) yaw={p.get(\"yaw\",0):.3f}')
"
