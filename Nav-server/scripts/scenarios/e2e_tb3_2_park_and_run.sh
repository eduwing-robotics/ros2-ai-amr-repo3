#!/usr/bin/env bash
#
# tb3_2: 대기장 주차 → leave_dock 후진 → E2E 시나리오
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

NAV_BASE="${NAV_BASE:-http://127.0.0.1:8002}"
ROBOT_ID="${ROBOT_ID:-tb3_2}"
TASK_ID="${TASK_ID:-9001}"
POLL_SEC="${POLL_SEC:-3}"
POLL_MAX="${POLL_MAX:-360}"
TS="$(date +%s)"
DOMAIN="${DOMAIN:-5}"
ROBOT_SSH="${ROBOT_SSH:-musk@192.168.30.102}"
ROBOT_PW="${ROBOT_PW:?Set ROBOT_PW in the environment}"
LOG="$ROOT/logs/e2e_park_and_run_${TS}.log"

exec > >(tee -a "$LOG") 2>&1

log() { printf '[park-e2e] %s\n' "$*"; }

wait_aruco() {
  local max_wait="${ARUCO_WAIT_SEC:-20}"
  local deadline=$((SECONDS + max_wait))
  log "ArUco detector 대기 (최대 ${max_wait}s)..."
  while (( SECONDS < deadline )); do
    if curl -sf "${NAV_BASE}/movement-api/v1/aruco/latest" 2>/dev/null \
      | python3 -c "import sys,json; d=json.load(sys.stdin).get('detections',[]); sys.exit(0 if d else 1)" 2>/dev/null; then
      log "ArUco 검출 OK"
      return 0
    fi
    export ROS_DOMAIN_ID="${DOMAIN:-5}"
    if timeout 2 ros2 topic info /mission/tb3_2/aruco/detections 2>/dev/null | grep -q "Publisher count: [1-9]"; then
      log "ArUco detector publisher OK (마커는 approach 이동 후 검출 예정)"
      return 0
    fi
    sleep 3
  done
  log "WARNING: ArUco 미검출 — approach 이동 후 align 시도"
  return 0
}

start_camera_sbc() {
  log "로봇 SBC 카메라 기동: $ROBOT_SSH"
  if command -v sshpass >/dev/null 2>&1 && [[ -n "$ROBOT_PW" ]]; then
    sshpass -p "$ROBOT_PW" ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout=8 \
      "$ROBOT_SSH" "export ROS_DOMAIN_ID=$DOMAIN BRINGUP_WAIT_SEC=5; bash -s" \
      < "$ROOT/scripts/robot_sbc/start_camera.sh" &
  else
    ssh -o StrictHostKeyChecking=accept-new "$ROBOT_SSH" \
      "export ROS_DOMAIN_ID=$DOMAIN BRINGUP_WAIT_SEC=5; bash -s" \
      < "$ROOT/scripts/robot_sbc/start_camera.sh" &
  fi
  sleep 8
}

start_detector() {
  if pgrep -f "aruco_detector_node.py" >/dev/null 2>&1; then
    log "detector 이미 실행 중"
    return 0
  fi
  log "Nav PC ArUco detector 기동 (system python3 — cv2 호환)"
  (
    cd "$ROOT"
    export ROS_DOMAIN_ID="$DOMAIN"
    PYTHON_BIN=python3 START_CAMERA_LAUNCH=0 START_CAMERA_RELAY=0 ROBOT_ID=tb3_burger_02 \
      bash scripts/run_pi_camera_aruco.sh
  ) &
  sleep 5
}

post_command() {
  local cmd_id="$1" kind="$2" params_json="$3"
  curl -fsS -X POST "${NAV_BASE}/robot-commands" \
    -H "Content-Type: application/json" \
    -d "$(cat <<JSON
{"command_id":"${cmd_id}","task_id":${TASK_ID},"robot_id":"${ROBOT_ID}","kind":"${kind}","dry_run":false,"params":${params_json},"callback_url":""}
JSON
)" | python3 -m json.tool
}

poll_until() {
  local cmd_id="$1" want_state="$2"
  local deadline=$((SECONDS + POLL_MAX))
  log "poll ${cmd_id} -> ${want_state}"
  while (( SECONDS < deadline )); do
    local body state stage reason
    body="$(curl -fsS "${NAV_BASE}/robot-commands/${cmd_id}" 2>/dev/null || echo '{}')"
    state="$(printf '%s' "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('state',''))" 2>/dev/null || echo "")"
    stage="$(printf '%s' "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('stage',''))" 2>/dev/null || echo "")"
    if [[ "$state" == "$want_state" ]]; then
      log "OK ${cmd_id} ${state} stage=${stage}"
      return 0
    fi
    if [[ "$state" == "FAILED" || "$state" == "ABORTED" ]]; then
      reason="$(printf '%s' "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('reason',''))" 2>/dev/null || echo "")"
      log "FAIL ${cmd_id} ${state} stage=${stage} reason=${reason}"
      printf '%s' "$body" | python3 -m json.tool
      return 1
    fi
    sleep "$POLL_SEC"
  done
  log "TIMEOUT ${cmd_id}"
  return 1
}

log "=== PREP: camera + detector ==="
if [[ "${SKIP_PREP:-0}" != "1" ]]; then
  start_camera_sbc
  start_detector
  wait_aruco
else
  log "SKIP_PREP=1 — 기존 스택 사용"
  wait_aruco
fi

CMD_MOVE="park-${TS}-to-vehicle2"
CMD_ALIGN="park-${TS}-align-hold"
CMD_LEAVE="park-${TS}-leave-dock"

log "=== STEP A: vehicle_2_approach 이동 ==="
post_command "$CMD_MOVE" "move_to_point" '{"waypoint_id": "vehicle_2_approach"}'
poll_until "$CMD_MOVE" "ARRIVED"

log "=== STEP B: ArUco 주차 (marker 4, hold) ==="
post_command "$CMD_ALIGN" "aruco_align" '{"aruco_marker_id": 4, "final": "hold", "align_mode": "center_only"}'
poll_until "$CMD_ALIGN" "DONE"

log "=== STEP C: leave_dock 후진 이탈 ==="
post_command "$CMD_LEAVE" "leave_dock" '{}'
poll_until "$CMD_LEAVE" "DONE"

log "=== STEP D: E2E 시나리오 시작 ==="
export TS
bash "$SCRIPT_DIR/e2e_tb3_2_factory_run.sh"
