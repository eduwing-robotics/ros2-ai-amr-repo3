#!/usr/bin/env bash
# 책임: 실로봇 사전점검과 HW-01~12 증적 수집을 운영자에게 안내한다.
# 소유: 검증 기록. 비책임: 로봇 이동·ESTOP·서버 재시작 같은 위험 동작 실행.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_BASE="${LMS_ACCEPTANCE_API_BASE:-http://localhost:8088/api/v1}"
UI_BASE="${LMS_ACCEPTANCE_UI_BASE:-http://localhost:8088}"
OPERATOR="${LMS_ACCEPTANCE_OPERATOR:-${USER:-unknown}}"
ROBOT_ID="${LMS_ACCEPTANCE_ROBOT_ID:-}"
RUN_ID="$(date '+%Y%m%d-%H%M%S')"
EVIDENCE_DIR=""
SKIP_LOCAL=0
PREFLIGHT_ONLY=0
DRY_RUN=0

usage() {
  cat <<'EOF'
Usage: ./scripts/robot_acceptance.sh [options]

Options:
  --api-base URL       Main API base (default: http://localhost:8088/api/v1)
  --ui-base URL        Operator UI base (default: http://localhost:8088)
  --operator NAME      Verifier recorded in the evidence
  --robot-id ID        Target robot recorded in the evidence
  --evidence-dir DIR   Evidence output directory
  --skip-local         Skip check.sh all (only if already passed on this commit)
  --preflight-only     Stop after live, read-only readiness checks
  --dry-run            Print the plan without calling servers or moving a robot
  -h, --help           Show this help

The scenario phase is interactive and never disconnects services, sends ESTOP, moves
the robot, creates work orders, or restarts Main by itself. Perform those actions in
the operator UI under the site's safety procedure, then record PASS/FAIL/UNVERIFIED.
EOF
}

while (($#)); do
  case "$1" in
    --api-base) API_BASE="${2:?missing URL}"; shift 2 ;;
    --ui-base) UI_BASE="${2:?missing URL}"; shift 2 ;;
    --operator) OPERATOR="${2:?missing name}"; shift 2 ;;
    --robot-id) ROBOT_ID="${2:?missing robot ID}"; shift 2 ;;
    --evidence-dir) EVIDENCE_DIR="${2:?missing directory}"; shift 2 ;;
    --skip-local) SKIP_LOCAL=1; shift ;;
    --preflight-only) PREFLIGHT_ONLY=1; shift ;;
    --dry-run) DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "[robot-acceptance] unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

EVIDENCE_DIR="${EVIDENCE_DIR:-$ROOT/.bootstrap/robot-acceptance/$RUN_ID}"
RESULTS="$EVIDENCE_DIR/results.tsv"

SCENARIOS=(
  "HW-01|1층 정상 입고|도킹·상차 완료 후 재고가 정확히 한 번 증가한다."
  "HW-02|2층 정상 입고|2층 경로·도킹 완료 후 재고가 정확히 한 번 증가한다."
  "HW-03|1층 정상 출고|도킹·하역 완료 후 재고가 정확히 한 번 감소한다."
  "HW-04|2층 정상 출고|2층 경로·도킹 완료 후 재고가 정확히 한 번 감소한다."
  "HW-05|Precision waypoint|params에는 waypoint_id만 있고 step_actions가 nav2_pose,aruco_align,wait,aruco_align이다."
  "HW-06|Movement 단절|조작이 차단되고 task·command ID와 실패 원인이 보존되며 임의 재개하지 않는다."
  "HW-07|물리 ESTOP|로봇이 실제 정지하고 UI 조작이 차단되며 해제 후 자동 재개하지 않는다."
  "HW-08|Callback 정합성|token·command·robot·event ID/sequence가 일치하고 중복·역순 callback이 업무를 중복 반영하지 않는다."
  "HW-09|적재 중 복구|cargo 확인 전 실행이 차단되고 확인 후 safe_move 또는 manual_abort만 수행한다."
  "HW-10|Main 재시작|진행 task와 Movement command가 재동기화되고 중복 명령·재고 반영이 없다."
  "HW-11|Vision stale|영상 상태와 evidence 오류가 기록되고 물류·이동 안전 규칙이 유지된다."
  "HW-12|중복 삽입 방지|자동 입출고에 dock_transfer가 없고 ARRIVED 전에 다음 command가 전송되지 않는다."
)

