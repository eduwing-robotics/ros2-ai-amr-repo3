#!/usr/bin/env bash
# Fake UI dev: Node fake API (:8088) + Vite dev (:5173)
# FastAPI·PostgreSQL·외부 Movement/Camera/Vision 없이 화면 확인.
#
# 사용법:
#   ./scripts/launch/fake.sh
#   ./scripts/launch/fake.sh --api-only    # fake API만 (Vite는 별도 터미널)
#
# 종료: Ctrl+C (fake API·Vite 함께 정리)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
FRONTEND="$ROOT/frontend/web"
HOST="${LMS_DEV_HOST:-0.0.0.0}"
API_PORT="${LMS_API_PORT:-8088}"
VITE_PORT="${LMS_VITE_PORT:-5173}"
API_ONLY=0

for arg in "$@"; do
  case "$arg" in
    --api-only) API_ONLY=1 ;;
    -h|--help)
      sed -n '2,9p' "$0"
      exit 0
      ;;
    *)
      echo "알 수 없는 옵션: $arg" >&2
      exit 1
      ;;
  esac
done

if ! command -v node >/dev/null 2>&1; then
  echo "[fake] node 가 필요하다." >&2
  exit 1
fi

if [[ ! -d "$FRONTEND/node_modules" ]]; then
  echo "[fake] frontend 의존성이 없다. 먼저 실행:"
  echo "  cd $FRONTEND && npm install"
  exit 1
fi

if curl -sf -m 0.5 "http://127.0.0.1:$API_PORT/health" >/dev/null 2>&1; then
  echo "[fake] :$API_PORT 에 API가 이미 떠 있다. 먼저 종료하라."
  exit 1
fi

FAKE_PID=""
VITE_PID=""

cleanup() {
  [[ -n "$VITE_PID" ]] && kill "$VITE_PID" 2>/dev/null || true
  [[ -n "$FAKE_PID" ]] && kill "$FAKE_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "[fake] fake API 시작 http://localhost:$API_PORT"
node "$ROOT/scripts/launch/run_fake_api.mjs" &
FAKE_PID=$!

echo -n "[fake] API 준비 대기"
for _ in $(seq 1 50); do
  if curl -sf "http://127.0.0.1:$API_PORT/health" >/dev/null 2>&1; then
    echo " OK"
    break
  fi
  echo -n "."
  sleep 0.1
done

if ! curl -sf "http://127.0.0.1:$API_PORT/health" >/dev/null 2>&1; then
  echo
  echo "[fake] fake API가 :$API_PORT 에 응답하지 않는다. 포트 점유를 확인하라." >&2
  exit 1
fi

if [[ "$API_ONLY" -eq 1 ]]; then
  echo "[fake] --api-only: Vite는 별도 실행"
  echo "  cd $FRONTEND && VITE_API_PROXY_TARGET=http://localhost:$API_PORT npm run dev -- --host $HOST --port $VITE_PORT"
  wait "$FAKE_PID"
  exit 0
fi

echo "[fake] Vite dev 시작 http://localhost:$VITE_PORT  (API 프록시 → :$API_PORT)"
(
  cd "$FRONTEND"
  export VITE_API_PROXY_TARGET="http://127.0.0.1:$API_PORT"
  exec npm run dev -- --host "$HOST" --port "$VITE_PORT"
) &
VITE_PID=$!

wait "$VITE_PID"
