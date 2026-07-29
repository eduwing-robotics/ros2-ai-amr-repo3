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

missing_env_root="$(mktemp -d)"
trap 'rm -rf "$missing_env_root"' EXIT
: >"$missing_env_root/.env"
if missing_output="$(
  env -u LMS_DATABASE_URL -u DATABASE_URL -u LMS_POSTGRES_PASSWORD \
    ROOT="$missing_env_root" BACKEND="$ROOT/backend" \
    bash -c 'set -euo pipefail; source "$1"; pg_ensure_url' _ "$LIB" 2>&1
)"; then
  echo "expected missing PostgreSQL configuration to fail" >&2
  exit 1
fi
grep -q '\[pg\] ERROR: set LMS_DATABASE_URL or LMS_POSTGRES_PASSWORD' <<<"$missing_output"

[[ "$(ROOT="$ROOT" BACKEND="$ROOT/backend" bash -c 'source "$1"; declare -F pg_ensure_url' _ "$WRAPPER")" == "pg_ensure_url" ]]

test_backend="$missing_env_root/backend"
mkdir -p "$test_backend/.venv/bin"
ln -s "$(command -v python3)" "$test_backend/.venv/bin/python"
derived="$(env -u LMS_DATABASE_URL -u DATABASE_URL LMS_DISABLE_DOTENV=1 LMS_POSTGRES_PASSWORD='space / secret' ROOT="$ROOT" BACKEND="$test_backend" bash -c 'source "$1"; pg_ensure_url; printf %s "$LMS_DATABASE_URL"' _ "$LIB")"
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
grep -Fq 'exec "$ROOT/scripts/reset_local_db.sh" "$@"' "$ROOT/scripts/db/reset_local_db.sh"
grep -Fq 'exec "$ROOT/scripts/dump_current_db.sh" "$@"' "$ROOT/scripts/db/dump_current_db.sh"
grep -Fq 'exec "$ROOT/scripts/restore_current_db.sh" "$@"' "$ROOT/scripts/db/restore_current_db.sh"
grep -Fq 'exec "$ROOT/scripts/check_all.sh" "$@"' "$ROOT/scripts/tests/check_all.sh"
grep -Fq 'exec "$ROOT/scripts/check_pg_mvp.sh" "$@"' "$ROOT/scripts/tests/check_pg_mvp.sh"
grep -Fq 'exec "$ROOT/scripts/install_desktop_launcher.sh" "$@"' "$ROOT/scripts/launch/install_desktop_launcher.sh"
grep -q 'bootstrap.sh --local-dev' "$ROOT/scripts/launch_real_terminal.sh"
grep -q 'pg_redact_url "\$LMS_DATABASE_URL"' "$ROOT/scripts/real.sh"
grep -Fq '[[ "$DEV" -eq 1 ]] || return 0' "$ROOT/scripts/real.sh"

echo '[deployment_fail_closed] PASS'
