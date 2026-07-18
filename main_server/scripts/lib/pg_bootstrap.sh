#!/usr/bin/env bash
# Local PostgreSQL bootstrap helpers for run_main.sh.
# shellcheck disable=SC2034
set -euo pipefail

pg_default_url() {
  if [[ -f "${ROOT}/.env.example" ]]; then
    local line
    line="$(grep -E '^LMS_DATABASE_URL=' "${ROOT}/.env.example" | tail -n1 || true)"
    if [[ -n "$line" ]]; then
      echo "${line#*=}" | tr -d '"' | tr -d "'"
      return
    fi
  fi
  echo "postgresql://lms:lms@localhost:5432/lms_mvp"
}

pg_host_port_from_url() {
  local url="$1"
  if [[ "$url" =~ @([^:/]+):([0-9]+)/ ]]; then
    echo "${BASH_REMATCH[1]} ${BASH_REMATCH[2]}"
  else
    echo "localhost 5432"
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

pg_probe_url() {
  local url="$1"
  [[ -x "${BACKEND:-${ROOT}/backend}/.venv/bin/python" ]] || return 1
  LMS_DATABASE_URL="$url" "${BACKEND:-${ROOT}/backend}/.venv/bin/python" -c "
import os, psycopg
with psycopg.connect(os.environ['LMS_DATABASE_URL'], connect_timeout=3):
    pass
" 2>/dev/null
}

pg_native_url() {
  echo "postgresql://lms:lms@localhost:5432/lms_mvp"
}

# 연결 성공 시 선택 URL을 export하며 포트 open만으로 readiness를 인정하지 않는다.
pg_ensure_running() {
  pg_ensure_url
  if pg_probe_url "$LMS_DATABASE_URL"; then
    echo "[pg] PostgreSQL 연결 확인 ($LMS_DATABASE_URL)"
    return 0
  fi

  local native_url
  native_url="$(pg_native_url)"
  if [[ "$LMS_DATABASE_URL" != "$native_url" ]] && pg_probe_url "$native_url"; then
    echo "[pg] .env URL 실패 — 로컬 PostgreSQL(:5432) 사용"
    export LMS_DATABASE_URL="$native_url"
    export DATABASE_URL="$native_url"
    return 0
  fi

  read -r pg_host pg_port <<<"$(pg_host_port_from_url "$LMS_DATABASE_URL")"
  if pg_port_open "$pg_host" "$pg_port"; then
    echo "[pg] ERROR: 포트는 열려 있으나 인증/DB 연결 실패 ($LMS_DATABASE_URL)" >&2
  else
    echo "[pg] ERROR: PostgreSQL에 연결할 수 없다 ($pg_host:$pg_port)." >&2
  fi
  echo "[pg] 로컬 PostgreSQL을 시작한 뒤 다음 명령을 실행하라:" >&2
  echo "  bash ./scripts/db.sh setup" >&2
  return 1
}
