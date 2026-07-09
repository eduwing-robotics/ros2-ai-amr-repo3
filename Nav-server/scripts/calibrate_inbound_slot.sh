#!/usr/bin/env bash
# tb3_2: robot2_map 기준 waypoint 캘리브레이션 (map frame = Nav2 robot2_map)
# Usage:
#   SLOT=inbound_slot_1 MARKER_ID=0 scripts/calibrate_inbound_slot.sh preview
#   SLOT=inbound_slot_1 MARKER_ID=0 scripts/calibrate_inbound_slot.sh apply-geometry
#   SLOT=inbound_slot_1 MARKER_ID=0 scripts/calibrate_inbound_slot.sh move
#   SLOT=inbound_slot_1 MARKER_ID=0 scripts/calibrate_inbound_slot.sh align
#   SLOT=inbound_slot_1 scripts/calibrate_inbound_slot.sh record
set -eo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SLOT="${SLOT:-inbound_slot_1}"
MARKER_ID="${MARKER_ID:-0}"
DOMAIN="${ROS_DOMAIN_ID:-5}"
BASE_URL="${BASE_URL:-http://127.0.0.1:8002}"
STANDOFF_M="${STANDOFF_M:-0.30}"
SAMPLES="${SAMPLES:-5}"
CENTER_TOL="${CENTER_TOL:-0.03}"
MAX_XY_DRIFT_M="${MAX_XY_DRIFT_M:-0.02}"

set +u
source /opt/ros/jazzy/setup.bash 2>/dev/null || true
set -u
export ROS_DOMAIN_ID="$DOMAIN"

case "${SLOT}" in
  inbound_slot_1) APPROACH_WP="${APPROACH_WP:-inbound_slot_1_approach}"; MARKER_ID="${MARKER_ID:-0}" ;;
  inbound_slot_2) APPROACH_WP="${APPROACH_WP:-inbound_slot_2_approach}"; MARKER_ID="${MARKER_ID:-1}" ;;
  *) APPROACH_WP="${APPROACH_WP:-${SLOT}_approach}" ;;
esac

cmd="${1:-preview}"

preview() {
  echo "===== $SLOT (marker $MARKER_ID) — robot2_map frame ====="
  python3 "$SCRIPT_DIR/compute_approach_from_marker.py" "$SLOT" --standoff-m "$STANDOFF_M"
  echo ""
  echo "현재 로봇 pose (robot2_map / tf map):"
  curl -sf "$BASE_URL/movement-api/v1/health" 2>/dev/null | python3 -c "
import sys,json
d=json.load(sys.stdin)
p=d.get('pose') or {}
print(f\"  online={d.get('robot_online')} localized={d.get('localized')}\")
print(f\"  x={p.get('x')} y={p.get('y')} yaw={p.get('yaw')}\")
" || echo "  (Movement API :8002 unreachable — nav-servers 재시작 필요)"
  echo ""
  echo "다음 단계:"
  echo "  1) apply-geometry  — 마커+standoff로 approach 1차값 zones.json 반영"
  echo "  2) move            — move_to_point(approach) 전송"
  echo "  3) align           — aruco_align(marker=$MARKER_ID) 정밀 정렬"
  echo "  4) record          — 정렬 직후 pose를 approach로 저장 (--samples $SAMPLES)"
}

apply_geometry() {
  python3 "$SCRIPT_DIR/compute_approach_from_marker.py" "$SLOT" --standoff-m "$STANDOFF_M" --apply
}

move_approach() {
  local x y theta
  read -r x y theta < <(python3 -c "
import json
from pathlib import Path
z=json.loads(Path('$ROOT/map/zones.json').read_text())
w=z['waypoints']['$APPROACH_WP']
print(w['x'], w['y'], w['theta'])
")
  local cid="calib-${SLOT}-move-$(date +%Y%m%dT%H%M%S)"
  echo "[calib] move_to_point $APPROACH_WP ($x, $y, $theta)"
  curl -sf -X POST "$BASE_URL/robot-commands" -H 'Content-Type: application/json' -d "{
    \"command_id\":\"$cid\",
    \"task_id\":0,
    \"robot_id\":\"tb3_2\",
    \"kind\":\"move_to_point\",
    \"params\":{\"waypoint_id\":\"$APPROACH_WP\",\"x\":$x,\"y\":$y,\"yaw\":$theta},
    \"callback_url\":\"http://127.0.0.1:8088/api/v1/movement/command-events\"
  }" | python3 -m json.tool
  echo "[calib] Nav pane에서 ARRIVED 확인 후: $0 align"
}

align_aruco() {
  local cid="calib-${SLOT}-align-$(date +%Y%m%dT%H%M%S)"
  echo "[calib] aruco_align marker=$MARKER_ID (center_only)"
  curl -sf -X POST "$BASE_URL/robot-commands" -H 'Content-Type: application/json' -d "{
    \"command_id\":\"$cid\",
    \"task_id\":0,
    \"robot_id\":\"tb3_2\",
    \"kind\":\"aruco_align\",
    \"params\":{
      \"aruco_marker_id\":$MARKER_ID,
      \"final\":\"return_approach\",
      \"align_mode\":\"center_only\",
      \"center_tolerance_norm\":$CENTER_TOL,
      \"docking_timeout_sec\":35
    },
    \"callback_url\":\"http://127.0.0.1:8088/api/v1/movement/command-events\"
  }" | python3 -m json.tool
  echo "[calib] DONE 확인 후: $0 record"
}

