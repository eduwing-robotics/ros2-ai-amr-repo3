#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
VENV_DIR="${NAV_SERVER_VENV_DIR:-$ROOT/.venv}"
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"

usage() {
	cat <<'EOF'
Usage: scripts/setup_nav_server_env.sh

Creates or updates nav-server/.venv from requirements-dev.txt and runs
pip check. ROS 2 packages remain provided by the system ROS installation.

Environment:
  PYTHON_BIN          Python used to create the environment. Default: python3
  NAV_SERVER_VENV_DIR Target virtualenv. Default: nav-server/.venv
  ROS_SETUP           System ROS 2 setup.bash. Default: /opt/ros/jazzy/setup.bash
EOF
}

fail() {
	printf '[setup_nav_server_env] ERROR: %s\n' "$*" >&2
	exit 1
}

case "${1:-}" in
"") ;;
-h | --help)
	usage
	exit 0
	;;
*)
	usage >&2
	fail "unknown argument: $1"
	;;
esac

command -v "$PYTHON_BIN" >/dev/null 2>&1 || fail "Python not found: $PYTHON_BIN"
[[ -f "$ROOT/requirements-dev.txt" ]] || fail "missing requirements-dev.txt"

"$PYTHON_BIN" - <<'PY' || fail "Python 3.10+ with venv support is required"
import ensurepip  # noqa: F401
import sys

if sys.version_info < (3, 10):
    raise SystemExit(f"Python 3.10+ required, got {sys.version.split()[0]}")
PY

if [[ ! -x "$VENV_DIR/bin/python" ]]; then
	[[ ! -e "$VENV_DIR" ]] || fail "existing path is not a usable virtualenv: $VENV_DIR"
	printf '[setup_nav_server_env] creating %s\n' "$VENV_DIR"
	"$PYTHON_BIN" -m venv "$VENV_DIR"
else
	printf '[setup_nav_server_env] reusing %s\n' "$VENV_DIR"
fi

VENV_PYTHON="$VENV_DIR/bin/python"
"$VENV_PYTHON" -m pip install --upgrade pip setuptools wheel
"$VENV_PYTHON" -m pip install -r "$ROOT/requirements-dev.txt"
"$VENV_PYTHON" -m pip check

if [[ -f "$ROS_SETUP" ]]; then
	# shellcheck source=/dev/null
	set +u
	source "$ROS_SETUP"
	set -u
	"$VENV_PYTHON" -c 'import rclpy' || fail "virtualenv cannot import rclpy after sourcing $ROS_SETUP"
	printf '[setup_nav_server_env] ROS Python import ready via %s\n' "$ROS_SETUP"
else
	printf '[setup_nav_server_env] WARNING: ROS setup not found: %s\n' "$ROS_SETUP" >&2
	printf '[setup_nav_server_env] Python dependencies are ready, but check_all and physical startup require ROS 2.\n' >&2
fi

cat <<EOF
[setup_nav_server_env] ready

Activate:
  source "$VENV_DIR/bin/activate"

Verify:
  cd "$ROOT"
  scripts/check_all.sh

Physical ROS/Nav2 startup still requires the system ROS environment, normally:
  source "$ROS_SETUP"
EOF
