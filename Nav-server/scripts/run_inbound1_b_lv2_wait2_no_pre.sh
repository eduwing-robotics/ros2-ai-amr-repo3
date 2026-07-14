#!/usr/bin/env bash
# 입고1 픽업(load L1) → B슬롯 2층 적재(unload L2) → 대기2 hold
# pre_approach 생략 (Nav2 FAILED 회피) — approach 직행
set -euo pipefail

BASE="${MOVEMENT_API_URL:-http://127.0.0.1:8002}"
ROBOT_ID="${ROBOT_ID:-tb3_2}"
TASK_ID="${TASK_ID:-9031}"
TS=$(date +%s)
ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-5}"
export ROS_DOMAIN_ID

require_detector() {
  if ! pgrep -f "aruco_detector_node.py" >/dev/null 2>&1; then
    echo "FATAL: ArUco detector 미기동"
    exit 1
  fi
  echo "detector: OK"
}

poll() {
  local cid="$1" want="$2" timeout="${3:-600}"
  local deadline=$((SECONDS + timeout))
  while (( SECONDS < deadline )); do
    local body state msg
    body=$(curl -sf "$BASE/robot-commands/$cid") || return 1
    state=$(echo "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('state',''))")
    msg=$(echo "$body" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('message','')[:120])")
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

echo "===== preflight ====="
curl -sf "$BASE/movement-api/v1/health" | python3 -c "
import sys,json
d=json.load(sys.stdin); p=d.get('pose') or {}
print('localized',d.get('localized'),'accepting',d.get('command_accepting'),'emergency',d.get('is_emergency'))
print(f\"pose ({p.get('x',0):.3f},{p.get('y',0):.3f}) yaw={p.get('yaw',0):.3f}\")
if d.get('is_emergency'):
  raise SystemExit('FATAL: estop active')
if not d.get('localized') or not d.get('command_accepting'):
  raise SystemExit('FATAL: not ready')
"
require_detector

# leave_dock (대기2 hold면 후진)
C0="ib1b2-${TS}-leave"
post "$C0" "leave_dock" '{}'
poll "$C0" "DONE" 120

# 입고1 approach (pre_approach 생략)
C1="ib1b2-${TS}-in1"
post "$C1" "move_to_point" '{"waypoint_id":"inbound_slot_1_approach"}'
poll "$C1" "ARRIVED" 480

# 입고1 load L1
C2="ib1b2-${TS}-in1dock"
post "$C2" "dock_transfer" '{"aruco_marker_id":0,"action":"load","level":1}'
poll "$C2" "DONE" 360

# B approach
C3="ib1b2-${TS}-b"
post "$C3" "move_to_point" '{"waypoint_id":"warehouse_b_approach"}'
poll "$C3" "ARRIVED" 480

# B unload L2
C4="ib1b2-${TS}-bdock"
post "$C4" "dock_transfer" '{"aruco_marker_id":8,"action":"unload","level":2}'
poll "$C4" "DONE" 360

# 대기2
C5="ib1b2-${TS}-v2"
post "$C5" "move_to_point" '{"waypoint_id":"vehicle_2_approach"}'
poll "$C5" "ARRIVED" 300

C6="ib1b2-${TS}-park"
post "$C6" "aruco_align" '{"aruco_marker_id":4,"final":"hold","center_tolerance_norm":0.03,"docking_timeout_sec":90,"marker_search_on_miss":true,"marker_search_timeout_sec":45}'
poll "$C6" "DONE" 180

echo ""
echo "======== SCENARIO OK (inbound1 load → B unload L2 → wait2) ========"
curl -sf "$BASE/movement-api/v1/health" | python3 -c "
import sys,json
p=json.load(sys.stdin).get('pose') or {}
print(f'END ({p.get(\"x\",0):.3f},{p.get(\"y\",0):.3f}) yaw={p.get(\"yaw\",0):.3f}')
"
