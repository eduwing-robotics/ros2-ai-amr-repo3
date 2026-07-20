#!/usr/bin/env bash
# 주행 전용 시나리오: approach → align → 수동 전진/후진 (리프트/dock_transfer 없음)
#
# Usage:
#   SCENARIO=in1_b_wait2 bash scripts/run_drive_insert_scenario.sh
#   SCENARIO=all bash scripts/run_drive_insert_scenario.sh
#   LOOPS=3 SCENARIO=in2_b_wait2 bash scripts/run_drive_insert_scenario.sh
#
# Scenarios:
#   in1_b_wait2   입고1 → B → 대기2 hold
#   in2_b_wait2   입고2 → B → 대기2 hold
#   in1_c_wait2   입고1 → C → 대기2 hold
#   in2_out1_wait2  입고2 → 출고1 → 대기2 hold
#   out2_a_wait2  출고2 → A → 대기2 hold
#   all           위 5개 순차 (각 루프마다 leave_dock 1회)
#
set -euo pipefail

BASE="${MOVEMENT_API_URL:-http://127.0.0.1:8002}"
ROBOT_ID="${ROBOT_ID:-tb3_2}"
ROBOT_NAME="${ROBOT_NAME:-tb3_2}"
TASK_ID="${TASK_ID:-9050}"
SCENARIO="${SCENARIO:-in1_b_wait2}"
LOOPS="${LOOPS:-1}"
INSERT_SPEED="${INSERT_SPEED:-0.035}"
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
  code=$(curl -s -o /tmp/drive_scenario_post.json -w '%{http_code}' -X POST "$BASE/robot-commands" \
    -H 'Content-Type: application/json' \
    -d "{\"command_id\":\"$cid\",\"task_id\":$TASK_ID,\"robot_id\":\"$ROBOT_ID\",\"kind\":\"$kind\",\"params\":$params,\"callback_url\":\"\"}")
  echo "HTTP $code"
  python3 -m json.tool /tmp/drive_scenario_post.json
  [[ "$code" == "200" ]]
}

manual_insert() {
  local dir="$1" dist="$2"
  local dur
  dur=$(python3 -c "print(max(1.0, ${dist}/${INSERT_SPEED}))")
  echo "manual $dir ${dist}m (~${dur}s @ ${INSERT_SPEED}m/s)"
  curl -s --max-time 8 -X POST "$BASE/movement-api/v1/manual/start" \
    -H 'Content-Type: application/json' \
    -d "{\"robot_name\":\"$ROBOT_NAME\",\"command\":\"$dir\",\"linear_x\":$INSERT_SPEED,\"timeout_sec\":$dur,\"override_nav\":true}" \
    | python3 -m json.tool
  sleep "$(python3 -c "import math; print(max(1.0, math.ceil(${dur})+1))")"
  curl -s -X POST "$BASE/movement-api/v1/manual/stop" \
    -H 'Content-Type: application/json' \
    -d "{\"robot_name\":\"$ROBOT_NAME\"}" | python3 -m json.tool
}

# wall 슬롯: Nav2 approach 좌표까지만 + center_only(회전만, 전진 없음) → 수동 insert만 전진
# (move_to_point+waypoint는 full align 전진이 체인되어 fork_insert 거리가 이중 적용됨)
visit_wall_slot() {
  local tag="$1" wx="$2" wy="$3" wyaw="$4" marker="$5" dist="$6" soft_xy="${7:-0.15}"
  local cid_nav="${tag}-${TS}-nav"
  post "$cid_nav" "move_to_point" "{\"x\":${wx},\"y\":${wy},\"theta\":${wyaw},\"nav_position_only\":true,\"soft_xy_tolerance_m\":${soft_xy}}"
  poll "$cid_nav" "ARRIVED" 480
  local cid_al="${tag}-${TS}-align"
  post "$cid_al" "aruco_align" "{\"aruco_marker_id\":${marker},\"align_mode\":\"center_only\",\"final\":\"return_approach\",\"docking_timeout_sec\":90,\"marker_search_on_miss\":true,\"marker_search_timeout_sec\":60,\"marker_seek_mode\":\"sweep\",\"marker_search_angular_speed\":0.12,\"dock_max_angular_speed\":0.12,\"wall_adjacent_approach\":true}"
  poll "$cid_al" "DONE" 180
  echo "======== ${tag} forward ${dist}m ========"
  manual_insert forward "$dist"
  echo "======== ${tag} backward ${dist}m ========"
  manual_insert backward "$dist"
}

# 중앙 슬롯: nav_position_only + center_only align + insert
visit_center_slot() {
  local tag="$1" wx="$2" wy="$3" wyaw="$4" marker="$5" dist="$6" soft_xy="${7:-0.10}"
  local cid_nav="${tag}-${TS}-nav"
  post "$cid_nav" "move_to_point" "{\"x\":${wx},\"y\":${wy},\"theta\":${wyaw},\"nav_position_only\":true,\"soft_xy_tolerance_m\":${soft_xy}}"
  poll "$cid_nav" "ARRIVED" 360
  local cid_al="${tag}-${TS}-align"
  post "$cid_al" "aruco_align" "{\"aruco_marker_id\":${marker},\"align_mode\":\"center_only\",\"final\":\"return_approach\",\"docking_timeout_sec\":90,\"marker_search_on_miss\":true,\"marker_search_timeout_sec\":45}"
  poll "$cid_al" "DONE" 180
  echo "======== ${tag} forward ${dist}m ========"
  manual_insert forward "$dist"
  echo "======== ${tag} backward ${dist}m ========"
  manual_insert backward "$dist"
}

