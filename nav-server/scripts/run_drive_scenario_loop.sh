#!/usr/bin/env bash
# 여러 주행 시나리오를 순차·반복 실행 (리프트 없음)
#
# Usage:
#   bash scripts/run_drive_scenario_loop.sh
#   LOOPS=2 SCENARIOS="in2_b_wait2 in1_c_wait2" bash scripts/run_drive_scenario_loop.sh
#   PARK_MODE=nav_only bash scripts/run_drive_scenario_loop.sh   # 대기장 nav만 (hold 생략)
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOOPS="${LOOPS:-1}"
SCENARIOS="${SCENARIOS:-in1_b_wait2 in2_b_wait2 in1_c_wait2 in2_out1_wait2 out2_a_wait2}"
PARK_MODE="${PARK_MODE:-hold}"
LOG_DIR="${LOG_DIR:-$ROOT/logs}"
mkdir -p "$LOG_DIR"
TS=$(date +%s)
MASTER_LOG="$LOG_DIR/drive_loop_${TS}.log"

exec > >(tee -a "$MASTER_LOG") 2>&1

echo "===== drive scenario loop loops=$LOOPS park=$PARK_MODE ====="
echo "scenarios: $SCENARIOS"
echo "master log: $MASTER_LOG"

for (( loop=1; loop<=LOOPS; loop++ )); do
  echo ""
  echo "######## LOOP $loop/$LOOPS ########"
  for scenario in $SCENARIOS; do
    echo ""
    echo ">>>> RUN $scenario (loop $loop) <<<<"
    if ! SCENARIO="$scenario" LOOPS=1 PARK_MODE="$PARK_MODE" bash "$ROOT/scripts/run_drive_insert_scenario.sh"; then
      echo "FAILED: $scenario loop=$loop — 다음 시나리오 계속 (CONTINUE_ON_FAIL=0 이면 중단)"
      if [[ "${CONTINUE_ON_FAIL:-1}" != "1" ]]; then
        exit 1
      fi
    fi
    sleep "${BETWEEN_SCENARIOS_SEC:-5}"
  done
done

echo ""
echo "===== DRIVE LOOP FINISHED ====="
