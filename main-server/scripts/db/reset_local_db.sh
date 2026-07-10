#!/usr/bin/env bash
# Recreate PostgreSQL MVP schema + seed (PHASE_60).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
URL="${LMS_DATABASE_URL:-${DATABASE_URL:-}}"

if [[ -z "$URL" ]]; then
  echo "[reset_local_db] ERROR: set LMS_DATABASE_URL (see docker-compose.pg.yml)" >&2
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
