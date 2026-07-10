#!/usr/bin/env bash
# PostgreSQL bootstrap helpers for real.sh (PHASE_60).
# shellcheck disable=SC2034
set -euo pipefail

pg_compose_file() {
  echo "${ROOT}/docker-compose.pg.yml"
}

pg_default_url() {
  if [[ -f "${ROOT}/.env.example" ]]; then
    local line
    line="$(grep -E '^LMS_DATABASE_URL=' "${ROOT}/.env.example" | tail -n1 || true)"
    if [[ -n "$line" ]]; then
      echo "${line#*=}" | tr -d '"' | tr -d "'"
      return
    fi
  fi
  echo "postgresql://lms:lms@localhost:5433/lms_mvp"
}

pg_host_port_from_url() {
  local url="$1"
  if [[ "$url" =~ @([^:/]+):([0-9]+)/ ]]; then
    echo "${BASH_REMATCH[1]} ${BASH_REMATCH[2]}"
  else
    echo "localhost 5433"
  fi
}

pg_port_open() {
  local host="$1" port="$2"
  if command -v nc >/dev/null 2>&1; then
    nc -z "$host" "$port" >/dev/null 2>&1
    return $?
  fi
  if command -v ss >/dev/null 2>&1; then
    ss -ltn | grep -q ":${port} "
    return $?
  fi
  return 1
}

pg_ensure_url() {
  local url="${LMS_DATABASE_URL:-${DATABASE_URL:-}}"
  if [[ -z "$url" ]] && [[ -n "${DB_URL:-}" ]]; then
    url="$DB_URL"
  fi
  if [[ -z "$url" ]]; then
    url="$(pg_default_url)"
    echo "[pg] LMS_DATABASE_URL 미설정 — 기본값 사용: $url"
    echo "[pg] 영구 설정: .env 에 LMS_DATABASE_URL=... 추가"
  fi
  export LMS_DATABASE_URL="$url"
  export DATABASE_URL="$url"
}

pg_try_docker_up() {
  local compose
  compose="$(pg_compose_file)"
  [[ -f "$compose" ]] || return 1
  if ! command -v docker >/dev/null 2>&1; then
    return 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    return 1
  fi
  echo "[pg] docker compose 로 PostgreSQL 기동 ($compose)"
  docker compose -f "$compose" up -d
  return 0
}

pg_wait_ready() {
  local host="$1" port="$2" tries="${3:-30}"
  local i
  for ((i = 1; i <= tries; i++)); do
    if pg_port_open "$host" "$port"; then
      if command -v docker >/dev/null 2>&1 && docker compose -f "$(pg_compose_file)" ps 2>/dev/null | grep -q healthy; then
        echo "[pg] PostgreSQL ready (docker healthy)"
        return 0
      fi
      if pg_port_open "$host" "$port"; then
        echo "[pg] PostgreSQL port $port open"
        return 0
      fi
    fi
    sleep 1
  done
  return 1
}

pg_probe_url() {
  local url="$1"
  [[ -x "${BACKEND:-${ROOT}/backend}/.venv/bin/python" ]] || return 1
  LMS_DATABASE_URL="$url" "${BACKEND:-${ROOT}/backend}/.venv/bin/python" -c "
import os, psycopg
with psycopg.connect(os.environ['LMS_DATABASE_URL'], connect_timeout=3):
    pass
" 2>/dev/null
}

pg_reload_url_from_env() {
  if [[ -f "${ROOT}/.env" ]]; then
    local line
    line="$(grep -E '^LMS_DATABASE_URL=' "${ROOT}/.env" | tail -n1 || true)"
    if [[ -n "$line" ]]; then
      export LMS_DATABASE_URL="$(echo "${line#*=}" | tr -d '"' | tr -d "'")"
      export DATABASE_URL="$LMS_DATABASE_URL"
    fi
  fi
}

pg_native_url() {
  echo "postgresql://lms:lms@localhost:5432/lms_mvp"
}

pg_ensure_running() {
  pg_ensure_url
  if pg_probe_url "$LMS_DATABASE_URL"; then
    echo "[pg] PostgreSQL 연결 확인 ($LMS_DATABASE_URL)"
    return 0
  fi
  local native_url
  native_url="$(pg_native_url)"
  if [[ "$LMS_DATABASE_URL" != "$native_url" ]] && pg_probe_url "$native_url"; then
    echo "[pg] .env URL 실패 — 로컬 Postgres(:5432) 사용"
    if [[ -x "$ROOT/scripts/db/setup_pg.sh" ]]; then
      LMS_DATABASE_URL="$native_url" "$ROOT/scripts/db/setup_pg.sh" && pg_reload_url_from_env
      pg_probe_url "$LMS_DATABASE_URL" && return 0
    fi
    export LMS_DATABASE_URL="$native_url"
    export DATABASE_URL="$native_url"
    return 0
  fi
  read -r pg_host pg_port <<<"$(pg_host_port_from_url "$LMS_DATABASE_URL")"
  if pg_port_open "$pg_host" "$pg_port"; then
    echo "[pg] ERROR: 포트는 열려 있으나 인증/DB 연결 실패 ($LMS_DATABASE_URL)" >&2
    echo "[pg]   ./scripts/db/setup_pg.sh 실행" >&2
    return 1
  fi
  if pg_try_docker_up; then
    read -r pg_host pg_port <<<"$(pg_host_port_from_url "$LMS_DATABASE_URL")"
    if pg_wait_ready "$pg_host" "$pg_port" && pg_probe_url "$LMS_DATABASE_URL"; then
      return 0
    fi
    echo "[pg] ERROR: docker Postgres가 준비되지 않았다." >&2
    return 1
  fi
  if pg_port_open localhost 5432; then
    echo "[pg] :5433 없음, 로컬 Postgres(:5432) 감지 — DB 준비 시도..." >&2
    if [[ -x "$ROOT/scripts/db/setup_pg.sh" ]]; then
      if [[ -t 0 ]] && [[ -t 1 ]]; then
        "$ROOT/scripts/db/setup_pg.sh" && pg_reload_url_from_env && pg_probe_url "$LMS_DATABASE_URL"
        return $?
      fi
      echo "[pg] 최초 1회 DB 생성 (sudo 필요):" >&2
      echo "  cd $ROOT" >&2
      echo "  sudo -u postgres psql -d postgres -v ON_ERROR_STOP=1 < database/setup_native_pg.sql" >&2
      echo "  ./scripts/db/setup_pg.sh && ./scripts/launch/real.sh --dev" >&2
      return 1
    fi
  fi
  echo "[pg] ERROR: PostgreSQL에 연결할 수 없다 ($pg_host:$pg_port)." >&2
  echo "[pg]   ./scripts/db/setup_pg.sh" >&2
  echo "[pg]   또는 docker compose -f docker-compose.pg.yml up -d" >&2
  return 1
}
