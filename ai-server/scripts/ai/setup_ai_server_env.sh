#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
SERVICE_DIR="${ROOT_DIR}"
VENV_DIR="${SERVICE_DIR}/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
MODEL_DIR="${AI_SERVER_MODEL_DIR:-${SERVICE_DIR}/models}"
DEFAULT_DETECT_MODEL="${AI_SERVER_DEFAULT_DETECT_MODEL:-yolov8n.pt}"
DEFAULT_SEG_MODEL="${AI_SERVER_DEFAULT_SEG_MODEL:-yolov8s-seg.pt}"

# Keep AI Server Python isolated from a sourced ROS2 shell.
unset PYTHONPATH
export PYTHONNOUSERSITE=1

if [ ! -d "${VENV_DIR}" ]; then
  "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

"${VENV_DIR}/bin/python" -m pip install --upgrade pip setuptools wheel
"${VENV_DIR}/bin/python" -m pip install -r "${SERVICE_DIR}/requirements-dev.txt"
"${VENV_DIR}/bin/python" -m pip install -r "${SERVICE_DIR}/requirements-model.txt"

mkdir -p "${MODEL_DIR}"
(
  cd "${MODEL_DIR}"
  "${VENV_DIR}/bin/python" - "${DEFAULT_DETECT_MODEL}" "${DEFAULT_SEG_MODEL}" << 'PY'
from __future__ import annotations

import sys
from pathlib import Path

from ultralytics import YOLO

for model_name in sys.argv[1:]:
    path = Path(model_name)
    if path.exists():
        print(f"model already present: {path}")
        continue
    print(f"downloading pretrained model: {model_name}")
    YOLO(model_name)
    if not path.exists():
        raise SystemExit(f"model download did not create expected file: {path}")
    print(f"model ready: {path}")
PY
)

cat << MSG
AI Server environment ready.
Default pretrained models are ready under:
  ${MODEL_DIR}

Activate:
  source ${VENV_DIR}/bin/activate

Run:
  cd ${SERVICE_DIR}
  uvicorn app.main:app --host 127.0.0.1 --port 8100 --reload

Test:
  ./scripts/ai/test_ai_server.sh

Low-load:
  ./scripts/vision/sf_lab.sh low-load

Note:
  setup does not rewrite requirements.lock. That file is kept stable for the
  optional API-only Docker image; local model packages live in this .venv.
MSG
