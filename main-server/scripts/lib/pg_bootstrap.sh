#!/usr/bin/env bash
# PostgreSQL configuration helpers.  Runtime startup verifies a configured DB;
# it never creates one or switches to another database.
# shellcheck disable=SC2034
set -euo pipefail

pg_read_env_value() {
  local key="$1" line
  [[ "${LMS_DISABLE_DOTENV:-}" != "1" ]] || return 0
  [[ -f "${ROOT}/.env" ]] || return 0
  line="$(grep -E "^${key}=" "${ROOT}/.env" | tail -n1 || true)"
  [[ -n "$line" ]] && printf '%s' "${line#*=}" | tr -d "'\""
}

pg_redact_url() {
  local url="$1" authority
  authority="${url#*://}"
  if [[ "$authority" == "$url" || "$authority" != *"@"* ]]; then
    printf '%s\n' 'configured (redacted)'
    return
  fi
  authority="${authority##*@}"
  authority="${authority%%/*}"
  authority="${authority%%\?*}"
  printf 'host=%s\n' "$authority"
}

pg_urlencode() {
  local value="$1"
  if [[ -x "${BACKEND:-${ROOT}/backend}/.venv/bin/python" ]]; then
    "${BACKEND:-${ROOT}/backend}/.venv/bin/python" -c 'import sys; from urllib.parse import quote; print(quote(sys.argv[1], safe=""))' "$value"
  else
    # PostgreSQL passwords used for deployment must not contain URL-reserved
    # characters when the backend venv is unavailable.
    [[ "$value" =~ ^[A-Za-z0-9._~-]+$ ]] || return 1
    printf '%s\n' "$value"
  fi
}

pg_ensure_url() {
  local url="${LMS_DATABASE_URL:-${DATABASE_URL:-}}"
  local password="${LMS_POSTGRES_PASSWORD:-}"
  [[ -n "$url" ]] || url="$(pg_read_env_value LMS_DATABASE_URL)"
  [[ -n "$password" ]] || password="$(pg_read_env_value LMS_POSTGRES_PASSWORD)"
  if [[ -z "$url" ]]; then
    if [[ -z "$password" ]]; then
      echo "[pg] ERROR: set LMS_DATABASE_URL or LMS_POSTGRES_PASSWORD; no database default is permitted." >&2
      return 1
    fi
    local encoded host port database
    encoded="$(pg_urlencode "$password")" || {
      echo "[pg] ERROR: cannot safely derive LMS_DATABASE_URL without the backend venv." >&2
      return 1
    }
    host="${LMS_POSTGRES_HOST:-$(pg_read_env_value LMS_POSTGRES_HOST)}"; host="${host:-localhost}"
    port="${LMS_POSTGRES_PORT:-$(pg_read_env_value LMS_POSTGRES_PORT)}"; port="${port:-5433}"
    database="${LMS_POSTGRES_DB:-$(pg_read_env_value LMS_POSTGRES_DB)}"; database="${database:-lms_mvp}"
    url="postgresql://lms:${encoded}@${host}:${port}/${database}"
  fi
  export LMS_DATABASE_URL="$url"
  export DATABASE_URL="$url"
}

pg_probe_url() {
  local url="$1" python="${BACKEND:-${ROOT}/backend}/.venv/bin/python"
  [[ -x "$python" ]] || return 1
  LMS_DATABASE_URL="$url" "$python" -c 'import os, psycopg; psycopg.connect(os.environ["LMS_DATABASE_URL"], connect_timeout=3).close()' 2>/dev/null
}

pg_ensure_running() {
  pg_ensure_url
  if pg_probe_url "$LMS_DATABASE_URL"; then
    echo "[pg] PostgreSQL connection verified"
    return 0
  fi
  echo "[pg] ERROR: configured PostgreSQL is unavailable or rejected credentials; refusing startup." >&2
  echo "[pg] Set LMS_DATABASE_URL/LMS_POSTGRES_PASSWORD correctly. Local bootstrap requires ./scripts/setup_pg.sh --local-dev." >&2
  return 1
}
