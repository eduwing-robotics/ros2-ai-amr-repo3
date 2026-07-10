#!/usr/bin/env bash
# 대기2 → 입고1 → 출고1 → 출고2 vision insert(135px) → 대기2 hold
# B안: full_center align + dock_transfer vision insert + lift L1
set -euo pipefail

BASE="${MOVEMENT_API_URL:-http://127.0.0.1:8002}"
ROBOT_ID="${ROBOT_ID:-tb3_2}"
TASK_ID="${TASK_ID:-9070}"
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
  code=$(curl -s -o /tmp/in1out_vision_post.json -w '%{http_code}' -X POST "$BASE/robot-commands" \
    -H 'Content-Type: application/json' \
    -d "{\"command_id\":\"$cid\",\"task_id\":$TASK_ID,\"robot_id\":\"$ROBOT_ID\",\"kind\":\"$kind\",\"params\":$params,\"callback_url\":\"\"}")
  echo "HTTP $code"
  python3 -m json.tool /tmp/in1out_vision_post.json
  [[ "$code" == "200" ]]
}

dock_load() {
  local tag="$1" marker="$2"
  post "${tag}-${TS}-dock" "dock_transfer" \
    "{\"aruco_marker_id\":${marker},\"action\":\"load\",\"level\":1,\"lift_timeout_sec\":60,\"align_mode\":\"full_center\"}"
  poll "${tag}-${TS}-dock" "DONE" 420
}

echo "===== preflight in1→out1→out2 vision test ====="
curl -sf "$BASE/movement-api/v1/robots/tb3_2/nav-state" | python3 -c "
import sys,json
d=json.load(sys.stdin)
p=d.get('pose') or {}
print(f'pose=({p.get(\"x\",0):.3f},{p.get(\"y\",0):.3f}) accepting={d.get(\"command_accepting\")} emergency={d.get(\"is_emergency\")}')
if not d.get('command_accepting'): raise SystemExit('FATAL: command_accepting=false')
if d.get('is_emergency'): raise SystemExit('FATAL: estop')
"
pgrep -f aruco_detector_node >/dev/null || echo "WARN: detector 미기동"

C0="io-${TS}-leave"
post "$C0" "leave_dock" '{}'
poll "$C0" "DONE" 120

C1="io-${TS}-in1"
post "$C1" "move_to_point" '{"x":-0.085,"y":0.006,"theta":1.571,"nav_position_only":true,"soft_xy_tolerance_m":0.22}'
poll "$C1" "ARRIVED" 480
dock_load "io-${TS}-in1" 0

C2="io-${TS}-out1"
post "$C2" "move_to_point" '{"x":1.131,"y":0.006,"theta":1.571,"nav_position_only":true,"soft_xy_tolerance_m":0.15}'
poll "$C2" "ARRIVED" 480
dock_load "io-${TS}-out1" 5

C3="io-${TS}-out2"
post "$C3" "move_to_point" '{"x":1.45,"y":0.006,"theta":1.571,"nav_position_only":true,"soft_xy_tolerance_m":0.15}'
poll "$C3" "ARRIVED" 480
dock_load "io-${TS}-out2" 6

C4="io-${TS}-wait"
post "$C4" "move_to_point" '{"x":0.816,"y":0.006,"theta":1.571,"nav_position_only":true,"soft_xy_tolerance_m":0.12}'
poll "$C4" "ARRIVED" 360

C5="io-${TS}-park"
post "$C5" "aruco_align" '{"aruco_marker_id":4,"align_mode":"center_only","final":"hold","center_tolerance_norm":0.03,"docking_timeout_sec":90,"marker_search_on_miss":true,"marker_search_timeout_sec":90}'
poll "$C5" "DONE" 240

echo ""
echo "======== SCENARIO OK (in1 → out1 → out2 vision → wait2) ========"
curl -sf "$BASE/movement-api/v1/health" | python3 -c "
import sys,json
p=json.load(sys.stdin).get('pose') or {}
print(f'END ({p.get(\"x\",0):.3f},{p.get(\"y\",0):.3f}) yaw={p.get(\"yaw\",0):.3f}')
"
