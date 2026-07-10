#!/usr/bin/env bash
# Disposable no-hardware PostgreSQL quality gate.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
IMAGE="${LMS_NOHARDWARE_PG_IMAGE:-postgres:16-alpine}"
CONTAINER="lms-nohardware-pg-${RANDOM}-$$"
PASSWORD="nohardware-test-${RANDOM}-${RANDOM}"
DATABASE="lms_nohardware_test"

cleanup() {
  docker rm --force "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

docker run --detach --rm --name "$CONTAINER" \
  --env POSTGRES_USER=lms \
  --env POSTGRES_PASSWORD="$PASSWORD" \
  --env POSTGRES_DB="$DATABASE" \
  --publish 127.0.0.1::5432 \
  "$IMAGE" >/dev/null

for _ in $(seq 1 30); do
  if docker exec "$CONTAINER" pg_isready -U lms -d "$DATABASE" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done
docker exec "$CONTAINER" pg_isready -U lms -d "$DATABASE" >/dev/null

PORT="$(docker port "$CONTAINER" 5432/tcp | sed -n 's/.*:\([0-9][0-9]*\)$/\1/p' | head -n1)"
if [[ -z "$PORT" ]]; then
  echo "[check_nohardware_pg] ERROR: unable to determine PostgreSQL port" >&2
  exit 1
fi

echo "[check_nohardware_pg] disposable PostgreSQL on 127.0.0.1:$PORT"
LMS_DATABASE_URL="postgresql://lms:${PASSWORD}@127.0.0.1:${PORT}/${DATABASE}" \
  "$ROOT/scripts/check_pg_mvp.sh"
