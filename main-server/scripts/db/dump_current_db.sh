#!/usr/bin/env bash
# Save the current PostgreSQL database as a portable snapshot for new PCs.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
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
  sha256sum "$SNAPSHOT" >"$SNAPSHOT.sha256"
fi

echo "[dump_db] done"
