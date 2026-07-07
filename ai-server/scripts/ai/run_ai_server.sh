#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVICE_DIR="${ROOT_DIR}"
VENV_DIR="${AI_SERVER_VENV_DIR:-${SERVICE_DIR}/.venv}"

if [ ! -x "${VENV_DIR}/bin/uvicorn" ]; then
  echo "AI Server venv not found at ${VENV_DIR}. Run ./scripts/ai/setup_ai_server_env.sh or set AI_SERVER_VENV_DIR to a prepared env." >&2
  exit 1
fi

# Keep AI Server Python isolated from ROS2 PYTHONPATH if this shell sourced /opt/ros.
# Optional model-only extras can be supplied explicitly for a temporary YOLO/Torch
# runtime. Prefer a project-local AI_SERVER_VENV_DIR for reproducible runs.
unset PYTHONPATH
if [ -n "${AI_SERVER_EXTRA_PYTHONPATH:-}" ]; then
  export PYTHONPATH="${AI_SERVER_EXTRA_PYTHONPATH}"
fi
export PYTHONNOUSERSITE=1

cd "${SERVICE_DIR}"
UVICORN_ARGS=()
if [ "${AI_SERVER_ACCESS_LOG:-false}" != "true" ]; then
  UVICORN_ARGS+=(--no-access-log)
fi
exec "${VENV_DIR}/bin/uvicorn" app.main:app \
  --host "${AI_SERVER_HOST:-127.0.0.1}" \
  --port "${AI_SERVER_PORT:-8100}" \
  "${UVICORN_ARGS[@]}" \
  "${@}"
