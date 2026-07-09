#!/usr/bin/env bash
# B→C→D vision 135px (A 실패 시 재개) 또는 SLOT=a|b|c|d 단일
set -euo pipefail
BASE="${MOVEMENT_API_URL:-http://127.0.0.1:8002}"
ROBOT_ID="${ROBOT_ID:-tb3_2}"
TASK_ID="${TASK_ID:-9091}"
ONLY="${SLOT:-bcd}"
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
    [[ "$state" == "FAILED" || "$state" == "ABORTED" ]] && { echo "$body" | python3 -m json.tool; return 1; }
    sleep 4
  done
  return 1
}

post() {
  local cid="$1" kind="$2" params="$3"
  echo ""; echo "======== $kind ($cid) ========"
  curl -s -o /tmp/wh_slot.json -w 'HTTP %{http_code}\n' -X POST "$BASE/robot-commands" \
    -H 'Content-Type: application/json' \
    -d "{\"command_id\":\"$cid\",\"task_id\":$TASK_ID,\"robot_id\":\"$ROBOT_ID\",\"kind\":\"$kind\",\"params\":$params,\"callback_url\":\"\"}"
  python3 -m json.tool /tmp/wh_slot.json
}

dock() {
  local tag="$1" wx="$2" wy="$3" wyaw="$4" marker="$5" action="$6" level="$7"
  post "${tag}-${TS}-nav" "move_to_point" "{\"x\":${wx},\"y\":${wy},\"theta\":${wyaw},\"nav_position_only\":true,\"soft_xy_tolerance_m\":0.10}"
  poll "${tag}-${TS}-nav" "ARRIVED" 480
  post "${tag}-${TS}-dock" "dock_transfer" "{\"aruco_marker_id\":${marker},\"action\":\"${action}\",\"level\":${level},\"lift_timeout_sec\":60,\"align_mode\":\"center_only\",\"docking_timeout_sec\":90,\"marker_search_on_miss\":true,\"marker_search_timeout_sec\":90}"
  poll "${tag}-${TS}-dock" "DONE" 420
}

curl -sf "$BASE/movement-api/v1/health" | python3 -c "import sys,json; p=json.load(sys.stdin).get('pose')or{}; print(f'START ({p.get(\"x\",0):.3f},{p.get(\"y\",0):.3f})')"

[[ "$ONLY" == *a* ]] && dock "a" "0.019" "-0.618" "0.0" "7" "unload" "2"
[[ "$ONLY" == *b* ]] && dock "b" "0.033" "-0.376" "0.0" "8" "load" "1"
[[ "$ONLY" == *c* ]] && dock "c" "1.239" "-0.631" "3.142" "10" "unload" "2"
[[ "$ONLY" == *d* ]] && dock "d" "1.225" "-0.377" "3.142" "9" "unload" "2"

echo "======== SLOT TEST DONE ($ONLY) ========"
