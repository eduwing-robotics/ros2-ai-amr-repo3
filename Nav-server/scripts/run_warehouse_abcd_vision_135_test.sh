#!/usr/bin/env bash
# A→B→C→D 슬롯 vision insert 테스트 (기준 65px, 정지 135px)
set -euo pipefail

BASE="${MOVEMENT_API_URL:-http://127.0.0.1:8002}"
ROBOT_ID="${ROBOT_ID:-tb3_2}"
TASK_ID="${TASK_ID:-9090}"
TS=$(date +%s)

poll() {
  local cid="$1" want="$2" timeout="${3:-480}"
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
  curl -s -o /tmp/wh_vision_post.json -w 'HTTP %{http_code}\n' -X POST "$BASE/robot-commands" \
    -H 'Content-Type: application/json' \
    -d "{\"command_id\":\"$cid\",\"task_id\":$TASK_ID,\"robot_id\":\"$ROBOT_ID\",\"kind\":\"$kind\",\"params\":$params,\"callback_url\":\"\"}"
  python3 -m json.tool /tmp/wh_vision_post.json
}

visit_slot() {
  local tag="$1" wx="$2" wy="$3" wyaw="$4" marker="$5" action="$6" level="$7"
  local cid_nav="${tag}-${TS}-nav"
  post "$cid_nav" "move_to_point" "{\"x\":${wx},\"y\":${wy},\"theta\":${wyaw},\"nav_position_only\":true,\"soft_xy_tolerance_m\":0.10}"
  poll "$cid_nav" "ARRIVED" 480
  local cid_dock="${tag}-${TS}-dock"
  post "$cid_dock" "dock_transfer" "{\"aruco_marker_id\":${marker},\"action\":\"${action}\",\"level\":${level},\"lift_timeout_sec\":60,\"align_mode\":\"center_only\",\"docking_timeout_sec\":90,\"marker_search_on_miss\":true,\"marker_search_timeout_sec\":90}"
  poll "$cid_dock" "DONE" 420
}

echo "===== warehouse A→B→C→D vision stop @135px ====="
curl -sf "$BASE/movement-api/v1/robots/tb3_2/nav-state" | python3 -c "
import sys,json
d=json.load(sys.stdin)
p=d.get('pose') or {}
print(f'pose=({p.get(\"x\",0):.3f},{p.get(\"y\",0):.3f}) accepting={d.get(\"command_accepting\")}')
if not d.get('command_accepting'): raise SystemExit('FATAL: not accepting')
"

C0="wh-${TS}-leave"
post "$C0" "leave_dock" '{}'
poll "$C0" "DONE" 120

visit_slot "a" "0.019" "-0.618" "0.0" "7" "unload" "2"
visit_slot "b" "0.033" "-0.376" "0.0" "8" "load" "1"
visit_slot "c" "1.239" "-0.631" "3.142" "10" "unload" "2"
visit_slot "d" "1.225" "-0.377" "3.142" "9" "unload" "2"

C5="wh-${TS}-wait"
post "$C5" "move_to_point" '{"x":0.816,"y":0.006,"theta":1.571,"nav_position_only":true,"soft_xy_tolerance_m":0.12}'
poll "$C5" "ARRIVED" 360

C6="wh-${TS}-park"
post "$C6" "aruco_align" '{"aruco_marker_id":4,"align_mode":"center_only","final":"hold","center_tolerance_norm":0.03,"docking_timeout_sec":90,"marker_search_on_miss":true,"marker_search_timeout_sec":90}'
poll "$C6" "DONE" 300

echo ""
echo "======== WAREHOUSE ABCD @135px OK ========"
curl -sf "$BASE/movement-api/v1/health" | python3 -c "
import sys,json
p=json.load(sys.stdin).get('pose') or {}
print(f'END ({p.get(\"x\",0):.3f},{p.get(\"y\",0):.3f}) yaw={p.get(\"yaw\",0):.3f}')
"