park_wait2() {
  local tag="$1"
  local cid_nav="${tag}-${TS}-wait"
  # waypoint_id 없이 좌표만 — auto aruco_align 체인 방지
  post "$cid_nav" "move_to_point" '{"x":0.816,"y":0.006,"theta":1.571,"nav_position_only":true,"soft_xy_tolerance_m":0.12}'
  poll "$cid_nav" "ARRIVED" 360
  if [[ "${PARK_MODE:-hold}" == "nav_only" ]]; then
    echo "PARK_MODE=nav_only — hold align 생략"
    return 0
  fi
  local cid_park="${tag}-${TS}-park"
  post "$cid_park" "aruco_align" '{"aruco_marker_id":4,"align_mode":"center_only","final":"hold","center_tolerance_norm":0.03,"docking_timeout_sec":90,"marker_search_on_miss":true,"marker_search_timeout_sec":90}'
  poll "$cid_park" "DONE" 240
}

run_in1_b_wait2() {
  visit_wall_slot "in1" "-0.085" "0.006" "1.571" "0" "0.40" "0.22"
  visit_center_slot "b" "0.033" "-0.376" "0.0" "8" "0.375" "0.10"
  park_wait2 "wait2"
}

run_in2_b_wait2() {
  visit_wall_slot "in2" "0.234" "0.006" "1.571" "1" "0.40" "0.15"
  visit_center_slot "b" "0.033" "-0.376" "0.0" "8" "0.375" "0.10"
  park_wait2 "wait2"
}

run_in1_c_wait2() {
  visit_wall_slot "in1" "-0.085" "0.006" "1.571" "0" "0.40" "0.22"
  visit_center_slot "c" "1.239" "-0.631" "3.142" "10" "0.395" "0.10"
  park_wait2 "wait2"
}

run_in2_out1_wait2() {
  visit_wall_slot "in2" "0.234" "0.006" "1.571" "1" "0.40" "0.15"
  visit_wall_slot "out1" "1.131" "0.006" "1.571" "5" "0.39" "0.15"
  park_wait2 "wait2"
}

run_out2_a_wait2() {
  visit_wall_slot "out2" "1.45" "0.006" "1.571" "6" "0.39" "0.15"
  visit_center_slot "a" "0.019" "-0.618" "0.0" "7" "0.385" "0.10"
  park_wait2 "wait2"
}

run_scenario() {
  local name="$1"
  echo ""
  echo "########################################"
  echo "# SCENARIO: $name"
  echo "########################################"
  case "$name" in
    in1_b_wait2) run_in1_b_wait2 ;;
    in2_b_wait2) run_in2_b_wait2 ;;
    in1_c_wait2) run_in1_c_wait2 ;;
    in2_out1_wait2) run_in2_out1_wait2 ;;
    out2_a_wait2) run_out2_a_wait2 ;;
    *) echo "unknown scenario: $name" >&2; return 1 ;;
  esac
}

preflight() {
  echo "===== preflight scenario=$SCENARIO loops=$LOOPS ====="
  curl -sf "$BASE/movement-api/v1/robots/tb3_2/nav-state" | python3 -c "
import sys,json
d=json.load(sys.stdin)
age=d.get('pose_age_sec',999)
print(f'pose_age={age:.1f}s accepting={d.get(\"command_accepting\")} nav2_ready={d.get(\"nav2_ready\")} emergency={d.get(\"is_emergency\")}')
if not d.get('command_accepting'): raise SystemExit('FATAL: command_accepting=false — Nav2/bringup 확인')
if age>30: raise SystemExit('WARN: pose stale — AMCL/Nav2 확인')
"
  pgrep -f aruco_detector_node >/dev/null || echo "WARN: ArUco detector 미기동"
}

preflight

for (( loop=1; loop<=LOOPS; loop++ )); do
  echo ""
  echo "======== LOOP $loop/$LOOPS ========"
  C0="drive-${TS}-L${loop}-leave"
  post "$C0" "leave_dock" '{}'
  poll "$C0" "DONE" 120

  if [[ "$SCENARIO" == "all" ]]; then
    for s in in1_b_wait2 in2_b_wait2 in1_c_wait2 in2_out1_wait2 out2_a_wait2; do
      run_scenario "$s" || exit 1
      if [[ "$s" != "out2_a_wait2" ]]; then
        Cx="drive-${TS}-L${loop}-leave-${s}"
        post "$Cx" "leave_dock" '{}'
        poll "$Cx" "DONE" 120
      fi
    done
  else
    run_scenario "$SCENARIO"
  fi
done

echo ""
echo "======== DRIVE SCENARIO OK ($SCENARIO x$LOOPS) ========"
curl -sf "$BASE/movement-api/v1/health" | python3 -c "
import sys,json
p=json.load(sys.stdin).get('pose') or {}
print(f'END ({p.get(\"x\",0):.3f},{p.get(\"y\",0):.3f}) yaw={p.get(\"yaw\",0):.3f}')
"
