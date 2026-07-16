#!/usr/bin/env bash
set -euo pipefail

log() {
  printf '[bootstrap-nohardware-envs] %s\n' "$*"
}

fail() {
  printf '[bootstrap-nohardware-envs] ERROR: %s\n' "$*" >&2
  exit 1
}

require_file() {
  local path=$1
  [[ -f "$path" ]] || fail "required file not found: $path"
}

require_dir() {
  local path=$1
  [[ -d "$path" ]] || fail "required directory not found: $path"
}

create_or_update_venv() {
  local name=$1
  local venv_dir=$2
  local requirements=$3
  local dev_requirements=$4

  require_file "$requirements"
  require_file "$dev_requirements"

  log "--- $name ---"
  log "venv: $venv_dir"
  log "requirements: $requirements"
  log "dev requirements: $dev_requirements"

  if [[ ! -x "$venv_dir/bin/python" ]]; then
    if [[ -e "$venv_dir" ]]; then
      fail "existing venv path is not usable and will not be overwritten automatically: $venv_dir"
    fi
    log "creating virtual environment with: $PYTHON_BIN"
    "$PYTHON_BIN" -m venv "$venv_dir"
  else
    log "reusing existing virtual environment"
  fi

  local venv_python="$venv_dir/bin/python"

  log "python: $("$venv_python" -c 'import sys; print(sys.executable)')"
  log "python version: $("$venv_python" -c 'import sys; print(sys.version.replace(chr(10), " "))')"

  log "upgrading venv packaging tools"
  "$venv_python" -m pip install --upgrade pip setuptools wheel

  log "installing runtime requirements"
  "$venv_python" -m pip install -r "$requirements"

  log "installing development requirements"
  "$venv_python" -m pip install -r "$dev_requirements"

  log "running pip check for $name"
  "$venv_python" -m pip check
  log "$name pip check passed"
}

main() {
  local script_dir repo_root
  script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
  repo_root=$(cd -- "$script_dir/.." && pwd -P)

  PYTHON_BIN=${PYTHON_BIN:-python3}
  export PYTHON_BIN

  command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "PYTHON_BIN not found or not executable: $PYTHON_BIN"
  "$PYTHON_BIN" - <<'PY' || fail "PYTHON_BIN must be Python 3.8+ with venv support"
import ensurepip  # noqa: F401
import sys
if sys.version_info < (3, 8):
    raise SystemExit(f"Python 3.8+ required, got {sys.version.split()[0]}")
PY

  log "repo root: $repo_root"
  log "PYTHON_BIN: $PYTHON_BIN"
  log "system Python will not be modified; all installs target service-local virtualenvs"

  require_dir "$repo_root/ai-server"
  require_dir "$repo_root/main-server/backend"
  require_dir "$repo_root/main-server/frontend/web"
  require_dir "$repo_root/nav-server"
  require_file "$repo_root/main-server/frontend/web/package-lock.json"
  command -v npm >/dev/null 2>&1 || fail "npm is required for the built Main UI acceptance"

  create_or_update_venv \
    "ai-server" \
    "$repo_root/ai-server/.venv" \
    "$repo_root/ai-server/requirements.txt" \
    "$repo_root/ai-server/requirements-dev.txt"

  create_or_update_venv \
    "main-server" \
    "$repo_root/main-server/.venv" \
    "$repo_root/main-server/backend/requirements.txt" \
    "$repo_root/main-server/backend/requirements-dev.txt"

  create_or_update_venv \
    "nav-server" \
    "$repo_root/nav-server/.venv" \
    "$repo_root/nav-server/requirements.txt" \
    "$repo_root/nav-server/requirements-dev.txt"

  log "--- main-server frontend ---"
  log "installing the exact package-lock dependency tree"
  (cd "$repo_root/main-server/frontend/web" && npm ci)

  log "all virtual environments and frontend dependencies are ready"
}

main "$@"