if ((DRY_RUN)); then
  echo "[robot-acceptance] DRY RUN"
  echo "API=$API_BASE UI=$UI_BASE operator=$OPERATOR robot=${ROBOT_ID:-not-set}"
  printf '%s\n' "${SCENARIOS[@]}"
  exit 0
fi

[[ -n "$ROBOT_ID" ]] || { echo "[robot-acceptance] ERROR: --robot-id is required for live preflight" >&2; exit 2; }

mkdir -p "$EVIDENCE_DIR"
printf 'case_id\tname\tverdict\twork_order_id\ttask_id\tcommand_id\tfinal_task_status\tinventory_before\tinventory_after\tnote\n' > "$RESULTS"
cat > "$EVIDENCE_DIR/run.env.log" <<EOF
run_id=$RUN_ID
started_at=$(date --iso-8601=seconds)
git_commit=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)
git_dirty=$(git -C "$ROOT" status --porcelain 2>/dev/null | wc -l)
api_base=$API_BASE
ui_base=$UI_BASE
operator=$OPERATOR
robot_id=${ROBOT_ID:-not-set}
skip_local=$SKIP_LOCAL
EOF

need() {
  command -v "$1" >/dev/null 2>&1 || { echo "[robot-acceptance] ERROR: $1 is required" >&2; exit 2; }
}
need curl
need python3

# API 실패도 증적으로 남기며 snapshot 수집 자체는 판정을 변경하지 않는다.
snapshot() {
  local label="$1" dir path name
  dir="$EVIDENCE_DIR/$label"
  mkdir -p "$dir"
  for path in \
    "status" "system/external-config" "work-orders?limit=200" \
    "tasks?limit=200" "inventory" "events?limit=200" \
    "item-change-logs?limit=200" "evidence-events?limit=200" \
    "movement-commands?limit=200" "tasks/recovery/awaiting-operator?limit=100"; do
    name="${path//[\/?&=]/_}"
    curl -sS --connect-timeout 3 --max-time 15 \
      -w '\nHTTP_STATUS:%{http_code}\n' "$API_BASE/$path" \
      > "$dir/$name.json.log" 2> "$dir/$name.stderr.log" || true
  done
}

# PASS는 운영자 판정 집계이며 물리 동작의 자동 검증 결과를 의미하지 않는다.
write_report() {
  [[ -f "$RESULTS" ]] || return 0
  local report="$EVIDENCE_DIR/report.txt" pass fail unverified recorded
  pass=$(awk -F '\t' 'NR>1 && $3=="PASS" {n++} END {print n+0}' "$RESULTS")
  fail=$(awk -F '\t' 'NR>1 && $3=="FAIL" {n++} END {print n+0}' "$RESULTS")
  unverified=$(awk -F '\t' 'NR>1 && $3=="UNVERIFIED" {n++} END {print n+0}' "$RESULTS")
  recorded=$(awk 'END {print NR > 0 ? NR-1 : 0}' "$RESULTS")
  {
    echo "REAL ROBOT ACCEPTANCE REPORT"
    echo "run_id: $RUN_ID"
    echo "finished_at: $(date --iso-8601=seconds)"
    echo "operator: $OPERATOR"
    echo "robot_id: ${ROBOT_ID:-not-set}"
    echo "git_commit: $(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
    echo "result: PASS=$pass FAIL=$fail UNVERIFIED=$unverified RECORDED=$recorded/${#SCENARIOS[@]}"
    echo
    column -t -s $'\t' "$RESULTS" 2>/dev/null || sed 's/\t/ | /g' "$RESULTS"
  } > "$report"
  echo "[robot-acceptance] report: $report"
}
trap 'write_report' EXIT

