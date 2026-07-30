#!/usr/bin/env bash
# 대기1 → 대기2 vision hold insert (정지 140px)
set -euo pipefail

BASE="${MOVEMENT_API_URL:-http://127.0.0.1:8002}"
ROBOT_ID="${ROBOT_ID:-tb3_2}"
TASK_ID="${TASK_ID:-9080}"
TS=$(date +%s)

poll() {
  local cid="$1" want="$2" timeout="${3:-360}"
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
  curl -s -o /tmp/wait_vision_post.json -w 'HTTP %{http_code}\n' -X POST "$BASE/robot-commands" \
    -H 'Content-Type: application/json' \
    -d "{\"command_id\":\"$cid\",\"task_id\":$TASK_ID,\"robot_id\":\"$ROBOT_ID\",\"kind\":\"$kind\",\"params\":$params,\"callback_url\":\"\"}"
  python3 -m json.tool /tmp/wait_vision_post.json
}

hold_park() {
  local tag="$1" marker="$2" wx="$3" wy="$4" wyaw="$5"
  local cid_nav="${tag}-${TS}-nav"
  post "$cid_nav" "move_to_point" "{\"x\":${wx},\"y\":${wy},\"theta\":${wyaw},\"nav_position_only\":true,\"soft_xy_tolerance_m\":0.12}"
  poll "$cid_nav" "ARRIVED" 360
  local cid_park="${tag}-${TS}-park"
  post "$cid_park" "aruco_align" "{\"aruco_marker_id\":${marker},\"align_mode\":\"center_only\",\"final\":\"hold\",\"center_tolerance_norm\":0.03,\"docking_timeout_sec\":90,\"marker_search_on_miss\":true,\"marker_search_timeout_sec\":90}"
  poll "$cid_park" "DONE" 300
}

echo "===== wait1(148px) + wait2(132px cap0.32m) ====="
curl -sf "$BASE/movement-api/v1/robots/tb3_2/nav-state" | python3 -c "
import sys,json
d=json.load(sys.stdin)
p=d.get('pose') or {}
print(f'pose=({p.get(\"x\",0):.3f},{p.get(\"y\",0):.3f}) accepting={d.get(\"command_accepting\")}')
if not d.get('command_accepting'): raise SystemExit('FATAL: not accepting')
"

C0="w145-${TS}-leave"
post "$C0" "leave_dock" '{}'
poll "$C0" "DONE" 120

hold_park "wait1" 3 "0.527" "0.006" "1.571"

C1="w145-${TS}-leave2"
post "$C1" "leave_dock" '{}'
poll "$C1" "DONE" 120

hold_park "wait2" 4 "0.816" "0.006" "1.571"

echo ""
echo "======== WAIT1+WAIT2 per-slot tune OK ========"
curl -sf "$BASE/movement-api/v1/health" | python3 -c "
import sys,json
p=json.load(sys.stdin).get('pose') or {}
print(f'END ({p.get(\"x\",0):.3f},{p.get(\"y\",0):.3f}) yaw={p.get(\"yaw\",0):.3f}')
"
