#!/usr/bin/env bash
# Resume after inbound1 load succeeded and robot is at/near warehouse_b_approach.
# Flow: B unload L2 -> vehicle_2_approach -> wait2 hold.
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
curl -sf "$BASE/movement-api/v1/health" | python3 -c '
import sys,json
d=json.load(sys.stdin); p=d.get("pose") or {}; seen=[x.get("marker_id") for x in d.get("latest_aruco_detections") or []]
print("localized",d.get("localized"),"accepting",d.get("command_accepting"),"emergency",d.get("is_emergency"),"seen",seen)
print("pose ({:.3f},{:.3f}) yaw={:.3f}".format(p.get("x",0), p.get("y",0), p.get("yaw",0)))
if d.get("is_emergency"):
  raise SystemExit("FATAL: estop active")
if not d.get("localized") or not d.get("command_accepting"):
  raise SystemExit("FATAL: not ready")
'
require_detector

C1="ib1b2-resume-${TS}-bdock"
post "$C1" "dock_transfer" '{"aruco_marker_id":8,"action":"unload","level":2}'
poll "$C1" "DONE" 360

C2="ib1b2-resume-${TS}-v2"
post "$C2" "move_to_point" '{"waypoint_id":"vehicle_2_approach"}'
poll "$C2" "ARRIVED" 300

C3="ib1b2-resume-${TS}-park"
post "$C3" "aruco_align" '{"aruco_marker_id":4,"final":"hold","center_tolerance_norm":0.03,"docking_timeout_sec":90,"marker_search_on_miss":true,"marker_search_timeout_sec":45}'
poll "$C3" "DONE" 180

echo ""
echo "======== RESUME OK (B unload L2 -> wait2) ========"
