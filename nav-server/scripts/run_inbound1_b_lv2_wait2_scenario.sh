#!/usr/bin/env bash
# 입고1 픽업(load L1) → B슬롯 2층 적재(unload L2) → 대기2 hold
#
# 전제 (7/5 E2E와 동일 + 리프트):
#   - scripts/start_all_tb3_2.sh restart  ← camera + detector2 필수
#   - config/robots.json tb3_burger_02.lift.enabled=true + nav restart
#   - 입고1에 파레트, B슬롯 2단 비어 있음
#
set -euo pipefail

BASE="${MOVEMENT_API_URL:-http://127.0.0.1:8002}"
ROBOT_ID="${ROBOT_ID:-tb3_2}"
TASK_ID="${TASK_ID:-9031}"
TS=$(date +%s)
ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-5}"
export ROS_DOMAIN_ID

require_detector() {
  if ! pgrep -f "aruco_detector_node.py" >/dev/null 2>&1; then
    echo ""
    echo "FATAL: ArUco detector 미기동 (7/5 E2E 필수)"
    echo "  → scripts/start_all_tb3_2.sh restart"
    echo "  → terminator: robot-camera 옆 detector2 pane 확인"
    exit 1
  fi
  echo "detector: aruco_detector_node 프로세스 OK"
  if command -v ros2 >/dev/null 2>&1 && [[ -f /opt/ros/jazzy/setup.bash ]]; then
    local pub
    set +u
    # shellcheck disable=SC1091
    source /opt/ros/jazzy/setup.bash
    set -u
    pub="$(timeout 6 ros2 topic info /mission/tb3_2/aruco/detections 2>/dev/null | grep 'Publisher count' || true)"
    if [[ -n "$pub" ]] && [[ "$pub" != *"Publisher count: 0"* ]]; then
      echo "detector: $pub"
    else
      echo "WARN: /mission/tb3_2/aruco/detections publisher 없음 — detector pane 재시작"
    fi
  fi
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
curl -sf "$BASE/movement-api/v1/health" | python3 -m json.tool
echo ""
require_detector
echo ""

# leave_dock: 뒤 막히면 후진 생략(no-op) 후 진행 (기본 정책)
C0="ib1b2-${TS}-leave"
post "$C0" "leave_dock" '{}'
poll "$C0" "DONE" 120

# 1) 입고1 pre-approach: 넓은 곳에서 먼저 방향 정렬
C1P="ib1b2-${TS}-in1pre"
post "$C1P" "move_to_point" '{"x":-0.085,"y":-0.22,"theta":1.571,"waypoint_id":"inbound_slot_1_pre_approach","nav_position_only":true,"yaw_tolerance_rad":null,"soft_xy_tolerance_m":0.08}'
poll "$C1P" "ARRIVED" 240

# 2) 입고1 approach
C1="ib1b2-${TS}-in1"
post "$C1" "move_to_point" "{\"waypoint_id\":\"inbound_slot_1_approach\"}"
poll "$C1" "ARRIVED" 480

# 3) 입고1 load L1: insert → 43mm → carry 50mm → reverse
C2="ib1b2-${TS}-in1dock"
post "$C2" "dock_transfer" '{"aruco_marker_id":0,"action":"load","level":1}'
poll "$C2" "DONE" 360

# 4) B슬롯 approach
C3="ib1b2-${TS}-b"
post "$C3" "move_to_point" '{"waypoint_id":"warehouse_b_approach"}'
poll "$C3" "ARRIVED" 480

# 5) B슬롯 unload L2: pre-insert 50mm → insert → 6mm → reverse
C4="ib1b2-${TS}-bdock"
post "$C4" "dock_transfer" '{"aruco_marker_id":8,"action":"unload","level":2}'
poll "$C4" "DONE" 360

# 5) 대기2 approach
C5="ib1b2-${TS}-v2"
post "$C5" "move_to_point" '{"waypoint_id":"vehicle_2_approach"}'
poll "$C5" "ARRIVED" 300

# 6) 대기2 hold (리프트 동작 없음, 정면 주차)
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
