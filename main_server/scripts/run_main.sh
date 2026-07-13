#!/usr/bin/env bash
# Run the Main server: FastAPI + PostgreSQL (:8088), with real Movement/Camera/Vision hosts.
#
# 사용법:
#   ./scripts/run_main.sh              # Main만 (:8088, dist 있으면 정적 서빙)
#   ./scripts/run_main.sh --dev        # Main + Vite dev (:5173)
#   ./scripts/run_main.sh --reload     # uvicorn auto-reload
#   ./scripts/run_main.sh --build      # 프론트 빌드 후 Main 실행
#
# PostgreSQL: .env 의 LMS_DATABASE_URL 필수. 최초 1회 ./scripts/db.sh setup
# 종료: ./scripts/run_main.sh --stop
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend/web"
HOST="${LMS_DEV_HOST:-0.0.0.0}"
PORT="${LMS_API_PORT:-8088}"
VITE_PORT="${LMS_VITE_PORT:-5173}"

# 현장 고정 호스트 (hostname-first). .env 값이 비어 있을 때 기본값으로 사용.
SITE_MOVEMENT_HOST="${SITE_MOVEMENT_HOST:-smartfactory-nav.local}"
SITE_CAMERA_HOST="${SITE_CAMERA_HOST:-smartfactory-nav.local}"
SITE_VISION_HOST="${SITE_VISION_HOST:-smartfactory-vision.local}"
SITE_VISION_FALLBACK_IP="${SITE_VISION_FALLBACK_IP:-192.168.10.59}"
SITE_MOVEMENT_MAP_ID="${SITE_MOVEMENT_MAP_ID:-robot2_map}"

BUILD=0
DEV=0
RELOAD=0
STOP=0
for arg in "$@"; do
  case "$arg" in
    --build) BUILD=1 ;;
    --dev) DEV=1 ;;
    --reload) RELOAD=1 ;;
    --stop) STOP=1 ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
    *)
      echo "알 수 없는 옵션: $arg" >&2
      exit 1
      ;;
  esac
done

kill_port() {
  local port="$1" label="$2"
  if command -v fuser >/dev/null 2>&1 && fuser -n tcp "$port" >/dev/null 2>&1; then
    echo "[real] $label :$port 종료"
    fuser -k "${port}/tcp" >/dev/null 2>&1 || true
    return
  fi
  if command -v lsof >/dev/null 2>&1; then
    local pids
    pids="$(lsof -ti tcp:"$port" 2>/dev/null || true)"
    if [[ -n "$pids" ]]; then
      echo "[real] $label :$port 종료 (pid $pids)"
      kill $pids 2>/dev/null || true
      return
    fi
  fi
  echo "[real] $label :$port - 실행 중 프로세스 없음"
}

if [[ "$STOP" -eq 1 ]]; then
  kill_port "$PORT" "Main API"
  kill_port "$VITE_PORT" "Vite dev"
  echo "[real] done"
  exit 0
fi

if [[ ! -f "$ROOT/.env" ]]; then
  echo "[real] .env 가 없어 .env.example 을 복사한다. 호스트를 확인하라."
  cp "$ROOT/.env.example" "$ROOT/.env"
fi

if [[ ! -x "$BACKEND/.venv/bin/uvicorn" ]]; then
  echo "[real] backend/.venv 가 없다. 먼저:"
  echo "  cd $BACKEND && python3 -m venv .venv && ./.venv/bin/pip install -r requirements.lock.txt"
  exit 1
fi

read_env_var() {
  local key="$1" default="${2:-}"
  if [[ -f "$ROOT/.env" ]]; then
    local line
    line="$(grep -E "^${key}=" "$ROOT/.env" | tail -n1 || true)"
    if [[ -n "$line" ]]; then
      echo "${line#*=}" | tr -d '"' | tr -d "'"
      return
    fi
  fi
  echo "$default"
}

is_placeholder() {
  local v="$1"
  [[ -z "$v" ]] || [[ "$v" == *"<"* ]] || [[ "$v" == *"host-or-name"* ]] || [[ "$v" == *"<movement"* ]] || [[ "$v" == *"<camera"* ]]
}

resolve_host() {
  local from_env="$1" site_default="$2"
  if is_placeholder "$from_env"; then
    echo "$site_default"
  else
    echo "$from_env"
  fi
}

guard_existing_api() {
  local health
  health="$(curl -sf -m 0.5 "http://127.0.0.1:${PORT}/health" 2>/dev/null || true)"
  if [[ -z "$health" ]]; then
    return
  fi
  echo "[real] :$PORT 에 API가 이미 떠 있다. 중복 실행을 중단한다."
  exit 1
}

guard_existing_api

# --- 실제 외부 서버 연동 env (프로세스 env가 .env 보다 우선 — config.py 정책) ---
MOVEMENT_MODE="http"

MOVEMENT_HOST="$(resolve_host "$(read_env_var LMS_MOVEMENT_HOST)" "$SITE_MOVEMENT_HOST")"
CAMERA_HOST="$(resolve_host "$(read_env_var LMS_CAMERA_HOST)" "$SITE_CAMERA_HOST")"
VISION_STREAM="$(read_env_var LMS_VISION_STREAM_BASE_URL "http://${SITE_VISION_HOST}:8090")"
if [[ "$VISION_STREAM" == *"<"* ]]; then
  VISION_STREAM="http://${SITE_VISION_HOST}:8090"
