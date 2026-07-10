#!/usr/bin/env bash
# Regression checks for deployment policy helpers and compatibility wrappers.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LIB="$ROOT/scripts/lib/pg_bootstrap.sh"
WRAPPER="$ROOT/scripts/launch/lib/pg_bootstrap.sh"

expect_failure() {
  if "$@"; then
    echo "expected failure: $*" >&2
    exit 1
  fi
}

expect_failure env -u LMS_DATABASE_URL -u DATABASE_URL -u LMS_POSTGRES_PASSWORD LMS_DISABLE_DOTENV=1 ROOT="$ROOT" BACKEND="$ROOT/backend" bash -c 'source "$1"; pg_ensure_url' _ "$LIB"

[[ "$(ROOT="$ROOT" BACKEND="$ROOT/backend" bash -c 'source "$1"; declare -F pg_ensure_url' _ "$WRAPPER")" == "pg_ensure_url" ]]

derived="$(env -u LMS_DATABASE_URL -u DATABASE_URL LMS_DISABLE_DOTENV=1 LMS_POSTGRES_PASSWORD='space / secret' ROOT="$ROOT" BACKEND="$ROOT/backend" bash -c 'source "$1"; pg_ensure_url; printf %s "$LMS_DATABASE_URL"' _ "$LIB")"
[[ "$derived" == 'postgresql://lms:space%20%2F%20secret@localhost:5433/lms_mvp' ]]

redacted="$(ROOT="$ROOT" BACKEND="$ROOT/backend" bash -c 'source "$1"; pg_redact_url "$2"' _ "$LIB" 'postgresql://lms:top-secret@db.example:5432/lms_mvp')"
[[ "$redacted" == 'host=db.example:5432' ]]
[[ "$redacted" != *'top-secret'* ]]
redacted="$(ROOT="$ROOT" BACKEND="$ROOT/backend" bash -c 'source "$1"; pg_redact_url "$2"' _ "$LIB" 'postgresql://lms:top-secret@still-secret@db.example:5432/lms_mvp')"
[[ "$redacted" == 'host=db.example:5432' ]]
[[ "$redacted" != *'top-secret'* && "$redacted" != *'still-secret'* ]]

for script in bootstrap.sh real.sh fake.sh launch_real_terminal.sh; do
  grep -q 'exec "\$ROOT/scripts/' "$ROOT/scripts/launch/$script"
done
grep -q 'exec "\$ROOT/scripts/setup_pg.sh"' "$ROOT/scripts/db/setup_pg.sh"
grep -q 'bootstrap.sh --local-dev' "$ROOT/scripts/launch_real_terminal.sh"
grep -q 'pg_redact_url "\$LMS_DATABASE_URL"' "$ROOT/scripts/real.sh"

echo '[deployment_fail_closed] PASS'
