#!/usr/bin/env bash
# Layered local verification: unit tests, config validators, Python compile.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

# Verification must use the dependencies installed for this service.  An
# explicit PYTHON_BIN remains available for CI or deliberately custom setups.
if [[ -n "${PYTHON_BIN:-}" ]]; then
  PYTHON_BIN="$PYTHON_BIN"
else
  PYTHON_BIN="$ROOT/.venv/bin/python"
  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "[check_all] Nav virtual environment is missing: $PYTHON_BIN" >&2
    echo "[check_all] Create it with: python3 -m venv .venv && .venv/bin/python -m pip install -r requirements-dev.txt" >&2
    echo "[check_all] To use another interpreter explicitly, set PYTHON_BIN=/path/to/python." >&2
    exit 1
  fi
fi

cd "$ROOT"

echo "[check_all] py_compile nav_app + scripts/nav_server.py"
"$PYTHON_BIN" -m py_compile \
  nav_app/bootstrap.py \
  nav_app/app.py \
  nav_app/runtime.py \
  nav_app/server_core.py \
  nav_app/adapters/callbacks.py \
  nav_app/config/loader.py \
  nav_app/config/validation.py \
  nav_app/models/requests.py \
  nav_app/routers/__init__.py \
  nav_app/routers/meta.py \
  nav_app/routers/movement_api.py \
  nav_app/routers/robot_commands.py \
  nav_app/routers/locks.py \
  nav_app/routers/mission.py \
  nav_app/services/command_state.py \
  nav_app/services/docking.py \
  nav_app/services/lift_client.py \
  nav_app/services/manual_control.py \
  nav_app/services/map_state.py \
  nav_app/services/mission_helpers.py \
  nav_app/services/movement_executor.py \
  nav_app/services/robot_commands.py \
  nav_app/services/robot_context.py \
  nav_app/services/route_helpers.py \
  nav_app/services/status_helpers.py \
  scripts/nav_server.py

echo "[check_all] pytest (ROS-free unit layer)"
"$PYTHON_BIN" -m pytest tests/ -q

echo "[check_all] config validators"
"$PYTHON_BIN" "$SCRIPT_DIR/validate_robot_domains.py" --config "$ROOT/config/robots.json" --bridge-dir "$ROOT/config/domain_bridge"
"$PYTHON_BIN" "$SCRIPT_DIR/validate_zones.py"

echo "[check_all] shell syntax"
bash -n "$SCRIPT_DIR/sim_ops.sh"

echo "[check_all] smoke layer (requires running nav servers for full pass)"
echo "  optional: SIMULATION_MODE=1 scripts/smoke_nav_servers.sh"
echo "  optional: scripts/smoke_movement_api.sh"
echo "  optional: scripts/smoke_main_contract.sh"

echo "[check_all] done"
