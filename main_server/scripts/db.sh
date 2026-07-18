#!/usr/bin/env bash
# 책임: 로컬 PostgreSQL schema·snapshot·reference data 생명주기를 관리한다.
# 소유: 지정 DB의 구조 변경. 비책임: PostgreSQL 서비스 설치와 운영 백업 정책.
set -euo pipefail

usage() {
  echo "Usage: ./scripts/db.sh <setup|reset|restore|dump|migrate|status|reference-verify|reference-sync|reference-export>" >&2
  exit 2
}

# 연결 가능한 DB에 schema·seed를 적용하며 필요 시 로컬 lms DB 생성을 시도한다.
db_setup() {

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
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
    echo "  ./scripts/db.sh setup" >&2
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
  if ensure_native; then
    exit 0
  fi
  echo "[setup_pg] ERROR: PostgreSQL을 준비하지 못했다." >&2
  echo "  로컬 PostgreSQL(:5432)을 시작하고 bash ./scripts/db.sh setup을 다시 실행하라." >&2
  echo "  최초 사용자/DB 생성에는 postgres sudo 권한이 필요할 수 있다." >&2
  exit 1
}

main "$@"

}

#  지정 DB의 public schema를 삭제 후 재생성하므로 사전 백업이 필요하다.
db_reset() {

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
URL="${LMS_DATABASE_URL:-${DATABASE_URL:-}}"

if [[ -z "$URL" ]]; then
  echo "[reset_local_db] ERROR: set LMS_DATABASE_URL (see .env.example)" >&2
  exit 1
fi

echo "[reset_local_db] drop + recreate public schema on $URL"
export LMS_DATABASE_URL="$URL"
cd "$ROOT/backend"
./.venv/bin/python <<'PY'
from app.db.pg_connection import require_database_url, pg_transaction

require_database_url()
with pg_transaction() as conn:
    conn.execute("DROP SCHEMA public CASCADE")
    conn.execute("CREATE SCHEMA public")
    conn.execute("GRANT ALL ON SCHEMA public TO public")
PY

echo "[reset_local_db] init_db (schema + bootstrap only)"
./.venv/bin/python -c "from app.db.connection import init_db; init_db(); print('ok')"
echo "[reset_local_db] done"

}

#  snapshot을 지정 DB에 clean restore하여 동일 이름 객체를 교체한다.
db_restore() {

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SNAPSHOT="${LMS_DB_SNAPSHOT_PATH:-$ROOT/database/snapshot/current_pg.dump}"
ENV_FILE="$ROOT/.env"

read_env_url() {
  if [[ -n "${LMS_DATABASE_URL:-${DATABASE_URL:-}}" ]]; then
    echo "${LMS_DATABASE_URL:-${DATABASE_URL:-}}"
    return
  fi
  if [[ -f "$ENV_FILE" ]]; then
    local line
    line="$(grep -E "^LMS_DATABASE_URL=" "$ENV_FILE" | tail -n1 || true)"
    if [[ -n "$line" ]]; then
      echo "${line#*=}" | tr -d "\""
      return
    fi
  fi
  echo ""
}

if [[ ! -f "$SNAPSHOT" ]]; then
  echo "[restore_db] snapshot 없음: $SNAPSHOT"
  exit 0
fi

URL="$(read_env_url)"
if [[ -z "$URL" ]]; then
  echo "[restore_db] ERROR: LMS_DATABASE_URL이 필요하다." >&2
  exit 1
fi

echo "[restore_db] restore: $SNAPSHOT"
if ! command -v pg_restore >/dev/null 2>&1; then
  echo "[restore_db] ERROR: 로컬 pg_restore 명령이 필요하다." >&2
  exit 1
fi
pg_restore --clean --if-exists --no-owner --no-privileges --exit-on-error --dbname "$URL" "$SNAPSHOT"
echo "[restore_db] done"

}

# 지정 DB의 재현 가능한 custom-format snapshot과 checksum을 갱신한다.
db_dump() {

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SNAPSHOT_DIR="$ROOT/database/snapshot"
SNAPSHOT="$SNAPSHOT_DIR/current_pg.dump"
ENV_FILE="$ROOT/.env"

read_env_url() {
  if [[ -n "${LMS_DATABASE_URL:-${DATABASE_URL:-}}" ]]; then
    echo "${LMS_DATABASE_URL:-${DATABASE_URL:-}}"
    return
  fi
  if [[ -f "$ENV_FILE" ]]; then
    local line
    line="$(grep -E '^LMS_DATABASE_URL=' "$ENV_FILE" | tail -n1 || true)"
    if [[ -n "$line" ]]; then
      echo "${line#*=}" | tr -d '"' | tr -d "'"
      return
    fi
  fi
  echo ""
}

if ! command -v pg_dump >/dev/null 2>&1; then
  echo "[dump_db] ERROR: pg_dump 명령이 필요하다." >&2
  exit 1
fi

URL="$(read_env_url)"
if [[ -z "$URL" ]]; then
  echo "[dump_db] ERROR: LMS_DATABASE_URL이 필요하다." >&2
  exit 1
fi

mkdir -p "$SNAPSHOT_DIR"
echo "[dump_db] dump: $SNAPSHOT"
pg_dump --format=custom --no-owner --no-privileges --file "$SNAPSHOT" "$URL"

if command -v sha256sum >/dev/null 2>&1; then
  (
    cd "$SNAPSHOT_DIR"
    sha256sum "$(basename "$SNAPSHOT")" >"$(basename "$SNAPSHOT").sha256"
  )
fi

echo "[dump_db] done"

}

COMMAND="${1:-}"
[[ -n "$COMMAND" ]] || usage
shift
case "$COMMAND" in
  setup) db_setup "$@" ;;
  reset) db_reset "$@" ;;
  restore) db_restore "$@" ;;
  dump) db_dump "$@" ;;
  migrate|status|reference-verify|reference-sync|reference-export)
    ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
    PYTHON="$ROOT/backend/.venv/bin/python"
    [[ -x "$PYTHON" ]] || PYTHON="$ROOT/backend/.venv/Scripts/python.exe"
    cd "$ROOT/backend"
    "$PYTHON" -m app.db.cli "$COMMAND" "$@"
    ;;
  *) usage ;;
esac
