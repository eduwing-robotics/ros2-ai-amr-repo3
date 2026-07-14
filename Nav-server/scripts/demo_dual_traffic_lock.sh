#!/usr/bin/env bash
# Phase C 데모: 같은 warehouse_aisle 동시 move → 한쪽 409 WAITING_TRAFFIC
#
# 눈에 보이는 것:
#   1) 로봇2가 먼저 복도(창고 B)로 출발 → lock 잡힘
#   2) 로봇1이 같은 복도(창고 A)로 요청 → HTTP 409 (멈춤)
#   3) 로봇2 ARRIVED 후 lock 해제 → 로봇1 재시도 성공
#
# 전제:
#   - 두 스택 기동, RViz localize 완료
#   - 로봇1 대기1 근처 / 로봇2 대기2 근처 (또는 leave_dock 가능)
#   - 리프트 불필요 (move만)
#
# 사용:
#   scripts/demo_dual_traffic_lock.sh
#   SKIP_LEAVE=1 scripts/demo_dual_traffic_lock.sh   # 이미 대기장 밖이면
#
set -euo pipefail

API1="${API1:-http://127.0.0.1:8001}"
API2="${API2:-http://127.0.0.1:8002}"
R1="${R1:-tb3_1}"
R2="${R2:-tb3_2}"
TS=$(date +%s)
SKIP_LEAVE="${SKIP_LEAVE:-0}"

# 둘 다 warehouse_aisle 을 잡는 approach (zones.json semantic → aisle)
WP1="${WP1:-warehouse_a_approach}"   # 로봇1 목표
WP2="${WP2:-warehouse_b_approach}"   # 로봇2 목표 (먼저 출발)

log() { printf '[demo] %s\n' "$*"; }

show_locks() {
  echo "----- traffic locks -----"
  curl -sf "$API2/traffic/locks" 2>/dev/null | python3 -m json.tool 2>/dev/null \
    || curl -sf "$API1/traffic/locks" 2>/dev/null | python3 -m json.tool 2>/dev/null \
    || echo "(locks endpoint empty/unavailable)"
  echo "-------------------------"
}

post_move() {
  local api="$1" robot="$2" cid="$3" wp="$4"
  local code
  code=$(curl -s -o /tmp/dual_traffic_post.json -w '%{http_code}' -X POST "$api/robot-commands" \
    -H 'Content-Type: application/json' \
    -d "{\"command_id\":\"$cid\",\"task_id\":9901,\"robot_id\":\"$robot\",\"kind\":\"move_to_point\",\"params\":{\"waypoint_id\":\"$wp\",\"soft_xy_tolerance_m\":0.12},\"callback_url\":\"\"}")
  log "POST $robot → $wp  HTTP $code  ($cid)" >&2
  python3 -m json.tool /tmp/dual_traffic_post.json 2>/dev/null | head -40 >&2 || cat /tmp/dual_traffic_post.json >&2
  printf '%s' "$code"
}

poll() {
  local api="$1" cid="$2" want="$3" timeout="${4:-300}"
  local deadline=$((SECONDS + timeout))
  while (( SECONDS < deadline )); do
    local body state
    body=$(curl -sf "$api/robot-commands/$cid") || { sleep 2; continue; }
    state=$(echo "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('state',''))")
    log "$cid → $state"
    [[ "$state" == "$want" ]] && return 0
    [[ "$state" == "FAILED" || "$state" == "ABORTED" ]] && {
      echo "$body" | python3 -m json.tool
      return 1
    }
    sleep 3
  done
  log "TIMEOUT $cid"
  return 1
}

post_leave() {
  local api="$1" robot="$2" cid="$3"
  curl -s -o /tmp/dual_leave.json -w '' -X POST "$api/robot-commands" \
    -H 'Content-Type: application/json' \
    -d "{\"command_id\":\"$cid\",\"task_id\":9901,\"robot_id\":\"$robot\",\"kind\":\"leave_dock\",\"params\":{},\"callback_url\":\"\"}" >/dev/null
  poll "$api" "$cid" "DONE" 120 || true
}

echo "========================================"
echo "  DUAL TRAFFIC LOCK DEMO"
echo "  R1=$R1 $API1 → $WP1"
echo "  R2=$R2 $API2 → $WP2  (먼저 출발)"
echo "========================================"

for api in "$API1" "$API2"; do
  curl -sf "$api/movement-api/v1/health" >/dev/null || {
    log "ERROR: health fail $api — 스택 기동 확인"
    exit 1
  }
done
log "health OK"

if [[ "$SKIP_LEAVE" != "1" ]]; then
  log "leave_dock (hold면 빠져나옴) — 이미 밖이면 SKIP_LEAVE=1"
  post_leave "$API1" "$R1" "dual-${TS}-r1-leave"
  post_leave "$API2" "$R2" "dual-${TS}-r2-leave"
fi

show_locks

# 1) 로봇2 먼저 복도로
CID2="dual-${TS}-r2-aisle"
code2=$(post_move "$API2" "$R2" "$CID2" "$WP2")
if [[ "$code2" != "200" ]]; then
  log "ERROR: 로봇2가 먼저 lock을 못 잡음 (HTTP $code2). 다른 명령이 점유 중인지 확인."
  show_locks
  exit 1
fi

log "로봇2 주행 시작 — 3초 뒤 로봇1이 같은 aisle 요청"
sleep 3
show_locks

# 2) 로봇1 동시 요청 → 409 기대
CID1="dual-${TS}-r1-aisle"
code1=$(post_move "$API1" "$R1" "$CID1" "$WP1")
if [[ "$code1" == "409" ]]; then
  log "★★★ 성공 포인트: 로봇1 HTTP 409 WAITING_TRAFFIC (복도 lock) ★★★"
elif [[ "$code1" == "200" ]]; then
  log "WARNING: 409가 안 나옴 — segment가 안 겹쳤거나 lock이 약함. locks/waypoint 확인."
  show_locks
else
  log "UNEXPECTED HTTP $code1"
fi

# 3) 로봇2 도착 대기
log "로봇2 ARRIVED 대기..."
poll "$API2" "$CID2" "ARRIVED" 480
show_locks

# 4) 로봇1 재시도 (새 command_id)
CID1b="dual-${TS}-r1-aisle-retry"
log "로봇1 재시도 (새 command_id)..."
code1b=$(post_move "$API1" "$R1" "$CID1b" "$WP1")
if [[ "$code1b" != "200" ]]; then
  log "재시도도 실패 HTTP $code1b — 로봇2 dock이 lock을 아직 쥐고 있을 수 있음."
  log "로봇2를 대기장으로 빼거나, dock 없이 move만 끝난 뒤 다시."
  show_locks
  exit 1
fi
poll "$API1" "$CID1b" "ARRIVED" 480

echo ""
echo "======== DEMO OK ========"
echo "본 것: 로봇2 먼저 감 → 로봇1 409 → 로봇2 도착 후 로봇1 재시도 ARRIVED"
show_locks
