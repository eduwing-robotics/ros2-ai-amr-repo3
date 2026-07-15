#!/usr/bin/env bash
set -u -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAV_PY="${NAV_PY:-${ROOT_DIR}/nav-server/.venv/bin/python}"
MAIN_PY="${MAIN_PY:-${ROOT_DIR}/main-server/.venv/bin/python}"
AI_PY="${AI_PY:-${ROOT_DIR}/ai-server/.venv/bin/python}"
FRONTEND_DIR="${FRONTEND_DIR:-${ROOT_DIR}/main-server/frontend/web}"
export NAV_PY MAIN_PY AI_PY FRONTEND_DIR
FAILED=0

echo "[nohardware] field-config: ${ROOT_DIR}/scripts/test-nohardware-config.sh"
"${ROOT_DIR}/scripts/test-nohardware-config.sh"
status=$?
if [[ ${status} -ne 0 ]]; then
  echo "[nohardware] field-config: FAILED (${status})" >&2
  FAILED=1
else
  echo "[nohardware] field-config: PASSED"
fi

run_pytest() {
  local service="$1"
  local python="$2"
  local workdir="$3"
  shift 3
  if [[ ! -x "${python}" ]]; then
    echo "[nohardware] ${service}: missing executable ${python}" >&2
    FAILED=127
    return 0
  fi
  echo "[nohardware] ${service}: ${python} -m pytest $*"
  (cd "${ROOT_DIR}/${workdir}" && "${python}" -m pytest "$@")
  local status=$?
  if [[ ${status} -ne 0 ]]; then
    echo "[nohardware] ${service}: FAILED (${status})" >&2
    FAILED=1
  else
    echo "[nohardware] ${service}: PASSED"
  fi
}

run_pytest_glob() {
  local service="$1"
  local python="$2"
  local workdir="$3"
  local pattern="$4"
  if [[ ! -x "${python}" ]]; then
    echo "[nohardware] ${service}: missing executable ${python}" >&2
    FAILED=127
    return 0
  fi
  echo "[nohardware] ${service}: ${python} -m pytest ${pattern}"
  (
    cd "${ROOT_DIR}/${workdir}" || exit 1
    local test_files=()
    while IFS= read -r test_file; do
      test_files+=("${test_file}")
    done < <(compgen -G "${pattern}" | sort)
    if [[ ${#test_files[@]} -eq 0 ]]; then
      echo "[nohardware] ${service}: no tests matched ${pattern}" >&2
      exit 5
    fi
    "${python}" -m pytest "${test_files[@]}"
  )
  local status=$?
  if [[ ${status} -ne 0 ]]; then
    echo "[nohardware] ${service}: FAILED (${status})" >&2
    FAILED=1
  else
    echo "[nohardware] ${service}: PASSED"
  fi
}

run_pytest "ai-server" "${AI_PY}" "ai-server" \
  tests/test_nohardware_lift_load_contract.py

run_pytest_glob "main-server" "${MAIN_PY}" "main-server/backend" \
  'tests/test_nohardware_*.py'

run_pytest "nav-server" "${NAV_PY}" "nav-server" \
  tests/test_nohardware_robot_command_contract.py


if [[ ${FAILED} -eq 0 ]]; then
  echo "[nohardware] tcp-smoke: ${ROOT_DIR}/scripts/test-nohardware-tcp.sh"
  "${ROOT_DIR}/scripts/test-nohardware-tcp.sh"
  status=$?
  if [[ ${status} -ne 0 ]]; then
    echo "[nohardware] tcp-smoke: FAILED (${status})" >&2
    FAILED=1
  else
    echo "[nohardware] tcp-smoke: PASSED"
  fi
fi

if [[ ${FAILED} -eq 0 ]]; then
  echo "[nohardware] tcp-lifecycle: staged abort, Ctrl-C, and request-timeout cleanup"
  "${MAIN_PY}" \
    "${ROOT_DIR}/tests/nohardware/check_nohardware_runner_lifecycle.py" \
    --runner "${ROOT_DIR}/scripts/test-nohardware-tcp.sh" \
    --dependency-root "${ROOT_DIR}"
  status=$?
  if [[ ${status} -ne 0 ]]; then
    echo "[nohardware] tcp-lifecycle: FAILED (${status})" >&2
    FAILED=1
  else
    echo "[nohardware] tcp-lifecycle: PASSED"
  fi
fi

if [[ ${FAILED} -eq 0 ]]; then
  echo "[nohardware] db-seam: ${ROOT_DIR}/scripts/test-nohardware-db.sh"
  "${ROOT_DIR}/scripts/test-nohardware-db.sh"
  status=$?
  if [[ ${status} -ne 0 ]]; then
    echo "[nohardware] db-seam: FAILED (${status})" >&2
    FAILED=1
  else
    echo "[nohardware] db-seam: PASSED"
  fi
fi

exit "${FAILED}"
