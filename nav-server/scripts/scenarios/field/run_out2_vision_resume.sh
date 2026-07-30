#!/usr/bin/env bash
# 출고2 vision insert 재시도 → 대기2 hold
set -euo pipefail
BASE="${MOVEMENT_API_URL:-http://127.0.0.1:8002}"
ROBOT_ID="${ROBOT_ID:-tb3_2}"
TASK_ID="${TASK_ID:-9072}"
TS=$(date +%s)

poll() {
  local cid="$1" want="$2" timeout="${3:-420}"
  local deadline=$((SECONDS + timeout))
  while (( SECONDS < deadline )); do
    local body state
    body=$(curl -sf "$BASE/robot-commands/$cid") || return 1
    state=$(echo "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('state',''))")
    echo "[$(date +%H:%M:%S)] $cid -> $state"
    [[ "$state" == "$want" ]] && return 0
    [[ "$state" == "FAILED" || "$state" == "ABORTED" ]] && {
      echo "$body" | python3 -m json.tool
      return 1
    }
    sleep 4
  done
  return 1
}

post() {
  local cid="$1" kind="$2" params="$3"
  echo ""
  echo "======== $kind ($cid) ========"
  curl -s -o /tmp/out2_resume.json -w 'HTTP %{http_code}\n' -X POST "$BASE/robot-commands" \
    -H 'Content-Type: application/json' \
    -d "{\"command_id\":\"$cid\",\"task_id\":$TASK_ID,\"robot_id\":\"$ROBOT_ID\",\"kind\":\"$kind\",\"params\":$params,\"callback_url\":\"\"}"
  python3 -m json.tool /tmp/out2_resume.json
}

curl -sf "$BASE/movement-api/v1/health" | python3 -c "
import sys,json
p=json.load(sys.stdin).get('pose') or {}
print(f'START ({p.get(\"x\",0):.3f},{p.get(\"y\",0):.3f}) yaw={p.get(\"yaw\",0):.3f}')
"

C1="out2r-${TS}-yaw"
post "$C1" "move_to_point" '{"x":1.45,"y":0.006,"theta":1.571,"nav_position_only":true,"soft_xy_tolerance_m":0.12}'
poll "$C1" "ARRIVED" 300

C2="out2r-${TS}-dock"
post "$C2" "dock_transfer" '{"aruco_marker_id":6,"action":"load","level":1,"lift_timeout_sec":60,"align_mode":"full_center","marker_search_timeout_sec":90,"docking_timeout_sec":90}'
poll "$C2" "DONE" 420

C3="out2r-${TS}-wait"
post "$C3" "move_to_point" '{"x":0.816,"y":0.006,"theta":1.571,"nav_position_only":true,"soft_xy_tolerance_m":0.12}'
poll "$C3" "ARRIVED" 360

C4="out2r-${TS}-park"
post "$C4" "aruco_align" '{"aruco_marker_id":4,"align_mode":"center_only","final":"hold","center_tolerance_norm":0.03,"docking_timeout_sec":90,"marker_search_on_miss":true,"marker_search_timeout_sec":90}'
poll "$C4" "DONE" 240

echo ""
echo "======== OUT2 RESUME OK ========"
