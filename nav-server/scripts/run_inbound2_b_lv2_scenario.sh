#!/usr/bin/env bash
# 입고2 픽업(load L1) → B슬롯 2층 적재(unload L2)
#
# 리프트: zones.json lift_levels_mm (approach 정렬 후 pre_insert → insert)
#   inbound2 L1: pre_insert 0mm(home) → insert → load 0mm → carry 50mm → reverse
#   B L2 unload: pre_insert 50mm → insert → unload 43mm → reverse
#
# 전제:
#   - scripts/start_all_tb3_2.sh restart (camera + detector2 + lift_bridge)
#   - config/robots.json tb3_2 lift.enabled=true
#   - 입고2에 파레트, B슬롯 2단 비어 있음
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

BASE="${MOVEMENT_API_URL:-http://127.0.0.1:8002}"
ROBOT_ID="${ROBOT_ID:-tb3_2}"
TASK_ID="${TASK_ID:-9042}"
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

nav_with_retry() {
  local wp="$1" tol="$2" prefix="$3" max="${4:-3}"
  local attempt=1
  while (( attempt <= max )); do
    local cid="${prefix}-a${attempt}"
    post "$cid" "move_to_point" "{\"waypoint_id\":\"$wp\",\"soft_xy_tolerance_m\":$tol}" || return 1
    if poll "$cid" "ARRIVED" 480; then return 0; fi
    echo "[nav_retry] $wp attempt $attempt/$max failed"
    ((attempt++)) || true
    sleep 6
  done
  return 1
}

preflight_lift_home() {
  echo "[preflight] lift HOME (이전 carry 높이 잔류 방지)"
  bash "$ROOT/scripts/test_lift_tb3_2.sh" home || echo "[preflight] WARNING: lift home 실패"
  sleep 8
}

maybe_reverse_out_if_inserted() {
  local need
  need=$(curl -sf "$BASE/movement-api/v1/robots/tb3_2/nav-state" | python3 -c "
import sys,json
d=json.load(sys.stdin)
p=d.get('pose') or {}
x,y=float(p.get('x',0)),float(p.get('y',0))
# 입고2 insert 구역 (approach y=0.006 보다 안쪽)
if 0.05 < x < 0.55 and y > 0.12:
    print('inbound2')
elif 0.0 < x < 0.55 and -0.55 < y < -0.15:
    print('warehouse_b')
else:
    print('no')
")
  if [[ "$need" == "no" ]]; then
    echo "[preflight] insert 구역 아님 — reverse_out 생략"
    return 0
  fi
  echo "[preflight] $need insert 구역 감지 — reverse_out(실제 후진) 선행"
  local cid="in2b2-${TS}-revout"
  local rev_params='{}'
  if [[ "$need" == "inbound2" ]]; then
    rev_params='{"aruco_marker_id":1}'
  elif [[ "$need" == "warehouse_b" ]]; then
    rev_params='{"aruco_marker_id":8}'
  fi
  post "$cid" "reverse_out" "$rev_params"
  poll "$cid" "DONE" 120
}

echo "===== preflight ====="
curl -sf "$BASE/movement-api/v1/robots/tb3_2/nav-state" | python3 -c "
import sys,json
d=json.load(sys.stdin)
age=d.get('pose_age_sec',999)
print(f'pose_age={age:.1f}s accepting={d.get(\"command_accepting\")} emergency={d.get(\"is_emergency\")}')
if age>30: raise SystemExit('WARN: pose stale — Nav2/AMCL 확인')
"
require_detector
preflight_lift_home
maybe_reverse_out_if_inserted
echo ""

C0="in2b2-${TS}-leave"
post "$C0" "leave_dock" '{}'
poll "$C0" "DONE" 120

# 1) 입고2 approach (full align at approach)
nav_with_retry "inbound_slot_2_approach" 0.15 "in2b2-${TS}-in2"

# 2) 입고2 load L1: approach 정렬 후 pre_insert 6mm → insert → lift 43 → carry 50 → reverse
C2="in2b2-${TS}-in2dock"
post "$C2" "dock_transfer" '{"aruco_marker_id":1,"action":"load","level":1}'
poll "$C2" "DONE" 420

# 3) B슬롯 approach
nav_with_retry "warehouse_b_approach" 0.12 "in2b2-${TS}-b"

# 4) B슬롯 unload L2: approach 정렬 후 pre_insert 50mm → insert → unload 6mm → reverse
C4="in2b2-${TS}-bdock"
post "$C4" "dock_transfer" '{"aruco_marker_id":8,"action":"unload","level":2}'
poll "$C4" "DONE" 420

echo ""
echo "======== SCENARIO OK (inbound2 load L1 → B unload L2) ========"
curl -sf "$BASE/movement-api/v1/health" | python3 -c "
import sys,json
p=json.load(sys.stdin).get('pose') or {}
print(f'END ({p.get(\"x\",0):.3f},{p.get(\"y\",0):.3f}) yaw={p.get(\"yaw\",0):.3f}')
"
