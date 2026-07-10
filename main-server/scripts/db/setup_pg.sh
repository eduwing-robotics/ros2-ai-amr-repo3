#!/usr/bin/env bash
# PostgreSQL 준비: docker compose 또는 로컬 Postgres(5432)에 lms_mvp 생성.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
COMPOSE="$ROOT/docker-compose.pg.yml"
BACKEND="$ROOT/backend"
DOCKER_URL="postgresql://lms:lms@localhost:5433/lms_mvp"
NATIVE_URL="postgresql://lms:lms@localhost:5432/lms_mvp"

write_env_url() {
  local url="$1"
  local env_file="$ROOT/.env"
  if [[ ! -f "$env_file" ]]; then
    cp "$ROOT/.env.example" "$env_file" 2>/dev/null || touch "$env_file"
  fi
  if grep -qE '^LMS_DATABASE_URL=' "$env_file"; then
    sed -i "s|^LMS_DATABASE_URL=.*|LMS_DATABASE_URL=${url}|" "$env_file"
  else
    printf '\nLMS_DATABASE_URL=%s\n' "$url" >>"$env_file"
  fi
  export LMS_DATABASE_URL="$url"
  export DATABASE_URL="$url"
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

probe_url() {
  local url="$1"
  LMS_DATABASE_URL="$url" "$BACKEND/.venv/bin/python" -c "
import psycopg
import os
url = os.environ['LMS_DATABASE_URL']
with psycopg.connect(url, connect_timeout=3):
    pass
" 2>/dev/null
}

init_schema() {
  local url="$1"
  echo "[setup_pg] schema/seed 적용 ($url)"
  (cd "$BACKEND" && LMS_DATABASE_URL="$url" ./.venv/bin/python -c "from app.db.connection import init_db; init_db()")
}

ensure_docker() {
  if ! command -v docker >/dev/null 2>&1; then
    return 1
  fi
  if ! docker compose version >/dev/null 2>&1; then
    return 1
  fi
  [[ -f "$COMPOSE" ]] || return 1
  echo "[setup_pg] docker compose up ($COMPOSE)"
  docker compose -f "$COMPOSE" up -d
  local i
  for ((i = 1; i <= 30; i++)); do
    if probe_url "$DOCKER_URL"; then
      write_env_url "$DOCKER_URL"
      init_schema "$DOCKER_URL"
      echo "[setup_pg] ready: $DOCKER_URL"
      return 0
    fi
    sleep 1
  done
  echo "[setup_pg] ERROR: docker Postgres 준비 시간 초과" >&2
  return 1
}

ensure_native() {
  if ! pg_port_open localhost 5432; then
    return 1
  fi

  if probe_url "$NATIVE_URL"; then
    echo "[setup_pg] 로컬 PostgreSQL(:5432) 이미 연결 가능"
    write_env_url "$NATIVE_URL"
    init_schema "$NATIVE_URL"
    echo "[setup_pg] ready: $NATIVE_URL"
    return 0
  fi

  echo "[setup_pg] 로컬 PostgreSQL(:5432) — lms 사용자/DB 생성 시도"
  local sql_file="$ROOT/database/setup_native_pg.sql"
  if [[ ! -f "$sql_file" ]]; then
    echo "[setup_pg] ERROR: $sql_file 없음" >&2
    return 1
  fi

  run_postgres_sql_file() {
    # postgres 유저는 $HOME 아래 파일을 -f 로 열 수 없음 → 현재 유저가 stdin 으로 전달
    if sudo -n -u postgres psql -d postgres -c "SELECT 1" >/dev/null 2>&1; then
      sudo -n -u postgres psql -d postgres -v ON_ERROR_STOP=1 <"$sql_file"
      return $?
    fi
    if [[ -t 0 ]] && [[ -t 1 ]]; then
      echo "[setup_pg] sudo 비밀번호를 입력하라 (postgres 슈퍼유저로 SQL 실행)"
      sudo -u postgres psql -d postgres -v ON_ERROR_STOP=1 <"$sql_file"
      return $?
    fi
    echo "[setup_pg] postgres 슈퍼유저 SQL을 직접 실행하라:" >&2
    echo "  cd $ROOT" >&2
    echo "  sudo -u postgres psql -d postgres -v ON_ERROR_STOP=1 < database/setup_native_pg.sql" >&2
    echo "  ./scripts/db/setup_pg.sh" >&2
    return 1
  }

  if ! run_postgres_sql_file; then
    return 1
  fi
  if probe_url "$NATIVE_URL"; then
    write_env_url "$NATIVE_URL"
    init_schema "$NATIVE_URL"
    echo "[setup_pg] ready: $NATIVE_URL"
    return 0
  fi
  echo "[setup_pg] ERROR: lms_mvp 생성 후에도 연결 실패" >&2
  return 1
}

main() {
  if [[ ! -x "$BACKEND/.venv/bin/python" ]]; then
    echo "[setup_pg] backend/.venv 가 없다. 먼저 venv 를 만든다." >&2
    exit 1
  fi
  local url="${LMS_DATABASE_URL:-}"
  if [[ -n "$url" ]] && probe_url "$url"; then
    echo "[setup_pg] 이미 연결 가능: $url"
    init_schema "$url"
    exit 0
  fi
  if probe_url "$NATIVE_URL"; then
    echo "[setup_pg] 로컬 :5432 연결 — .env 갱신"
    write_env_url "$NATIVE_URL"
    init_schema "$NATIVE_URL"
    exit 0
  fi
  if ensure_docker; then
    exit 0
  fi
  if ensure_native; then
    exit 0
  fi
  echo "[setup_pg] ERROR: PostgreSQL을 준비하지 못했다." >&2
  echo "  docker: sudo apt install docker.io && docker compose -f docker-compose.pg.yml up -d" >&2
  echo "  native: ./scripts/db/setup_pg.sh (postgres sudo 필요) 또는 DB_MIGRATION.md 참고" >&2
  exit 1
}

main "$@"
