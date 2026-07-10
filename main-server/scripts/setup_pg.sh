#!/usr/bin/env bash
# Explicit local-development PostgreSQL bootstrap.  Never used by runtime startup.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
COMPOSE="$ROOT/docker-compose.pg.yml"

if [[ "${1:-}" != "--local-dev" || $# -ne 1 ]]; then
  echo "[setup_pg] ERROR: local database bootstrap requires --local-dev." >&2
  echo "Usage: LMS_POSTGRES_PASSWORD='<secret>' ./scripts/setup_pg.sh --local-dev" >&2
  exit 2
fi

# shellcheck source=/dev/null
source "$ROOT/scripts/lib/pg_bootstrap.sh"
CONFIGURED_URL="${LMS_DATABASE_URL:-${DATABASE_URL:-}}"
[[ -n "$CONFIGURED_URL" ]] || CONFIGURED_URL="$(pg_read_env_value LMS_DATABASE_URL)"
pg_ensure_url

# A supplied URL names a deployment database.  Do not mask an outage or typo by
# bringing up a different local instance, even in this explicitly local tool.
if [[ -n "$CONFIGURED_URL" ]]; then
  if ! pg_probe_url "$LMS_DATABASE_URL"; then
    echo "[setup_pg] ERROR: configured PostgreSQL is unavailable; refusing a local fallback." >&2
    exit 1
  fi
  echo "[setup_pg] configured PostgreSQL verified; applying schema/seed"
  (cd "$BACKEND" && LMS_DATABASE_URL="$LMS_DATABASE_URL" ./.venv/bin/python -c 'from app.db.connection import init_db; init_db()')
  exit 0
fi

if ! command -v docker >/dev/null 2>&1 || ! docker compose version >/dev/null 2>&1; then
  echo "[setup_pg] ERROR: docker compose is required for explicit local development bootstrap." >&2
  exit 1
fi
if [[ ! -f "$COMPOSE" ]]; then
  echo "[setup_pg] ERROR: compose file missing: $COMPOSE" >&2
  exit 1
fi

echo "[setup_pg] starting explicitly requested local PostgreSQL"
docker compose -f "$COMPOSE" up -d
for _ in $(seq 1 30); do
  if pg_probe_url "$LMS_DATABASE_URL"; then
    echo "[setup_pg] schema/seed 적용"
    (cd "$BACKEND" && LMS_DATABASE_URL="$LMS_DATABASE_URL" ./.venv/bin/python -c 'from app.db.connection import init_db; init_db()')
    echo "[setup_pg] ready"
    exit 0
  fi
  sleep 1
done
echo "[setup_pg] ERROR: explicit local PostgreSQL did not become ready." >&2
exit 1
