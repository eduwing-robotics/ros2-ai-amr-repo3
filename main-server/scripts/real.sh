#!/usr/bin/env bash
# Real Main server: FastAPI + PostgreSQL (:8088). 실제 Movement/Camera/Vision 호스트 연결.
#
# 사용법:
#   ./scripts/real.sh              # Main만 (:8088, dist 있으면 정적 서빙)
#   ./scripts/real.sh --dev        # Main + Vite dev (:5173)
#   ./scripts/real.sh --reload     # uvicorn auto-reload
#   ./scripts/real.sh --build      # 프론트 빌드 후 Main 실행
#   ./scripts/real.sh --check      # hostname, credential, dependency, port 검사
#
# PostgreSQL: .env 의 LMS_DATABASE_URL 필수. 최초 1회 ./scripts/setup_pg.sh
# 종료: Ctrl+C 또는 저장소 루트 scripts/sf_stack.sh down
# UI mock(dry)는 ./scripts/fake.sh 또는 ./scripts/fake.sh — fake API + Vite.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$ROOT/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend/web"
HOST=""
PORT="${LMS_API_PORT:-8088}"
VITE_PORT="${LMS_VITE_PORT:-5173}"
SITE_PROFILE="${SF_MAIN_SITE_PROFILE:-field}"

# Service identities are fixed by config/network/smartfactory-hosts. The
# integration profile is a versioned field-LAN identity, not a direct-IP bypass.
case "$SITE_PROFILE" in
  field)
    SITE_MOVEMENT_HOST="smartfactory-nav.local"
    SITE_CAMERA_HOST="smartfactory-nav.local"
    SITE_MAIN_HOST="smartfactory-main.local"
    ;;
  integration)
    SITE_MOVEMENT_HOST="smartfactory-integration.local"
    SITE_CAMERA_HOST="smartfactory-integration.local"
    SITE_MAIN_HOST="smartfactory-integration.local"
    ;;
  *)
    echo "[real] unsupported SF_MAIN_SITE_PROFILE: $SITE_PROFILE" >&2
    exit 1
    ;;
esac
SITE_VISION_HOST="smartfactory-vision.local"
SITE_MOVEMENT_MAP_ID="${SITE_MOVEMENT_MAP_ID:-robot2_map}"

BUILD=0
DEV=0
RELOAD=0
STOP=0
CHECK=0
for arg in "$@"; do
  case "$arg" in
    --build) BUILD=1 ;;
    --dev) DEV=1 ;;
    --reload) RELOAD=1 ;;
    --stop) STOP=1 ;;
    --check) CHECK=1 ;;
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

if [[ "$STOP" -eq 1 ]]; then
  echo "[real] --stop does not kill by port. Use scripts/sf_stack.sh down, or Ctrl+C in this launcher terminal." >&2
  exit 1
fi

# Main binds only the canonical hostname selected by the versioned site profile.
CANONICAL_HOSTS="$REPO_ROOT/config/network/smartfactory-hosts"
SMARTFACTORY_HOSTS_SOURCE="$CANONICAL_HOSTS" \
  "$REPO_ROOT/scripts/install-smartfactory-hosts.sh" --check
HOST="$(getent ahostsv4 "$SITE_MAIN_HOST" | awk 'NR == 1 {print $1}')"
if [[ ! "$HOST" =~ ^192\.168\.30\.[0-9]+$ ]]; then
  echo "[real] $SITE_MAIN_HOST must resolve to 192.168.30.x, got: ${HOST:-<unresolved>}" >&2
  exit 1
fi
if ! ip -o -4 addr show | awk '{print $4}' | cut -d/ -f1 | grep -Fxq "$HOST"; then
  echo "[real] resolved Main address is not assigned to a local interface: $HOST" >&2
  exit 1
fi

if [[ ! -f "$ROOT/.env" ]]; then
  echo "[real] .env 가 없어 .env.example 을 복사한다. 호스트를 확인하라."
  cp "$ROOT/.env.example" "$ROOT/.env"
