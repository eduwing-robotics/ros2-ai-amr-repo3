#!/usr/bin/env bash
# Repository verification dispatcher.
set -euo pipefail
SCRIPT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
  echo "Usage: ./scripts/check.sh <backend|frontend|ux|db|docs|hygiene|operator|pg|all>" >&2
  exit 2
}

check_backend() {

ROOT="$SCRIPT_ROOT"
PYTHON="$ROOT/backend/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="$ROOT/backend/.venv/Scripts/python.exe"
if [[ ! -x "$PYTHON" ]]; then
  echo "[backend-unit] ERROR: backend venv missing. Run ./scripts/bootstrap.sh --skip-db" >&2
  exit 2
fi

cd "$ROOT/backend"
echo "[backend-unit] syntax"
"$PYTHON" -m compileall -q app
echo "[backend-unit] ruff"
"$PYTHON" -m ruff check app tests
echo "[backend-unit] pytest (PostgreSQL tests skipped unless a URL is explicit)"
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 "$PYTHON" -m pytest -q

}

check_db() {

ROOT="$SCRIPT_ROOT"
export PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-3}"
PYTHON="$ROOT/backend/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="$ROOT/backend/.venv/Scripts/python.exe"
if [[ ! -x "$PYTHON" ]]; then
  echo "[db] ERROR: backend venv missing. Run ./scripts/bootstrap.sh --skip-db" >&2
  exit 2
fi

