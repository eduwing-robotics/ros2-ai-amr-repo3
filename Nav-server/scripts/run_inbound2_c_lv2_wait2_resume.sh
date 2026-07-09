#!/usr/bin/env bash
# 입고2 적재 완료(carry 50mm) 후 C unload L2 → 대기2 hold 재개
set -euo pipefail

BASE="${MOVEMENT_API_URL:-http://127.0.0.1:8002}"
ROBOT_ID="${ROBOT_ID:-tb3_2}"
TASK_ID="${TASK_ID:-9061}"
TS=$(date +%s)

poll() {
  local cid="$1" want="$2" timeout="${3:-600}"
  local deadline=$((SECONDS + timeout))
  while (( SECONDS < deadline )); do
    local body state msg
    body=$(curl -sf "$BASE/robot-commands/$cid") || return 1
    state=$(echo "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('state',''))")
    msg=$(echo "$body" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('message','')[:140])")
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
  code=$(curl -s -o /tmp/scenario_resume_post.json -w '%{http_code}' -X POST "$BASE/robot-commands" \
    -H 'Content-Type: application/json' \
    -d "{\"command_id\":\"$cid\",\"task_id\":$TASK_ID,\"robot_id\":\"$ROBOT_ID\",\"kind\":\"$kind\",\"params\":$params,\"callback_url\":\"\"}")
  echo "HTTP $code"
  python3 -m json.tool /tmp/scenario_resume_post.json
  [[ "$code" == "200" ]]
}

echo "===== resume C→wait2 (from inbound2 carry) ====="
curl -sf "$BASE/movement-api/v1/robots/tb3_2/nav-state" | python3 -c "
import sys,json
d=json.load(sys.stdin)
p=d.get('pose') or {}
print(f'pose=({p.get(\"x\",0):.3f},{p.get(\"y\",0):.3f}) accepting={d.get(\"command_accepting\")}')
"

C3="in2c-r${TS}-c"
post "$C3" "move_to_point" '{"x":1.239,"y":-0.631,"theta":3.142,"nav_position_only":true,"soft_xy_tolerance_m":0.10}'
poll "$C3" "ARRIVED" 480

C4="in2c-r${TS}-cdock"
post "$C4" "dock_transfer" '{"aruco_marker_id":10,"action":"unload","level":2,"lift_timeout_sec":60}'
poll "$C4" "DONE" 420

C5="in2c-r${TS}-wait"
post "$C5" "move_to_point" '{"x":0.816,"y":0.006,"theta":1.571,"nav_position_only":true,"soft_xy_tolerance_m":0.12}'
poll "$C5" "ARRIVED" 360

C6="in2c-r${TS}-park"
post "$C6" "aruco_align" '{"aruco_marker_id":4,"align_mode":"center_only","final":"hold","center_tolerance_norm":0.03,"docking_timeout_sec":90,"marker_search_on_miss":true,"marker_search_timeout_sec":90}'
poll "$C6" "DONE" 240

echo ""
echo "======== RESUME OK (C unload L2 → wait2) ========"