fi
VISION_FB="$(read_env_var LMS_VISION_API_FALLBACK_BASE_URL "http://${SITE_VISION_FALLBACK_IP}:8100")"
VISION_STREAM_FB="$(read_env_var LMS_VISION_STREAM_FALLBACK_BASE_URL "http://${SITE_VISION_FALLBACK_IP}:8090")"
MAP_ID="$(read_env_var LMS_MOVEMENT_ACTIVE_MAP_ID "$SITE_MOVEMENT_MAP_ID")"
[[ "$MAP_ID" == "Main_map" ]] || [[ "$MAP_ID" == "map" ]] && MAP_ID="$SITE_MOVEMENT_MAP_ID"

VISION_API="$(read_env_var LMS_VISION_API_BASE_URL "http://${SITE_VISION_HOST}:8100")"
if is_placeholder "$VISION_API" || [[ "$VISION_API" == *"<vision"* ]]; then
  VISION_API="http://${SITE_VISION_HOST}:8100"
fi
if [[ "$VISION_STREAM" == *"<"* ]]; then
  VISION_STREAM="http://${SITE_VISION_HOST}:8090"
fi

export LMS_MOVEMENT_CLIENT_MODE="$MOVEMENT_MODE"
export LMS_MOVEMENT_HOST="$MOVEMENT_HOST"
export LMS_CAMERA_HOST="$CAMERA_HOST"
export LMS_MOVEMENT_ACTIVE_MAP_ID="$MAP_ID"
export LMS_VISION_API_BASE_URL="$VISION_API"
export LMS_VISION_STREAM_BASE_URL="$VISION_STREAM"
export LMS_VISION_API_FALLBACK_BASE_URL="$VISION_FB"
export LMS_VISION_STREAM_FALLBACK_BASE_URL="$VISION_STREAM_FB"

PUBLIC_BASE="$(read_env_var LMS_PUBLIC_BASE_URL "http://smartfactory-main.local:8088")"
export LMS_PUBLIC_BASE_URL="$PUBLIC_BASE"

DB_URL="$(read_env_var LMS_DATABASE_URL "")"
if [[ -z "$DB_URL" ]]; then
  DB_URL="$(grep -E '^LMS_DATABASE_URL=' "$ROOT/.env.example" 2>/dev/null | tail -n1 | cut -d= -f2- | tr -d '"' | tr -d "'" || true)"
fi
export LMS_DATABASE_URL="${DB_URL:-postgresql://lms:lms@localhost:5432/lms_mvp}"

# shellcheck source=/dev/null
source "$ROOT/scripts/lib/pg_bootstrap.sh"
pg_ensure_running

echo "[real] PostgreSQL $LMS_DATABASE_URL"
echo "  Movement  http://${MOVEMENT_HOST}:8001|8002/movement-api/v1  map=${MAP_ID}"
echo "  Camera    http://${CAMERA_HOST}:$(read_env_var LMS_CAMERA_API_PORT 8080)  ros ws://$(read_env_var LMS_CAMERA_STREAM_PORT 9090)"
echo "  Vision    $(read_env_var LMS_VISION_STREAM_BASE_URL "http://${SITE_VISION_HOST}:8090")"

probe() {
  local label="$1" url="$2"
  if curl -sf -m 2 "$url" >/dev/null 2>&1; then
    echo "  [ok] $label"
  else
    echo "  [warn] $label — 응답 없음 ($url)"
  fi
}
probe "movement :8001" "http://${MOVEMENT_HOST}:8001/movement-api/v1/map-state"
probe "vision stream" "${VISION_STREAM}/api/v1/vision/bridge/status"

if [[ "$DEV" -eq 0 ]] && [[ ! -d "$FRONTEND/dist" ]]; then
  echo "[real] frontend/web/dist 없음 — 브라우저 UI는 --dev 또는 --build 를 쓰거나 dist 를 빌드하라."
fi

if [[ "$BUILD" -eq 1 ]]; then
  echo "[real] 프론트 빌드..."
  (cd "$FRONTEND" && npm run build)
fi

VITE_PID=""
cleanup() {
  [[ -n "$VITE_PID" ]] && kill "$VITE_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

if [[ "$DEV" -eq 1 ]]; then
  if [[ ! -d "$FRONTEND/node_modules" ]]; then
    echo "[real] frontend 의존성이 없다: cd $FRONTEND && npm install"
    exit 1
  fi
  echo "[real] Vite dev http://localhost:$VITE_PORT  (프록시 → :$PORT)"
  (
    cd "$FRONTEND"
    export VITE_API_PROXY_TARGET="http://127.0.0.1:$PORT"
    npm run dev -- --host "$HOST" --port "$VITE_PORT"
  ) &
  VITE_PID=$!
fi

echo "[real] Main 서버 http://localhost:$PORT"
UVICORN_ARGS=(app.main:app --host "$HOST" --port "$PORT")
[[ "$RELOAD" -eq 1 ]] && UVICORN_ARGS+=(--reload)
cd "$BACKEND"
exec ./.venv/bin/python -m uvicorn "${UVICORN_ARGS[@]}"