if [[ -z "${LMS_DATABASE_URL:-${DATABASE_URL:-}}" && -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(grep -E '^LMS_DATABASE_URL=' "$ROOT/.env" | sed 's/^/export /')
  set +a
fi
if [[ -z "${LMS_DATABASE_URL:-${DATABASE_URL:-}}" ]]; then
  echo "[db] ERROR: LMS_DATABASE_URL or DATABASE_URL is required" >&2
  exit 2
fi

cd "$ROOT/backend"
TEST_DATABASE_URL="$("$PYTHON" tests/prepare_test_db.py)"
export LMS_DATABASE_URL="$TEST_DATABASE_URL"
export DATABASE_URL="$TEST_DATABASE_URL"
check_pg
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 "$PYTHON" -m pytest -q

}

check_docs() {

ROOT="$SCRIPT_ROOT"
cd "$ROOT"

PYTHON="$ROOT/backend/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="$ROOT/backend/.venv/Scripts/python.exe"
command -v "$PYTHON" >/dev/null 2>&1 || PYTHON=python3
"$PYTHON" scripts/check_docs.py

fail=0
err() { echo "[docs] ERROR: $*" >&2; fail=1; }
warn() { echo "[docs] WARN: $*" >&2; }

# Root markdown policy.
while IFS= read -r file; do
  case "$file" in
    ./README.md|./AGENTS.md) ;;
    ./docs/*|./worklog/*) ;;
    *) err "Markdown file outside allowed roots: $file" ;;
  esac
done < <(find . \
  -path './.git' -prune -o \
  -path './frontend/web/node_modules' -prune -o \
  -path './frontend/web/dist' -prune -o \
  -path './frontend/web/.claude' -prune -o \
  -path './backend/.venv' -prune -o \
  -path './backend/.pytest_cache' -prune -o \
  -path './database/legacy' -prune -o \
  -path './ref' -prune -o \
  -path './slides' -prune -o \
  -path './docs/internal' -prune -o \
  -path './docs/archive' -prune -o \
  -path './worklog' -prune -o \
  -name '*.md' -type f -print)

# Public Markdown is intentionally flat under docs/.
while IFS= read -r file; do
  case "$file" in
    docs/README.md|docs/GLOSSARY.md|docs/ARCHITECTURE.md|docs/DATABASE.md|docs/INTERFACES.md|docs/API.md|docs/OPERATIONS.md|docs/UX.md|docs/TEST_CASES.md|docs/MOVEMENT_SERVER_REQUIREMENTS.md) ;;
    *) err "Unexpected public Markdown file: $file" ;;
  esac
done < <(find docs -maxdepth 1 -name '*.md' -type f -print)

required_meta=("상태:" "소유:" "최종 갱신:" "목적:")
should_check_meta() {
  case "$1" in
    ./docs/*.md) return 0 ;;
    *) return 1 ;;
  esac
}

allow_long_doc() {
  case "$1" in
    *) return 1 ;;
  esac
}

while IFS= read -r file; do
  case "$file" in
    ./README.md|./AGENTS.md) continue ;;
  esac
  should_check_meta "$file" || continue
  head -n 12 "$file" | grep -q '^# ' || err "Missing title heading: $file"
  for meta in "${required_meta[@]}"; do
    head -n 12 "$file" | grep -q "$meta" || err "Missing metadata '$meta' in $file"
  done
  updated_line=$(head -n 12 "$file" | grep '^최종 갱신:' || true)
  if [[ -n "$updated_line" ]]; then
    if ! grep -Eq '^최종 갱신: ([0-9]{4})-([0-9]{2})-([0-9]{2}) ([0-9]{2}):([0-9]{2}) KST$|^최종 갱신: YYYY-MM-DD HH:MM KST$' <<< "$updated_line"; then
      err "Invalid updated timestamp format in $file: expected YYYY-MM-DD HH:MM KST"
    fi
  fi
done < <(find docs \
  -path 'docs/internal' -prune -o \
  -path 'docs/archive' -prune -o \
  -name '*.md' -type f -print 2>/dev/null | sed 's#^#./#')

while IFS= read -r file; do
  base="$(basename "$file")"
  [[ "$base" =~ \([0-9]+\) ]] && err "Copy suffix is not allowed: $file"
done < <(find docs \
  -path 'docs/internal' -prune -o \
  -path 'docs/archive' -prune -o \
  -name '*.md' -type f -print 2>/dev/null | sed 's#^#./#')

check_limit() {
  local dir="$1" glob="$2" limit="$3"
  [[ -d "$dir" ]] || return 0
  while IFS= read -r file; do
    [[ -e "$file" ]] || continue
    local lines
    lines=$(wc -l < "$file")
    if (( lines > limit )) && ! allow_long_doc "$file"; then
    warn "Line budget exceeded ($lines > $limit): $file"
    fi
  done < <(find "$dir" -maxdepth 1 -name "$glob" -type f -print)
}

# Public canonical documents share one upper line budget.
check_limit 'docs' '*.md' 450

# Drift (public canons ↔ code)
check_drift() {
  local doc="$1"; shift
  [[ -f "$doc" ]] || return 0
  local dirs=() d
  for d in "$@"; do [[ -e "$d" ]] && dirs+=("$d"); done
  (( ${#dirs[@]} )) || return 0
  local newer
  newer=$(find "${dirs[@]}" -type f \
      -not -path '*/node_modules/*' -not -path '*/dist/*' \
      -not -path '*/__pycache__/*' -not -path '*/.venv/*' \
      -newer "$doc" -print -quit 2>/dev/null)
  if [[ -n "$newer" ]]; then
    warn "$doc 검토 필요 — 대상 코드가 더 최근에 변경됨 (예: ${newer#./})"
  fi
}

check_drift docs/UX.md frontend/web/src
check_drift docs/API.md backend/app/api
check_drift docs/DATABASE.md database backend/app/db
check_drift docs/ARCHITECTURE.md backend/app/domains backend/app/core
check_drift docs/INTERFACES.md backend/app/domains
check_drift docs/MOVEMENT_SERVER_REQUIREMENTS.md backend/app/domains/movement backend/app/domains/execution

if (( fail )); then
  exit 1
fi
echo "[docs] OK"

}

check_frontend() {

ROOT="$SCRIPT_ROOT"
cd "$ROOT/frontend/web"
if [[ ! -f node_modules/typescript/package.json ]]; then
  echo "[frontend] ERROR: dependencies missing. Run npm ci in frontend/web" >&2
  exit 2
fi

npm run typecheck
npm run lint
npm run build

}

check_ux() {
  ROOT="$SCRIPT_ROOT"
  cd "$ROOT/frontend/web"
  npm run test:ux
}

check_operator() {
# Default mode is read-only. Set LMS_VERIFY_MUTATING=1 only against a test/disposable
# server if you want to create a sample work order and verify robot_id assignment.
set -euo pipefail

ROOT="$SCRIPT_ROOT"
API_BASE="${LMS_VERIFY_API_BASE:-http://localhost:8088/api/v1}"
PY="${PYTHON:-python3}"

fail() {
  echo "[operator-control] FAIL: $*" >&2
  exit 1
}

pass() {
  echo "[operator-control] OK: $*"
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "$1 is required"
}

curl_json() {
  local url="$1"
  curl -fsS "$url"
}

post_json() {
  local url="$1" body="$2"
  curl -fsS -X POST "$url" -H "Content-Type: application/json" -d "$body"
}

json_get() {
  local expr="$1"
  "$PY" -c '
import json, sys
data = json.load(sys.stdin)
expr = sys.argv[1]
try:
    safe = {"all": all, "any": any, "bool": bool, "float": float, "int": int, "len": len, "next": next, "str": str, "sum": sum}
    value = eval(expr, {"__builtins__": safe}, {"data": data})
except Exception as exc:
    raise SystemExit(f"json expression failed: {exc}")
if isinstance(value, (dict, list)):
    print(json.dumps(value, ensure_ascii=False))
elif value is None:
    print("")
else:
    print(value)
' "$expr"
}

need_cmd curl
need_cmd "$PY"

echo "[operator-control] API_BASE=$API_BASE"

status_json="$(curl_json "$API_BASE/status")" || fail "cannot reach $API_BASE/status"
movement_mode="$(printf '%s' "$status_json" | json_get 'data.get("system", {}).get("movement_mode", "")')"
[[ "$movement_mode" == "http" ]] || fail "movement_mode is not http: $movement_mode"
pass "Main server is real/http"

maps_json="$(curl_json "$API_BASE/maps")" || fail "cannot reach $API_BASE/maps"
map_count="$(printf '%s' "$maps_json" | json_get 'len(data)')"
[[ "$map_count" -gt 0 ]] || fail "GET /maps returned no maps"

selected_map="$(printf '%s' "$maps_json" | json_get 'next((m for m in data if m.get("map_id") == "robot2_map"), data[0])')"
map_id="$(printf '%s' "$selected_map" | json_get 'data.get("map_id", "")')"
image_url="$(printf '%s' "$selected_map" | json_get 'data.get("image_url", "")')"
asset_status="$(printf '%s' "$selected_map" | json_get 'data.get("asset_status", "")')"
runtime_map_id="$(printf '%s' "$selected_map" | json_get 'data.get("runtime_map_id", "")')"

[[ -n "$image_url" ]] || fail "map $map_id has empty image_url; UI cannot render a background"
curl -fsSI "${API_BASE%/api/v1}${image_url}" >/dev/null || fail "map image is not reachable: $image_url"
pass "map $map_id has reachable image_url ($asset_status, runtime=$runtime_map_id)"

if [[ "$asset_status" == "mismatch" ]]; then
  echo "[operator-control] WARN: map/runtime mismatch remains; UI must show background plus warning, not blank map"
fi

tasks_json="$(curl_json "$API_BASE/tasks?limit=20")" || fail "cannot reach /tasks"
assigned_visible_count="$(printf '%s' "$tasks_json" | json_get 'sum(1 for t in data if t.get("assigned_robot_id"))')"
running_without_robot="$(printf '%s' "$tasks_json" | json_get '[t.get("task_id") for t in data if t.get("status") in {"ASSIGNED", "RUNNING"} and not t.get("assigned_robot_id")]')"
[[ "$running_without_robot" == "[]" ]] || fail "active tasks without assigned_robot_id: $running_without_robot"
pass "active task API exposes assigned_robot_id; assigned rows=$assigned_visible_count"

work_orders_json="$(curl_json "$API_BASE/work-orders?limit=20")" || fail "cannot reach /work-orders"
wo_missing_robot="$(printf '%s' "$work_orders_json" | json_get '[o.get("order_id") for o in data for t in o.get("tasks", []) if t.get("status") in {"ASSIGNED", "RUNNING"} and not t.get("assigned_robot_id")]')"
[[ "$wo_missing_robot" == "[]" ]] || fail "active work order tasks without assigned_robot_id: $wo_missing_robot"
pass "work order API exposes assigned_robot_id for active task rows"

if [[ "${LMS_VERIFY_MUTATING:-0}" != "1" ]]; then
  echo "[operator-control] SKIP: mutating robot_id work-order check (set LMS_VERIFY_MUTATING=1 on a test/disposable server)"
  exit 0
fi

if [[ "${LMS_ALLOW_MUTABLE_DB_TESTS:-0}" != "1" ]]; then
  fail "refusing mutating check without LMS_ALLOW_MUTABLE_DB_TESTS=1"
fi

target_robot="${LMS_VERIFY_ROBOT_ID:-tb3_2}"
item_code="${LMS_VERIFY_ITEM_CODE:-bolt_1}"
quantity="${LMS_VERIFY_QUANTITY:-1}"

body="$(printf '{"operation":"inbound","item_code":"%s","quantity":%s,"auto_start":false,"robot_id":"%s","created_by":"phase79_verify"}' "$item_code" "$quantity" "$target_robot")"
created="$(post_json "$API_BASE/work-orders" "$body")" || fail "work order creation with robot_id failed"
order_id="$(printf '%s' "$created" | json_get 'data.get("order_id")')"
assigned="$(printf '%s' "$created" | json_get 'next((t.get("assigned_robot_id") for t in data.get("tasks", []) if t.get("assigned_robot_id")), "")')"

[[ "$assigned" == "$target_robot" ]] || fail "work order $order_id was not assigned to $target_robot (assigned=$assigned). Manual robot assignment contract is not implemented or sweeper stole it."
pass "work order $order_id honors robot_id=$target_robot"

}

check_pg() {
set -euo pipefail

ROOT="$SCRIPT_ROOT"
export PGCONNECT_TIMEOUT="${PGCONNECT_TIMEOUT:-3}"
PYTHON="$ROOT/backend/.venv/bin/python"
[[ -x "$PYTHON" ]] || PYTHON="$ROOT/backend/.venv/Scripts/python.exe"
if [[ ! -x "$PYTHON" ]]; then
  echo "[check_pg_mvp] ERROR: backend venv missing. Run ./scripts/bootstrap.sh --skip-db" >&2
  exit 2
fi

if [[ -z "${LMS_DATABASE_URL:-${DATABASE_URL:-}}" && -f "$ROOT/.env" ]]; then
  set -a
  # shellcheck disable=SC1091
  source <(grep -E '^LMS_DATABASE_URL=' "$ROOT/.env" | sed 's/^/export /')
  set +a
fi

URL="${LMS_DATABASE_URL:-${DATABASE_URL:-}}"

if [[ -z "$URL" ]]; then
  echo "[check_pg_mvp] ERROR: LMS_DATABASE_URL is required (see .env.example)" >&2
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
"$PYTHON" -c "from app.db.connection import init_db; from tests.support.postgres import apply_demo_fixture; init_db(); apply_demo_fixture()"
"$PYTHON" -m app.db.cli status
"$PYTHON" -m app.db.cli reference-sync
"$PYTHON" -m unittest tests.test_postgres_inout tests.test_pg_ddl_smoke tests.test_command_evidence_runtime tests.test_seed_persistence -v
echo "[check_pg_mvp] ok"

}

check_hygiene() {

ROOT="$SCRIPT_ROOT"
cd "$ROOT/.."

patterns='(^|/)(node_modules|__pycache__|\.bootstrap|backups|\.claude|\.agents|\.codex|test-results|playwright-report)(/|$)|(^|/)\.env($|\.)|\.(pyc|tsbuildinfo|log|pid|pid\.lock|pem|key|p12|pfx|jks)$|(^|/)dist/|(^|/)data/.*\.(db|sqlite|sqlite3)$'
tracked="$(git ls-files | grep -E "$patterns" | grep -Ev '(^|/)\.env\.example$' || true)"
if [[ -n "$tracked" ]]; then
  echo "[hygiene] ERROR: generated, local, or sensitive files are tracked:" >&2
  echo "$tracked" >&2
  exit 1
fi
echo "[hygiene] clean"

}

check_all() {
  echo "[check] docs"; check_docs
  echo "[check] repository hygiene"; check_hygiene
  echo "[check] backend unit"; check_backend
  echo "[check] frontend"; check_frontend
  echo "[check] UX browser"; check_ux
  echo "[check] PostgreSQL integration"; check_db
  echo "[check] done"
}

COMMAND="${1:-}"
[[ -n "$COMMAND" ]] || usage
shift
case "$COMMAND" in
  backend) check_backend "$@" ;;
  frontend) check_frontend "$@" ;;
  ux) check_ux "$@" ;;
  db) check_db "$@" ;;
  docs) check_docs "$@" ;;
  hygiene) check_hygiene "$@" ;;
  operator) check_operator "$@" ;;
  pg) check_pg "$@" ;;
  all) check_all "$@" ;;
  *) usage ;;
esac