echo "[robot-acceptance] evidence=$EVIDENCE_DIR"
if ((SKIP_LOCAL == 0)); then
  echo "[robot-acceptance] local gates: docs, hygiene, backend, frontend, UX, PostgreSQL"
  bash "$ROOT/scripts/check.sh" all 2>&1 | tee "$EVIDENCE_DIR/local-gates.log"
else
  echo "[robot-acceptance] WARN: local gates skipped by operator" | tee "$EVIDENCE_DIR/local-gates.log"
fi

echo "[robot-acceptance] live preflight (read-only)"
curl -fsS --connect-timeout 3 --max-time 10 "${API_BASE%/api/v1}/health" > "$EVIDENCE_DIR/health.json.log"
curl -fsS --connect-timeout 3 --max-time 10 "${API_BASE%/api/v1}/ready" > "$EVIDENCE_DIR/ready.json.log"
LMS_VERIFY_API_BASE="$API_BASE" bash "$ROOT/scripts/check.sh" operator 2>&1 | tee "$EVIDENCE_DIR/operator-preflight.log"
curl -fsS --connect-timeout 3 --max-time 15 -X POST "$API_BASE/comm/probe/movement" > "$EVIDENCE_DIR/movement-probe.json.log"
curl -fsS --connect-timeout 3 --max-time 15 -X POST "$API_BASE/comm/probe/camera" > "$EVIDENCE_DIR/camera-probe.json.log"
curl -fsS --connect-timeout 3 --max-time 15 "$API_BASE/system/external-config" > "$EVIDENCE_DIR/external-config.json.log"
python3 -c 'import json,sys; h=json.load(open(sys.argv[1]))["movement_health"].get(sys.argv[2]); assert h, "target robot missing"; assert h.get("ok") and h.get("robot_online") is not False, "Movement offline"; assert h.get("command_accepting") is not False, "Movement rejects commands"; assert h.get("localized") is not False, "robot not localized"' "$EVIDENCE_DIR/movement-probe.json.log" "$ROBOT_ID"
python3 -c 'import json,sys; assert json.load(open(sys.argv[1])).get("ok"), "Vision/camera preflight failed"' "$EVIDENCE_DIR/camera-probe.json.log"
python3 -c 'import json,sys; assert json.load(open(sys.argv[1]))["movement"].get("callback_auth_required"), "Movement callback token is empty"' "$EVIDENCE_DIR/external-config.json.log"
snapshot "preflight"

if ((PREFLIGHT_ONLY)); then
  echo "[robot-acceptance] preflight complete; scenario verdicts remain UNVERIFIED"
  for row in "${SCENARIOS[@]}"; do
    IFS='|' read -r id name expected <<< "$row"
    printf '%s\t%s\tUNVERIFIED\t\t\t\t\t\t\tpreflight-only\n' "$id" "$name" >> "$RESULTS"
  done
  exit 0
fi

cat <<EOF

현장 실행 전 확인:
  - 시험 구역을 통제하고 하드웨어 ESTOP 담당자를 배치하십시오.
  - UI를 여십시오: $UI_BASE/operate/control
  - 운영 DB 백업과 시험용 품목·슬롯·수량을 확인하십시오.
  - 각 단계는 UI에서 수행합니다. 이 스크립트는 로봇 명령을 보내지 않습니다.
EOF
read -r -p "계속하려면 현장 책임자가 READY를 입력하십시오: " ready
[[ "$ready" == "READY" ]] || { echo "[robot-acceptance] aborted before motion"; exit 1; }

