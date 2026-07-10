#!/usr/bin/env bash
set -u -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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
  local venv="$2"
  local workdir="$3"
  shift 3
  local pytest_bin="${ROOT_DIR}/${venv}/bin/pytest"
  if [[ ! -x "${pytest_bin}" ]]; then
    echo "[nohardware] ${service}: missing executable ${pytest_bin}" >&2
    FAILED=127
    return 0
  fi
  echo "[nohardware] ${service}: ${pytest_bin} $*"
  (cd "${ROOT_DIR}/${workdir}" && "${pytest_bin}" "$@")
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
  local venv="$2"
  local workdir="$3"
  local pattern="$4"
  local pytest_bin="${ROOT_DIR}/${venv}/bin/pytest"
  if [[ ! -x "${pytest_bin}" ]]; then
    echo "[nohardware] ${service}: missing executable ${pytest_bin}" >&2
    FAILED=127
    return 0
  fi
  echo "[nohardware] ${service}: ${pytest_bin} ${pattern}"
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
    "${pytest_bin}" "${test_files[@]}"
  )
  local status=$?
  if [[ ${status} -ne 0 ]]; then
    echo "[nohardware] ${service}: FAILED (${status})" >&2
    FAILED=1
  else
    echo "[nohardware] ${service}: PASSED"
  fi
}

run_pytest "ai-server" "ai-server/.venv" "ai-server" \
  tests/test_nohardware_lift_load_contract.py

run_pytest_glob "main-server" "main-server/.venv" "main-server/backend" \
  'tests/test_nohardware_*.py'

run_pytest "nav-server" "nav-server/.venv" "nav-server" \
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
