#!/usr/bin/env bash
# 대기2 → 입고2 load L1 → C슬롯 unload L2 → 대기2 hold
#
# 리프트 (zones.json 2026-07-08):
#   inbound2 L1: pre_insert 0 → insert → load 6 → carry 50 → reverse
#   C L2 unload: pre_insert 50 → insert → unload 43 → reverse
#
set -euo pipefail

BASE="${MOVEMENT_API_URL:-http://127.0.0.1:8002}"
ROBOT_ID="${ROBOT_ID:-tb3_2}"
TASK_ID="${TASK_ID:-9060}"
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
  code=$(curl -s -o /tmp/scenario_post.json -w '%{http_code}' -X POST "$BASE/robot-commands" \
    -H 'Content-Type: application/json' \
    -d "{\"command_id\":\"$cid\",\"task_id\":$TASK_ID,\"robot_id\":\"$ROBOT_ID\",\"kind\":\"$kind\",\"params\":$params,\"callback_url\":\"\"}")
  echo "HTTP $code"
  python3 -m json.tool /tmp/scenario_post.json
  [[ "$code" == "200" ]]
}

echo "===== preflight in2→C L2→wait2 ====="
curl -sf "$BASE/movement-api/v1/robots/tb3_2/nav-state" | python3 -c "
import sys,json
d=json.load(sys.stdin)
age=d.get('pose_age_sec',999)
print(f'pose_age={age:.1f}s accepting={d.get(\"command_accepting\")} emergency={d.get(\"is_emergency\")}')
if not d.get('command_accepting'): raise SystemExit('FATAL: command_accepting=false')
if d.get('is_emergency'): raise SystemExit('FATAL: estop — curl -X POST http://127.0.0.1:8002/robot/clear_estop')
"
pgrep -f aruco_detector_node >/dev/null || echo "WARN: detector 미기동"

C0="in2c-${TS}-leave"
post "$C0" "leave_dock" '{}'
poll "$C0" "DONE" 120

C1="in2c-${TS}-in2"
# waypoint_id는 auto align 체인·경로 실패 가능 — drive 시나리오와 동일 좌표 nav only
post "$C1" "move_to_point" '{"x":0.234,"y":0.006,"theta":1.571,"nav_position_only":true,"soft_xy_tolerance_m":0.15}'
poll "$C1" "ARRIVED" 480

C2="in2c-${TS}-in2dock"
post "$C2" "dock_transfer" '{"aruco_marker_id":1,"action":"load","level":1,"lift_timeout_sec":60,"align_mode":"full_center"}'
poll "$C2" "DONE" 420

C3="in2c-${TS}-c"
post "$C3" "move_to_point" '{"x":1.239,"y":-0.631,"theta":3.142,"nav_position_only":true,"soft_xy_tolerance_m":0.10}'
poll "$C3" "ARRIVED" 480

C4="in2c-${TS}-cdock"
post "$C4" "dock_transfer" '{"aruco_marker_id":10,"action":"unload","level":2,"lift_timeout_sec":60}'
poll "$C4" "DONE" 420

C5="in2c-${TS}-wait"
post "$C5" "move_to_point" '{"x":0.816,"y":0.006,"theta":1.571,"nav_position_only":true,"soft_xy_tolerance_m":0.12}'
poll "$C5" "ARRIVED" 360

C6="in2c-${TS}-park"
post "$C6" "aruco_align" '{"aruco_marker_id":4,"align_mode":"center_only","final":"hold","center_tolerance_norm":0.03,"docking_timeout_sec":90,"marker_search_on_miss":true,"marker_search_timeout_sec":90}'
poll "$C6" "DONE" 240

echo ""
echo "======== SCENARIO OK (in2 load L1 → C unload L2 → wait2) ========"
curl -sf "$BASE/movement-api/v1/health" | python3 -c "
import sys,json
p=json.load(sys.stdin).get('pose') or {}
print(f'END ({p.get(\"x\",0):.3f},{p.get(\"y\",0):.3f}) yaw={p.get(\"yaw\",0):.3f}')
"
