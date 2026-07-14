#!/usr/bin/env bash
# EKF ON 상태에서 zones.json 기준 각 approach → align → insert(dock_transfer) 실험
#
# 사용:
#   bash scripts/run_ekf_zone_approach_insert_test.sh
#   ZONES="inbound2,b,wait2" bash scripts/run_ekf_zone_approach_insert_test.sh
#
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BASE="${MOVEMENT_API_URL:-http://127.0.0.1:8002}"
ROBOT_ID="${ROBOT_ID:-tb3_2}"
TASK_ID="${TASK_ID:-9100}"
TS=$(date +%s)
export ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-5}"
LOG="${LOG:-/tmp/ekf_zone_insert_${TS}.log}"
ZONES="${ZONES:-inbound2,inbound1,outbound1,outbound2,a,b,c,d,wait1,wait2}"
FAIL=0
SKIP_LIFT="${SKIP_LIFT:-0}"

# waypoint_id|marker|kind|level|soft_xy_tol
# kind: dock= dock_transfer, hold= aruco_align hold
ALL_ZONES=(
  "inbound_slot_2_approach|1|dock|1|0.15"
  "inbound_slot_1_approach|0|dock|1|0.15"
  "outbound_slot_1_approach|5|dock|1|0.15"
  "outbound_slot_2_approach|6|dock|1|0.15"
  "warehouse_a_approach|7|dock|2|0.12"
  "warehouse_b_approach|8|dock|1|0.12"
  "warehouse_c_approach|10|dock|2|0.12"
  "warehouse_d_approach|9|dock|2|0.12"
  "vehicle_1_approach|3|hold|1|0.15"
  "vehicle_2_approach|4|hold|1|0.15"
)

poll() {
  local cid="$1" want="$2" timeout="${3:-480}"
  local deadline=$((SECONDS + timeout))
  while (( SECONDS < deadline )); do
    local body state msg
    body=$(curl -sf "$BASE/robot-commands/$cid") || return 1
    state=$(echo "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('state',''))")
    msg=$(echo "$body" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('message','')[:140])")
    echo "[$(date +%H:%M:%S)] $cid -> $state | $msg" | tee -a "$LOG"
    [[ "$state" == "$want" ]] && return 0
    [[ "$state" == "FAILED" || "$state" == "ABORTED" ]] && {
      echo "$body" | python3 -m json.tool | tee -a "$LOG"
      return 1
    }
    sleep 4
  done
  echo "TIMEOUT $cid" | tee -a "$LOG"
  return 1
}

post() {
  local cid="$1" kind="$2" params="$3"
  echo "" | tee -a "$LOG"
  echo "======== $kind ($cid) ========" | tee -a "$LOG"
  local code
  code=$(curl -s -o /tmp/ekf_zone_post.json -w '%{http_code}' -X POST "$BASE/robot-commands" \
    -H 'Content-Type: application/json' \
    -d "{\"command_id\":\"$cid\",\"task_id\":$TASK_ID,\"robot_id\":\"$ROBOT_ID\",\"kind\":\"$kind\",\"params\":$params,\"callback_url\":\"\"}")
  echo "HTTP $code" | tee -a "$LOG"
  python3 -m json.tool /tmp/ekf_zone_post.json | tee -a "$LOG"
  [[ "$code" == "200" ]]
}

nav_with_retry() {
  local wp="$1" tol="$2" prefix="$3" max="${4:-3}"
  local attempt=1
  while (( attempt <= max )); do
    local cid="${prefix}-n${attempt}"
    post "$cid" "move_to_point" "{\"waypoint_id\":\"$wp\",\"soft_xy_tolerance_m\":$tol}" || return 1
    if poll "$cid" "ARRIVED" 480; then return 0; fi
    echo "[nav_retry] $wp $attempt/$max" | tee -a "$LOG"
    ((attempt++)) || true
    sleep 5
  done
  return 1
}

slot_reverse_if_needed() {
  maybe_reverse_out_if_inserted
}

maybe_reverse_out_if_inserted() {
  CID_PREFIX="ekf-${TS}" bash "$ROOT/scripts/maybe_reverse_out_if_inserted.sh" | tee -a "$LOG"
}

zone_enabled() {
  local key="$1"
  [[ ",${ZONES}," == *",${key},"* ]]
}

