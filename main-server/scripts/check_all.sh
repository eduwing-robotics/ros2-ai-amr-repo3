#!/usr/bin/env bash
# Repo-wide lightweight verification (PostgreSQL required for DB tests).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ -z "${LMS_DATABASE_URL:-${DATABASE_URL:-}}" ]]; then
  if [[ -f "$ROOT/.env" ]]; then
    set -a
    # shellcheck disable=SC1091
    source <(grep -E '^LMS_DATABASE_URL=' "$ROOT/.env" | sed 's/^/export /')
    set +a
  fi
fi

echo "[check_all] docs"
"$ROOT/scripts/check_docs.sh"

echo "[check_all] backend syntax"
cd "$ROOT/backend"
./.venv/bin/python -m compileall app

echo "[check_all] postgres mvp (required)"
"$ROOT/scripts/check_pg_mvp.sh"

echo "[check_all] backend unittest"
cd "$ROOT"
backend/.venv/bin/python -m unittest discover -s backend/tests

if backend/.venv/bin/python -c "import ruff" 2>/dev/null; then
  echo "[check_all] backend ruff"
  cd "$ROOT/backend"
  ./.venv/bin/ruff check app tests
else
  echo "[check_all] backend ruff skipped (pip install -r requirements-dev.txt)"
fi

if backend/.venv/bin/python -c "import pytest" 2>/dev/null; then
  echo "[check_all] backend pytest"
  cd "$ROOT/backend"
  ./.venv/bin/python -m pytest -q
else
  echo "[check_all] backend pytest skipped (pip install -r requirements-dev.txt)"
fi

echo "[check_all] frontend typecheck"
cd "$ROOT/frontend/web"
npm run typecheck

echo "[check_all] frontend build"
npm run build

if [ -f node_modules/eslint/package.json ]; then
  echo "[check_all] frontend eslint"
  npm run lint
else
  echo "[check_all] frontend eslint skipped (npm install in frontend/web)"
fi

echo "[check_all] done"
