#!/usr/bin/env bash
# Layered local verification: unit tests, config validators, Python compile.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"

# Verification must use the dependencies installed for this service.  An
# explicit PYTHON_BIN remains available for CI or deliberately custom setups.
if [[ -n "${PYTHON_BIN:-}" ]]; then
  PYTHON_BIN="$PYTHON_BIN"
else
  PYTHON_BIN="$ROOT/.venv/bin/python"
  if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "[check_all] Nav virtual environment is missing: $PYTHON_BIN" >&2
    echo "[check_all] Create it with: scripts/setup_nav_server_env.sh" >&2
    echo "[check_all] To use another interpreter explicitly, set PYTHON_BIN=/path/to/python." >&2
    exit 1
  fi
fi

if [[ ! -f "$ROS_SETUP" ]]; then
  echo "[check_all] ROS setup is missing: $ROS_SETUP" >&2
  echo "[check_all] Set ROS_SETUP to the installed ROS 2 setup.bash." >&2
  exit 1
fi
# shellcheck source=/dev/null
set +u
source "$ROS_SETUP"
set -u
"$PYTHON_BIN" -c 'import rclpy' || {
  echo "[check_all] the selected Python cannot import rclpy after sourcing $ROS_SETUP" >&2
  exit 1
}

cd "$ROOT"

echo "[check_all] py_compile nav_app + deployment scripts"
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
  scripts/nav_server.py \
  scripts/logistics_navigator.py \
  map/generate_factory_map.py

echo "[check_all] ruff"
"$PYTHON_BIN" -m ruff check nav_app scripts/nav_server.py scripts/logistics_navigator.py map/generate_factory_map.py tests

echo "[check_all] pytest (unit/contract layer; no live ROS graph)"
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 "$PYTHON_BIN" -m pytest tests/ -q

echo "[check_all] config validators"
"$PYTHON_BIN" "$SCRIPT_DIR/validate_robot_domains.py" --config "$ROOT/config/robots.json" --bridge-dir "$ROOT/config/domain_bridge"
"$PYTHON_BIN" "$SCRIPT_DIR/validate_zones.py" --scope field-e2e
"$PYTHON_BIN" -c 'from nav_app.config import MAIN_SERVER_ROUTES; assert MAIN_SERVER_ROUTES["nav_pc_host"]'

echo "[check_all] shell syntax"
while IFS= read -r -d '' script; do
  bash -n "$script"
done < <(find "$SCRIPT_DIR" -type f -name '*.sh' -print0)

echo "[check_all] smoke layer (requires running nav servers for full pass)"
echo "  optional: SIMULATION_MODE=1 scripts/smoke_nav_servers.sh"
echo "  optional: scripts/smoke_movement_api.sh"
echo "  optional: scripts/smoke_main_contract.sh"

echo "[check_all] done"
