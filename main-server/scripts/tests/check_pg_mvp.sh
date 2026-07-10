#!/usr/bin/env bash
# PostgreSQL quality gate (PHASE_60-F).
# Uses mutable demo fixtures, so it must run against a dedicated test DB.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [[ -z "${LMS_DATABASE_URL:-${DATABASE_URL:-}}" && -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(grep -E '^LMS_DATABASE_URL=' "$ROOT/.env" | sed 's/^/export /')
  set +a
fi

URL="${LMS_DATABASE_URL:-${DATABASE_URL:-}}"

if [[ -z "$URL" ]]; then
  echo "[check_pg_mvp] ERROR: LMS_DATABASE_URL is required (see .env.example, docker-compose.pg.yml)" >&2
  exit 1
fi

if [[ "${LMS_ALLOW_MUTABLE_DB_TESTS:-}" != "1" && "$URL" != *"_test"* ]]; then
  echo "[check_pg_mvp] ERROR: this test applies test fixtures and deletes fixture rows." >&2
  echo "[check_pg_mvp] Refusing non-test DB URL: $URL" >&2
  echo "[check_pg_mvp] Use a dedicated DB such as postgresql://lms:lms@localhost:5432/lms_mvp_test" >&2
  echo "[check_pg_mvp] or set LMS_ALLOW_MUTABLE_DB_TESTS=1 only for disposable databases." >&2
  exit 1
fi

echo "[check_pg_mvp] init + test fixture + unittest ($URL)"
export LMS_DATABASE_URL="$URL"
cd "$ROOT/backend"
./.venv/bin/python -c "from app.db.connection import init_db; from tests.pg_fixture import apply_demo_fixture; init_db(); apply_demo_fixture()"
./.venv/bin/python -m unittest tests.test_mvp_pg_inout tests.test_pg_ddl_smoke tests.test_command_evidence_runtime tests.test_seed_persistence tests.test_pg_db_safety_races -v
echo "[check_pg_mvp] ok"
