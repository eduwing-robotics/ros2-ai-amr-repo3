#!/usr/bin/env bash
# Restore the packaged PostgreSQL snapshot into the configured database.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SNAPSHOT="${LMS_DB_SNAPSHOT_PATH:-$ROOT/database/snapshot/current_pg.dump}"
ENV_FILE="$ROOT/.env"
COMPOSE_FILE="$ROOT/docker-compose.pg.yml"

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
if command -v pg_restore >/dev/null 2>&1; then
  pg_restore --clean --if-exists --no-owner --no-privileges --exit-on-error --dbname "$URL" "$SNAPSHOT"
elif command -v docker >/dev/null 2>&1 && docker compose -f "$COMPOSE_FILE" ps postgres >/dev/null 2>&1; then
  docker compose -f "$COMPOSE_FILE" exec -T postgres pg_restore \
    --clean --if-exists --no-owner --no-privileges --exit-on-error \
    --username lms --dbname lms_mvp <"$SNAPSHOT"
else
  echo "[restore_db] ERROR: pg_restore 명령 또는 docker compose postgres 서비스가 필요하다." >&2
  exit 1
fi
echo "[restore_db] done"
