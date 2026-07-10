#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_NAME="lms_nohardware_test"
DB_USER="postgres"
DB_PASSWORD="postgres"
CONTAINER_NAME="nohardware-db-${RANDOM}-$$"
CID=""

cleanup() {
  if [[ -n "${CID}" ]]; then
    docker rm -f "${CID}" >/dev/null 2>&1 || true
  fi
}
trap cleanup EXIT

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required for no-hardware DB test" >&2
  exit 127
fi

CID="$(docker run -d \
  --name "${CONTAINER_NAME}" \
  -e POSTGRES_USER="${DB_USER}" \
  -e POSTGRES_PASSWORD="${DB_PASSWORD}" \
  -e POSTGRES_DB="${DB_NAME}" \
  -p 127.0.0.1::5432 \
  postgres:16-alpine)"

HOST_PORT="$(docker port "${CID}" 5432/tcp | sed -E 's/.*:([0-9]+)$/\1/')"
DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@127.0.0.1:${HOST_PORT}/${DB_NAME}"

echo "Started postgres:16-alpine container=${CID:0:12} port=${HOST_PORT}"

ready=0
for _ in {1..60}; do
  if docker exec "${CID}" psql -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 -c "SELECT 1" >/dev/null 2>&1; then
    ready=1
    break
  fi
  sleep 0.5
done
if [[ "${ready}" != "1" ]]; then
  echo "Postgres did not become ready" >&2
  docker logs "${CID}" >&2 || true
  exit 1
fi

# Apply DBML schema plus the static command seed required by repo progress/evidence seams.
docker exec -i "${CID}" psql -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 < "${ROOT_DIR}/main-server/database/schema_pg.sql" >/dev/null
docker exec -i "${CID}" psql -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 < "${ROOT_DIR}/main-server/database/seed/commands_pg.sql" >/dev/null
docker exec -i "${CID}" psql -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 < "${ROOT_DIR}/tests/nohardware/db/seed.sql" >/dev/null

cd "${ROOT_DIR}"
# This is intentionally a DB-only seam.  It proves PostgreSQL persistence,
# concurrent claims, and restart dispatch durability without starting the AI
# monitor service required for a physical-motion leg.  The root TCP suite keeps
# LMS_PERSON_HAZARD_ENABLED=true and covers the mandatory person-stop flow.
LMS_PERSON_HAZARD_ENABLED=false \
LMS_DATABASE_URL="${DATABASE_URL}" \
PYTHONPATH="${ROOT_DIR}/main-server/backend" \
"${ROOT_DIR}/main-server/.venv/bin/python" "${ROOT_DIR}/tests/nohardware/db/check_db_persistence.py"

# This must use the disposable PostgreSQL instance above: the race suite opens
# competing real connections and verifies recovery/poller callback claims.
LMS_PERSON_HAZARD_ENABLED=false \
LMS_DATABASE_URL="${DATABASE_URL}" \
PYTHONPATH="${ROOT_DIR}/main-server/backend" \
"${ROOT_DIR}/main-server/.venv/bin/pytest" -q \
  "${ROOT_DIR}/main-server/backend/tests/test_pg_db_safety_races.py"
