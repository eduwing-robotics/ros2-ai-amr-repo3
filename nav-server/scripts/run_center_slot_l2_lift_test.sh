#!/usr/bin/env bash
# 중앙 슬롯 A/B/C/D — 2층(L2) 적재 리프트 높이 테스트
#
# 흐름: approach Nav2 → center align → pre_insert(2F 진입) → 전진삽입 → unload(살짝 내림) → 후진
#
# Usage:
#   SLOT=a bash scripts/run_center_slot_l2_lift_test.sh
#   PRE_INSERT_MM=50 UNLOAD_MM=12 SLOT=b bash scripts/run_center_slot_l2_lift_test.sh
#
set -euo pipefail

BASE="${MOVEMENT_API_URL:-http://127.0.0.1:8002}"
ROBOT_ID="${ROBOT_ID:-tb3_2}"
ROBOT_NAME="${ROBOT_NAME:-tb3_2}"
TASK_ID="${TASK_ID:-9043}"
SLOT="${SLOT:-a}"
INSERT_SPEED="${INSERT_SPEED:-0.035}"
PRE_INSERT_MM="${PRE_INSERT_MM:-50}"
UNLOAD_MM="${UNLOAD_MM:-12}"
TRAVEL_MM="${TRAVEL_MM:-50}"
ROBOT_SSH="${ROBOT_SSH:-musk@192.168.30.102}"
ROBOT_PW="${ROBOT_PW:-1234}"
TS=$(date +%s)

case "${SLOT,,}" in
  a) WX=0.026; WY=-0.025; WYAW=0.0; MARKER=7; DIST=0.385; LABEL="warehouse_a" ;;
  b) WX=0.033; WY=-0.376; WYAW=0.0; MARKER=8; DIST=0.375; LABEL="warehouse_b" ;;
  c) WX=1.226; WY=-0.025; WYAW=3.142; MARKER=10; DIST=0.395; LABEL="warehouse_c" ;;
  d) WX=1.225; WY=-0.377; WYAW=3.142; MARKER=9; DIST=0.385; LABEL="warehouse_d" ;;
  *) echo "SLOT must be a|b|c|d" >&2; exit 1 ;;
esac

lift_move() {
  local mm="$1"
  echo ""
  echo "======== lift -> ${mm}mm ========"
  sshpass -p "$ROBOT_PW" ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=25 "$ROBOT_SSH" \
    "export ROS_DOMAIN_ID=5; source /opt/ros/jazzy/setup.bash; source /home/musk/lift_project/ros2_ws/install/setup.bash;
     ros2 topic pub --once /lift/cmd_move std_msgs/msg/Float32 \"{data: ${mm}.0}\" >/dev/null; sleep 12;
     echo -n position=; timeout 5 ros2 topic echo /lift/position --once 2>/dev/null | awk '/^data:/ {print \$2; exit}'"
}

poll() {
  local cid="$1" want="$2" timeout="${3:-480}"
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

post_cmd() {
  local cid="$1" kind="$2" params="$3"
  echo ""
  echo "======== $kind ($cid) ========"
  curl -sf -X POST "$BASE/robot-commands" \
    -H 'Content-Type: application/json' \
    -d "{\"command_id\":\"$cid\",\"task_id\":$TASK_ID,\"robot_id\":\"$ROBOT_ID\",\"kind\":\"$kind\",\"params\":$params,\"callback_url\":\"\"}" \
    | python3 -m json.tool
}

manual_drive() {
  local dir="$1" dist="$2"
  local dur
  dur=$(python3 -c "print(max(1.0, ${dist}/${INSERT_SPEED}))")
  echo "manual $dir ${dist}m (~${dur}s)"
  curl -s --max-time 5 -X POST "$BASE/movement-api/v1/manual/start" \
    -H 'Content-Type: application/json' \
    -d "{\"robot_name\":\"$ROBOT_NAME\",\"command\":\"$dir\",\"linear_x\":$INSERT_SPEED,\"timeout_sec\":$dur,\"override_nav\":true}" \
    | python3 -m json.tool
  sleep "$(python3 -c "import math; print(max(1.0, math.ceil(${dur})+1))")"
  curl -s -X POST "$BASE/movement-api/v1/manual/stop" \
    -H 'Content-Type: application/json' \
    -d "{\"robot_name\":\"$ROBOT_NAME\"}" | python3 -m json.tool
}

echo "===== L2 lift test slot=$SLOT ($LABEL) pre_insert=${PRE_INSERT_MM} unload=${UNLOAD_MM} ====="
curl -sf "$BASE/movement-api/v1/robots/tb3_2/nav-state" | python3 -c "
import sys,json
d=json.load(sys.stdin)
print(f'pose_age={d.get(\"pose_age_sec\",999):.1f}s accepting={d.get(\"command_accepting\")}')
"

# 이동 전 2층 높이 (파레트 들고 올 때)
lift_move "$TRAVEL_MM"

C1="${LABEL}-${TS}-nav"
post_cmd "$C1" "move_to_point" "{\"x\":$WX,\"y\":$WY,\"theta\":$WYAW,\"nav_position_only\":true,\"soft_xy_tolerance_m\":0.10}"
poll "$C1" "ARRIVED" 360

C2="${LABEL}-${TS}-align"
post_cmd "$C2" "aruco_align" "{\"aruco_marker_id\":$MARKER,\"align_mode\":\"center_only\",\"final\":\"return_approach\",\"docking_timeout_sec\":90,\"marker_search_on_miss\":true,\"marker_search_timeout_sec\":45}"
poll "$C2" "DONE" 180

lift_move "$PRE_INSERT_MM"

echo ""
echo "======== manual forward ${DIST}m (2F insert) ========"
manual_drive forward "$DIST"

lift_move "$UNLOAD_MM"

echo ""
echo "======== manual backward ${DIST}m ========"
manual_drive backward "$DIST"

echo ""
echo "======== SLOT $SLOT L2 lift test DONE (pre_insert=${PRE_INSERT_MM} unload=${UNLOAD_MM}) ========"