for row in "${SCENARIOS[@]}"; do
  IFS='|' read -r id name expected <<< "$row"
  echo
  echo "[$id] $name"
  echo "통과 조건: $expected"
  case "$id" in
    HW-01|HW-02|HW-03|HW-04) echo "UI에서 해당 층의 작업을 생성·시작하고 완료까지 관찰하십시오. 재고 전후와 ID를 확인합니다." ;;
    HW-05) echo "Main payload가 waypoint_id만 포함하고 Movement 조회의 step_actions가 nav2_pose,aruco_align,wait,aruco_align인지 확인하십시오." ;;
    HW-06) echo "안전 정지 상태에서 Movement 연결을 차단하고 UI 차단·원인 보존을 확인한 뒤 연결을 복구하십시오." ;;
    HW-07) echo "저속 안전 시험 중 물리 ESTOP을 작동하십시오. 위험 제거·해제 후 자동 재개가 없는지 확인하십시오." ;;
    HW-08) echo "Movement callback 로그와 Main command trace를 비교하고 동일 event 재전송 시 1회 반영을 확인하십시오." ;;
    HW-09) echo "시험 화물 적재 상태에서 안전 중단 후 복구 패널의 cargo 확인·preview·execute 순서를 확인하십시오." ;;
    HW-10) echo "진행 중 안전한 구간에서 승인된 절차로 Main만 재시작하고 task/command 재동기화를 확인하십시오." ;;
    HW-11) echo "Vision 입력을 stale 상태로 만들고 UI·evidence 오류를 확인한 뒤 Vision을 복구하십시오." ;;
    HW-12) echo "자동 입출고 payload와 command trace에서 중복 dock_transfer 및 ARRIVED 전 조기 전송이 없는지 확인하십시오." ;;
  esac

  snapshot "${id}-before"
  read -r -p "시험 수행 후 Enter를 누르십시오 (미수행도 Enter): " _
  snapshot "${id}-after"
  read -r -p "work order ID (없으면 빈 값): " work_order_id
  read -r -p "task ID (없으면 빈 값): " task_id
  read -r -p "Movement command ID (없으면 빈 값): " command_id
  read -r -p "최종 task 상태 (예: DONE, 없으면 빈 값): " final_task_status
  read -r -p "대상 재고 전 값 (해당 없으면 빈 값): " inventory_before
  read -r -p "대상 재고 후 값 (해당 없으면 빈 값): " inventory_after
  if [[ -n "$command_id" ]]; then
    curl -sS --connect-timeout 3 --max-time 15 \
      -w '\nHTTP_STATUS:%{http_code}\n' "$API_BASE/movement/commands/$command_id/trace" \
      > "$EVIDENCE_DIR/${id}-command-trace.json.log" 2> "$EVIDENCE_DIR/${id}-command-trace.stderr.log" || true
  fi

  while true; do
    read -r -p "판정 [p=PASS, f=FAIL, u=UNVERIFIED]: " verdict
    case "${verdict,,}" in
      p) verdict=PASS; break ;;
      f) verdict=FAIL; break ;;
      u|'') verdict=UNVERIFIED; break ;;
      *) echo "p, f, u 중 하나를 입력하십시오." ;;
    esac
  done
  read -r -p "근거/관찰 메모: " note
  note="${note//$'\t'/ }"
  note="${note//$'\n'/ }"
  printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\t%s\n' \
    "$id" "$name" "$verdict" "$work_order_id" "$task_id" "$command_id" \
    "$final_task_status" "$inventory_before" "$inventory_after" "$note" >> "$RESULTS"
done

snapshot "final"
echo "[robot-acceptance] all scenarios recorded"
fail_count=$(awk -F '\t' 'NR>1 && $3=="FAIL" {n++} END {print n+0}' "$RESULTS")
unverified_count=$(awk -F '\t' 'NR>1 && $3=="UNVERIFIED" {n++} END {print n+0}' "$RESULTS")
if ((fail_count > 0 || unverified_count > 0)); then
  echo "[robot-acceptance] acceptance incomplete: FAIL=$fail_count UNVERIFIED=$unverified_count" >&2
  exit 1
fi
echo "[robot-acceptance] PASS: all real-robot scenarios passed"