run_zone() {
  local key="$1" wp="$2" marker="$3" kind="$4" level="$5" tol="$6"
  echo "" | tee -a "$LOG"
  echo "===== ZONE $key ($wp) marker=#$marker EKF insert test =====" | tee -a "$LOG"

  maybe_reverse_out_if_inserted

  if ! nav_with_retry "$wp" "$tol" "ekf-${TS}-${key}"; then
    echo "[FAIL] $key nav" | tee -a "$LOG"
    FAIL=$((FAIL + 1))
    slot_reverse_if_needed "$marker" || true
    return 1
  fi

  local cid="ekf-${TS}-${key}-dock"
  if [[ "$kind" == "hold" ]]; then
    post "$cid" "aruco_align" "{\"aruco_marker_id\":${marker},\"align_mode\":\"center_only\",\"final\":\"hold\",\"docking_timeout_sec\":90,\"marker_search_on_miss\":true,\"marker_search_timeout_sec\":90}"
    if poll "$cid" "DONE" 360; then
      echo "[OK] $key hold+insert" | tee -a "$LOG"
      post "ekf-${TS}-${key}-revout" "reverse_out" "{\"aruco_marker_id\":${marker}}" \
        && poll "ekf-${TS}-${key}-revout" "DONE" 120 || true
      return 0
    fi
  else
    local action="load"
    [[ "$level" == "2" ]] && action="unload"
    local dock_params="{\"aruco_marker_id\":${marker},\"action\":\"${action}\",\"level\":${level},\"docking_timeout_sec\":90,\"marker_search_on_miss\":true,\"marker_search_timeout_sec\":90}"
    if [[ "$SKIP_LIFT" == "1" ]]; then
      dock_params="{\"aruco_marker_id\":${marker},\"action\":\"${action}\",\"level\":${level},\"skip_lift\":true,\"post_insert_dwell_sec\":1.0,\"docking_timeout_sec\":90,\"marker_search_on_miss\":true,\"marker_search_timeout_sec\":90}"
    else
      dock_params="{\"aruco_marker_id\":${marker},\"action\":\"${action}\",\"level\":${level},\"lift_timeout_sec\":60,\"docking_timeout_sec\":90,\"marker_search_on_miss\":true,\"marker_search_timeout_sec\":90}"
    fi
    post "$cid" "dock_transfer" "$dock_params"
    if poll "$cid" "DONE" 420; then
      echo "[OK] $key dock_transfer" | tee -a "$LOG"
      return 0
    fi
    slot_reverse_if_needed "$marker" || true
  fi
  echo "[FAIL] $key dock" | tee -a "$LOG"
  FAIL=$((FAIL + 1))
  return 1
}

{
echo "===== EKF zone approach+insert test $(date -Is) ====="
echo "LOG=$LOG ZONES=$ZONES SKIP_LIFT=$SKIP_LIFT"
curl -sf "$BASE/movement-api/v1/robots/tb3_2/nav-state" | python3 -c "
import sys,json
d=json.load(sys.stdin)
p=d.get('pose')or{}
print(f'START pose=({p.get(\"x\",0):.3f},{p.get(\"y\",0):.3f}) accepting={d.get(\"command_accepting\")}')
"
pgrep -f aruco_detector_node >/dev/null && echo "detector=OK" || echo "detector=MISSING"
pgrep -f ekf_filter_node >/dev/null && echo "ekf=OK" || echo "ekf=MISSING"

if [[ "$SKIP_LIFT" != "1" ]]; then
  bash "$ROOT/scripts/test_lift_tb3_2.sh" home || true
  sleep 6
else
  echo "[skip_lift] lift HOME preflight skipped" | tee -a "$LOG"
fi

for row in "${ALL_ZONES[@]}"; do
  IFS='|' read -r wp marker kind level tol <<<"$row"
  case "$wp" in
    inbound_slot_2_approach) key=inbound2 ;;
    inbound_slot_1_approach) key=inbound1 ;;
    outbound_slot_1_approach) key=outbound1 ;;
    outbound_slot_2_approach) key=outbound2 ;;
    warehouse_a_approach) key=a ;;
    warehouse_b_approach) key=b ;;
    warehouse_c_approach) key=c ;;
    warehouse_d_approach) key=d ;;
    vehicle_1_approach) key=wait1 ;;
    vehicle_2_approach) key=wait2 ;;
    *) key="$wp" ;;
  esac
  zone_enabled "$key" || continue
  run_zone "$key" "$wp" "$marker" "$kind" "$level" "$tol" || true
done

echo ""
echo "===== SUMMARY fail_count=$FAIL log=$LOG ====="
ls -1t "$ROOT/worklog/insert_snapshots/"*$(date +%Y%m%d)*.txt 2>/dev/null | head -8 | while read -r f; do
  echo "--- $(basename "$f") ---"
  head -2 "$f"
done
} 2>&1 | tee -a "$LOG"

exit "$FAIL"