fi

# shellcheck source=/dev/null
source "$REPO_ROOT/scripts/lib/site_credentials.sh"
sf_load_site_credentials "$REPO_ROOT"

if [[ ! -x "$BACKEND/.venv/bin/uvicorn" ]]; then
  echo "[real] backend/.venv 가 없다. 먼저:"
  echo "  cd $BACKEND && python3 -m venv .venv && ./.venv/bin/pip install -r requirements.txt"
  exit 1
fi

read_env_var() {
  local key="$1" default="${2:-}"
  if [[ -v "$key" ]]; then
    printf '%s\n' "${!key}"
    return
  fi
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

require_canonical_host() {
  local label="$1" value="$2" expected="$3"
  if [[ "$value" != "$expected" ]]; then
    echo "[real] $label must use canonical hostname $expected, got: ${value:-<empty>}" >&2
    exit 1
  fi
}

require_canonical_url() {
  local label="$1" value="$2" expected_host="$3"
  local escaped_host="${expected_host//./\\.}"
  local pattern="^(https?|wss?)://${escaped_host}(:[0-9]+)?(/[^[:space:]]*)?$"
  if [[ ! "$value" =~ $pattern ]]; then
    echo "[real] $label must use canonical hostname $expected_host, got: ${value:-<empty>}" >&2
    exit 1
  fi
}

require_canonical_url_list() {
  local label="$1" value="$2" expected_host="$3" format="$4"
  local entry url
  local -a entries
  [[ -z "$value" ]] && return
  IFS=',' read -r -a entries <<< "$value"
  for entry in "${entries[@]}"; do
    entry="${entry#"${entry%%[![:space:]]*}"}"
    entry="${entry%"${entry##*[![:space:]]}"}"
    if [[ "$format" == "keyed" ]]; then
      if [[ "$entry" != *=* ]] || [[ -z "${entry%%=*}" ]]; then
        echo "[real] $label contains an invalid keyed URL: ${entry:-<empty>}" >&2
        exit 1
      fi
      url="${entry#*=}"
    else
      url="$entry"
    fi
    require_canonical_url "$label" "$url" "$expected_host"
  done
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
  local health listener=""
  health="$(curl -sf -m 0.5 "http://${SITE_MAIN_HOST}:${PORT}/health" 2>/dev/null || true)"
  if [[ "$health" == *'"mode":"fake"'* ]] || [[ "$health" == *'"mode": "fake"'* ]]; then
    echo "[real] :$PORT 에 fake API가 이미 떠 있다. fake를 종료한 뒤 다시 실행하라."
    exit 1
  fi
  if command -v ss >/dev/null 2>&1; then
    listener="$(ss -H -ltnp "sport = :$PORT" 2>/dev/null | head -n1 || true)"
  fi
  if [[ -n "$health" || -n "$listener" ]]; then
    echo "[real] :$PORT 에 listener가 이미 있다. 종료하지 않고 시작을 중단한다. ${listener:-}" >&2
    exit 1
  fi
}

guard_existing_vite() {
  local listener=""
  [[ "$DEV" -eq 1 ]] || return 0
  if command -v ss >/dev/null 2>&1; then
    listener="$(ss -H -ltnp "sport = :$VITE_PORT" 2>/dev/null | head -n1 || true)"
  fi
  if [[ -n "$listener" ]]; then
    echo "[real] :$VITE_PORT 에 listener가 이미 있다. 종료하지 않고 Vite 시작을 중단한다. $listener" >&2
    exit 1
  fi
}

guard_existing_api
guard_existing_vite

# --- 실제 외부 서버 연동 env (프로세스 env가 .env 보다 우선 — config.py 정책) ---
# real.sh is the production/field path. Fake movement is only allowed via
# scripts/fake.sh.
MOVEMENT_MODE="http"

MOVEMENT_HOST="$(resolve_host "$(read_env_var LMS_MOVEMENT_HOST)" "$SITE_MOVEMENT_HOST")"
CAMERA_HOST="$(resolve_host "$(read_env_var LMS_CAMERA_HOST)" "$SITE_CAMERA_HOST")"
MOVEMENT_BASE_URLS="$(read_env_var LMS_MOVEMENT_BASE_URLS)"
VISION_STREAM="$(read_env_var LMS_VISION_STREAM_BASE_URL "http://${SITE_VISION_HOST}:8090")"
if [[ "$VISION_STREAM" == *"<"* ]]; then
  VISION_STREAM="http://${SITE_VISION_HOST}:8090"
fi
MAP_ID="$(read_env_var LMS_MOVEMENT_ACTIVE_MAP_ID "$SITE_MOVEMENT_MAP_ID")"
[[ "$MAP_ID" == "Main_map" ]] || [[ "$MAP_ID" == "map" ]] && MAP_ID="$SITE_MOVEMENT_MAP_ID"

VISION_API="$(read_env_var LMS_VISION_API_BASE_URL "http://${SITE_VISION_HOST}:8100")"
if is_placeholder "$VISION_API" || [[ "$VISION_API" == *"<vision"* ]]; then
  VISION_API="http://${SITE_VISION_HOST}:8100"
fi
PUBLIC_BASE="$(read_env_var LMS_PUBLIC_BASE_URL "http://${SITE_MAIN_HOST}:8088")"
CALLBACK_BASE="$(read_env_var LMS_CALLBACK_BASE_URL "$PUBLIC_BASE")"
CALLBACK_ALLOWLIST="$(read_env_var LMS_CALLBACK_ALLOWLIST)"
CAMERA_API_BASE="$(read_env_var LMS_CAMERA_API_BASE_URL "http://${CAMERA_HOST}:$(read_env_var LMS_CAMERA_API_PORT 8080)")"
CAMERA_ROSBRIDGE="$(read_env_var LMS_CAMERA_ROSBRIDGE_URL "ws://${CAMERA_HOST}:$(read_env_var LMS_CAMERA_STREAM_PORT 9090)")"
CAMERA_STREAM_TEMPLATE="$(read_env_var LMS_CAMERA_STREAM_URL_TEMPLATE "$CAMERA_ROSBRIDGE")"
CAMERA_STREAM_CHECK="${CAMERA_STREAM_TEMPLATE//\{host\}/$SITE_CAMERA_HOST}"

require_canonical_host "LMS_MOVEMENT_HOST" "$MOVEMENT_HOST" "$SITE_MOVEMENT_HOST"
require_canonical_host "LMS_CAMERA_HOST" "$CAMERA_HOST" "$SITE_CAMERA_HOST"
require_canonical_url "LMS_VISION_API_BASE_URL" "$VISION_API" "$SITE_VISION_HOST"
require_canonical_url "LMS_VISION_STREAM_BASE_URL" "$VISION_STREAM" "$SITE_VISION_HOST"
require_canonical_url "LMS_PUBLIC_BASE_URL" "$PUBLIC_BASE" "$SITE_MAIN_HOST"
require_canonical_url "LMS_CALLBACK_BASE_URL" "$CALLBACK_BASE" "$SITE_MAIN_HOST"
require_canonical_url "LMS_CAMERA_API_BASE_URL" "$CAMERA_API_BASE" "$SITE_CAMERA_HOST"
require_canonical_url "LMS_CAMERA_ROSBRIDGE_URL" "$CAMERA_ROSBRIDGE" "$SITE_CAMERA_HOST"
require_canonical_url "LMS_CAMERA_STREAM_URL_TEMPLATE" "$CAMERA_STREAM_CHECK" "$SITE_CAMERA_HOST"
require_canonical_url_list "LMS_MOVEMENT_BASE_URLS" "$MOVEMENT_BASE_URLS" "$SITE_MOVEMENT_HOST" "keyed"
require_canonical_url_list "LMS_CALLBACK_ALLOWLIST" "$CALLBACK_ALLOWLIST" "$SITE_MAIN_HOST" "plain"

export LMS_MOVEMENT_CLIENT_MODE="$MOVEMENT_MODE"
export LMS_MOVEMENT_HOST="$MOVEMENT_HOST"
export LMS_CAMERA_HOST="$CAMERA_HOST"
export LMS_MOVEMENT_ACTIVE_MAP_ID="$MAP_ID"
export LMS_VISION_API_BASE_URL="$VISION_API"
export LMS_VISION_STREAM_BASE_URL="$VISION_STREAM"
export LMS_PUBLIC_BASE_URL="$PUBLIC_BASE"
export LMS_CALLBACK_BASE_URL="$CALLBACK_BASE"
[[ -n "$MOVEMENT_BASE_URLS" ]] && export LMS_MOVEMENT_BASE_URLS="$MOVEMENT_BASE_URLS"
[[ -n "$CALLBACK_ALLOWLIST" ]] && export LMS_CALLBACK_ALLOWLIST="$CALLBACK_ALLOWLIST"

if [[ "$CHECK" -eq 1 ]]; then
  if [[ "$DEV" -eq 1 && ! -x "$FRONTEND/node_modules/.bin/vite" ]]; then
    echo "[real] frontend dependency is missing: $FRONTEND/node_modules/.bin/vite" >&2
    exit 1
  fi
  echo "[real] check OK site_profile=$SITE_PROFILE bind=$HOST api_port=$PORT vite_port=$VITE_PORT"
  exit 0
fi

# shellcheck source=/dev/null
source "$ROOT/scripts/lib/pg_bootstrap.sh"
pg_ensure_running

echo "[real] PostgreSQL $(pg_redact_url "$LMS_DATABASE_URL")"
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
API_PID=""
cleanup() {
  local status=$? pid
  trap - EXIT INT TERM
  for pid in "$API_PID" "$VITE_PID"; do
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill -TERM "$pid" 2>/dev/null || true
    fi
  done
  for pid in "$API_PID" "$VITE_PID"; do
    if [[ -n "$pid" ]]; then
      wait "$pid" 2>/dev/null || true
    fi
  done
  return "$status"
}
trap cleanup EXIT INT TERM

UVICORN_ARGS=(app.main:app --host "$HOST" --port "$PORT")
[[ "$RELOAD" -eq 1 ]] && UVICORN_ARGS+=(--reload)

if [[ "$DEV" -eq 1 ]]; then
  if [[ ! -d "$FRONTEND/node_modules" ]]; then
    echo "[real] frontend 의존성이 없다: cd $FRONTEND && npm install"
    exit 1
  fi
  echo "[real] Vite dev http://$SITE_MAIN_HOST:$VITE_PORT  (프록시 → :$PORT)"
  (
    cd "$FRONTEND"
    export VITE_API_PROXY_TARGET="http://$SITE_MAIN_HOST:$PORT"
    export VITE_ALLOWED_HOSTS="${VITE_ALLOWED_HOSTS:-$SITE_MAIN_HOST}"
    export VITE_VISION_WEBRTC_ENABLED="${VITE_VISION_WEBRTC_ENABLED:-true}"
    exec ./node_modules/.bin/vite --host "$HOST" --port "$VITE_PORT" --strictPort
  ) &
  VITE_PID=$!

  echo "[real] Main 서버 http://$SITE_MAIN_HOST:$PORT"
  (
    cd "$BACKEND"
    exec ./.venv/bin/python -m uvicorn "${UVICORN_ARGS[@]}"
  ) &
  API_PID=$!
  wait "$API_PID"
else
  echo "[real] Main 서버 http://$SITE_MAIN_HOST:$PORT"
  cd "$BACKEND"
  exec ./.venv/bin/python -m uvicorn "${UVICORN_ARGS[@]}"
fi
