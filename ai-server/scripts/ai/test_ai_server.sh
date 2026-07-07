#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVICE_DIR="${ROOT_DIR}"
VENV_DIR="${SERVICE_DIR}/.venv"

if [ ! -x "${VENV_DIR}/bin/python" ]; then
  echo "AI Server venv not found. Run ./scripts/ai/setup_ai_server_env.sh first." >&2
  exit 1
fi

# Prevent ROS2 pytest plugins from leaking into the API service test run.
unset PYTHONPATH
export PYTHONNOUSERSITE=1
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

cd "${SERVICE_DIR}"
"${VENV_DIR}/bin/python" -m pytest tests "$@"
cd "${ROOT_DIR}"
python3 "${ROOT_DIR}/scripts/validate/validate_contracts.py"
