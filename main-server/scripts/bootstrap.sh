#!/usr/bin/env bash
# Prepare this repo on a new PC: .env, Python venv, npm deps, PostgreSQL schema.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKEND="$ROOT/backend"
FRONTEND="$ROOT/frontend/web"
STATE_DIR="$ROOT/.bootstrap"
ENV_FILE="$ROOT/.env"
ENV_EXAMPLE="$ROOT/.env.example"
DB_SNAPSHOT="$ROOT/database/snapshot/current_pg.dump"

SKIP_DB=0
LOCAL_DEV=0
FORCE=0
FORCE_DB_RESTORE=0
for arg in "$@"; do
  case "$arg" in
    --skip-db) SKIP_DB=1 ;;
    --local-dev) LOCAL_DEV=1 ;;
    --force) FORCE=1 ;;
    --force-db-restore) FORCE_DB_RESTORE=1 ;;
    -h|--help)
      sed -n '2,7p' "$0"
      echo
      echo "Usage: ./scripts/bootstrap.sh [--skip-db] [--local-dev] [--force] [--force-db-restore]"
      exit 0
      ;;
    *)
      echo "[bootstrap] 알 수 없는 옵션: $arg" >&2
      exit 1
      ;;
  esac
done

need_command() {
  local cmd="$1" hint="$2"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "[bootstrap] ERROR: '$cmd' 명령이 필요하다." >&2
    echo "[bootstrap] $hint" >&2
    exit 1
  fi
}

python_cmd() {
  if command -v python3 >/dev/null 2>&1; then
    echo "python3"
    return
  fi
  if command -v python >/dev/null 2>&1; then
    echo "python"
    return
  fi
  echo ""
}

file_hash() {
  local path="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | awk '{print $1}'
    return
  fi
  cksum "$path" | awk '{print $1 "-" $2}'
}

stamp_matches() {
  local stamp="$1" source="$2"
  [[ -f "$stamp" ]] || return 1
  [[ -f "$source" ]] || return 1
  [[ "$(cat "$stamp")" == "$(file_hash "$source")" ]]
}

write_stamp() {
  local stamp="$1" source="$2"
  mkdir -p "$STATE_DIR"
  file_hash "$source" >"$stamp"
}

echo "[bootstrap] root: $ROOT"

PYTHON="$(python_cmd)"
if [[ -z "$PYTHON" ]]; then
  echo "[bootstrap] ERROR: Python 3.11+ 가 필요하다." >&2
  exit 1
fi

need_command node "Node.js 20+ 설치 후 다시 실행하라."
need_command npm "npm 설치 후 다시 실행하라."

"$PYTHON" - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("[bootstrap] ERROR: Python 3.11+ 가 필요하다. 현재: " + sys.version.split()[0])
PY

node -e "const v=process.versions.node.split('.').map(Number); if (v[0] < 20) { console.error('[bootstrap] ERROR: Node.js 20+ 가 필요하다. 현재: ' + process.versions.node); process.exit(1); }"

if [[ ! -f "$ENV_FILE" ]]; then
  if [[ -f "$ENV_EXAMPLE" ]]; then
    echo "[bootstrap] .env 생성"
    cp "$ENV_EXAMPLE" "$ENV_FILE"
  else
    echo "[bootstrap] WARN: .env.example 없음"
  fi
fi

VENV_PY="$BACKEND/.venv/bin/python"
VENV_PIP="$BACKEND/.venv/bin/pip"
REQ_STAMP="$STATE_DIR/requirements.txt.sha"

if [[ "$FORCE" -eq 1 || ! -x "$VENV_PY" ]]; then
  echo "[bootstrap] Python venv 생성"
  "$PYTHON" -m venv "$BACKEND/.venv"
fi

BACKEND_INSTALL=0
if [[ "$FORCE" -eq 1 || ! -x "$BACKEND/.venv/bin/uvicorn" ]]; then
  BACKEND_INSTALL=1
elif ! stamp_matches "$REQ_STAMP" "$BACKEND/requirements.txt"; then
  BACKEND_INSTALL=1
fi

if [[ "$BACKEND_INSTALL" -eq 1 ]]; then
  echo "[bootstrap] backend 의존성 설치"
  "$VENV_PIP" install --upgrade pip
  "$VENV_PIP" install -r "$BACKEND/requirements.txt"
  write_stamp "$REQ_STAMP" "$BACKEND/requirements.txt"
else
  echo "[bootstrap] backend 의존성 OK"
fi

PKG_SOURCE="$FRONTEND/package.json"
if [[ -f "$FRONTEND/package-lock.json" ]]; then
  PKG_SOURCE="$FRONTEND/package-lock.json"
fi
NPM_STAMP="$STATE_DIR/frontend-deps.sha"

FRONTEND_INSTALL=0
if [[ "$FORCE" -eq 1 || ! -d "$FRONTEND/node_modules" ]]; then
  FRONTEND_INSTALL=1
elif ! stamp_matches "$NPM_STAMP" "$PKG_SOURCE"; then
  FRONTEND_INSTALL=1
fi

if [[ "$FRONTEND_INSTALL" -eq 1 ]]; then
  echo "[bootstrap] frontend 의존성 설치"
  if [[ -f "$FRONTEND/package-lock.json" ]]; then
    (cd "$FRONTEND" && npm ci)
  else
    (cd "$FRONTEND" && npm install)
  fi
  write_stamp "$NPM_STAMP" "$PKG_SOURCE"
else
  echo "[bootstrap] frontend 의존성 OK"
fi

if [[ "$SKIP_DB" -eq 0 ]]; then
  if [[ "$LOCAL_DEV" -ne 1 ]]; then
    echo "[bootstrap] ERROR: database bootstrap is local-only; pass --local-dev or --skip-db." >&2
    exit 2
  fi
  echo "[bootstrap] explicit local-development PostgreSQL 준비"
  "$ROOT/scripts/setup_pg.sh" --local-dev
  if [[ -f "$DB_SNAPSHOT" ]]; then
    DB_SNAPSHOT_STAMP="$STATE_DIR/current_pg.dump.sha"
    if [[ "$FORCE" -eq 1 || "$FORCE_DB_RESTORE" -eq 1 ]] || ! stamp_matches "$DB_SNAPSHOT_STAMP" "$DB_SNAPSHOT"; then
      echo "[bootstrap] 현재 DB snapshot 복원"
      "$ROOT/scripts/restore_current_db.sh"
      write_stamp "$DB_SNAPSHOT_STAMP" "$DB_SNAPSHOT"
    else
      echo "[bootstrap] 현재 DB snapshot 복원 OK"
    fi
  fi
else
  echo "[bootstrap] PostgreSQL 준비 건너뜀"
fi

echo "[bootstrap] done"