record_approach() {
  echo "[calib] pose drift check (max xy=${MAX_XY_DRIFT_M}m)..."
  python3 -c "
import json, math, sys, urllib.request
zones=json.load(open('$ROOT/map/zones.json'))
wp=zones['waypoints']['$APPROACH_WP']
health=json.load(urllib.request.urlopen('$BASE_URL/movement-api/v1/health'))
pose=health.get('pose') or {}
dx=float(pose.get('x',0))-float(wp['x'])
dy=float(pose.get('y',0))-float(wp['y'])
drift=math.hypot(dx,dy)
print(f\"  saved=({wp['x']},{wp['y']}) current=({pose.get('x'):.3f},{pose.get('y'):.3f}) drift={drift:.3f}m\")
if drift > float('$MAX_XY_DRIFT_M'):
    print(f'[calib] ERROR: xy drift {drift:.3f}m > $MAX_XY_DRIFT_M — Nav2 approach 부정확, record 중단', file=sys.stderr)
    sys.exit(1)
"
  echo "[calib] recording $APPROACH_WP (samples=$SAMPLES, theta_only)..."
  python3 "$SCRIPT_DIR/record_waypoint_pose.py" "$APPROACH_WP" --source tf --samples "$SAMPLES" --theta-only --max-xy-error-m "$MAX_XY_DRIFT_M"
  echo "[calib] 완료. preview:"
  python3 "$SCRIPT_DIR/compute_approach_from_marker.py" "$SLOT" --standoff-m "$STANDOFF_M"
}

poll_cmd() {
  local cid="$1" want="$2" max="${3:-300}"
  local deadline=$((SECONDS + max))
  echo "[calib] poll $cid -> $want (max ${max}s)"
  while (( SECONDS < deadline )); do
    local state
    state="$(curl -sf "$BASE_URL/robot-commands/$cid" 2>/dev/null | python3 -c "import sys,json; print(json.load(sys.stdin).get('state',''))" 2>/dev/null || echo "")"
    if [[ "$state" == "$want" ]]; then
      echo "[calib] OK $cid -> $state"
      return 0
    fi
    if [[ "$state" == "FAILED" || "$state" == "ABORTED" ]]; then
      curl -sf "$BASE_URL/robot-commands/$cid" | python3 -m json.tool
      return 1
    fi
    sleep 2
  done
  echo "[calib] TIMEOUT $cid" >&2
  return 1
}

run_all() {
  preview
  echo ""
  echo "===== MOVE ====="
  local x y theta cid_move cid_align
  read -r x y theta < <(python3 -c "
import json
from pathlib import Path
w=json.loads(Path('$ROOT/map/zones.json').read_text())['waypoints']['$APPROACH_WP']
print(w['x'], w['y'], w['theta'])
")
  cid_move="calib-${SLOT}-move-$(date +%Y%m%dT%H%M%S)"
  echo "[calib] move_to_point $APPROACH_WP ($x, $y, $theta)"
  curl -sf -X POST "$BASE_URL/robot-commands" -H 'Content-Type: application/json' -d "{
    \"command_id\":\"$cid_move\",
    \"task_id\":0,
    \"robot_id\":\"tb3_2\",
    \"kind\":\"move_to_point\",
    \"params\":{\"waypoint_id\":\"$APPROACH_WP\",\"x\":$x,\"y\":$y,\"yaw\":$theta},
    \"callback_url\":\"\"
  }" | python3 -m json.tool
  poll_cmd "$cid_move" "ARRIVED" || return 1
  echo ""
  echo "===== ALIGN (center_only) ====="
  cid_align="calib-${SLOT}-align-$(date +%Y%m%dT%H%M%S)"
  curl -sf -X POST "$BASE_URL/robot-commands" -H 'Content-Type: application/json' -d "{
    \"command_id\":\"$cid_align\",
    \"task_id\":0,
    \"robot_id\":\"tb3_2\",
    \"kind\":\"aruco_align\",
    \"params\":{
      \"aruco_marker_id\":$MARKER_ID,
      \"final\":\"return_approach\",
      \"align_mode\":\"center_only\",
      \"center_tolerance_norm\":$CENTER_TOL,
      \"docking_timeout_sec\":35
    },
    \"callback_url\":\"\"
  }" | python3 -m json.tool
  poll_cmd "$cid_align" "DONE" || return 1
  echo ""
  echo "===== RECORD ====="
  record_approach
}

case "$cmd" in
  preview|status) preview ;;
  apply-geometry|geometry) apply_geometry ;;
  move) move_approach ;;
  align|aruco) align_aruco ;;
  record|save) record_approach ;;
  all|run) run_all ;;
  *)
    echo "usage: $0 {preview|apply-geometry|move|align|record|all}" >&2
    exit 2
    ;;
esac
