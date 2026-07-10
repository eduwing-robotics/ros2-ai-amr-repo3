#!/usr/bin/env bash
# Open a visible terminal and start the real LMS server inside it.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RUN_IN_TERMINAL='
cd "$1" || exit 1
echo "[launcher] LMS real server preparing..."
echo "[launcher] root: $1"
echo
./scripts/bootstrap.sh
echo
echo "[launcher] LMS real server starting..."
./scripts/real.sh --dev
status=$?
echo
echo "[launcher] server exited with status: $status"
read -r -p "[launcher] Press Enter to close this terminal..." _
exit "$status"
'

if command -v x-terminal-emulator >/dev/null 2>&1; then
  exec x-terminal-emulator -e bash -lc "$RUN_IN_TERMINAL" bash "$ROOT"
fi

if command -v gnome-terminal >/dev/null 2>&1; then
  exec gnome-terminal -- bash -lc "$RUN_IN_TERMINAL" bash "$ROOT"
fi

if command -v konsole >/dev/null 2>&1; then
  exec konsole -e bash -lc "$RUN_IN_TERMINAL" bash "$ROOT"
fi

if command -v xfce4-terminal >/dev/null 2>&1; then
  exec xfce4-terminal -e "bash -lc '$RUN_IN_TERMINAL' bash '$ROOT'"
fi

if command -v mate-terminal >/dev/null 2>&1; then
  exec mate-terminal -- bash -lc "$RUN_IN_TERMINAL" bash "$ROOT"
fi

if command -v lxterminal >/dev/null 2>&1; then
  exec lxterminal -e bash -lc "$RUN_IN_TERMINAL" bash "$ROOT"
fi

if command -v xterm >/dev/null 2>&1; then
  exec xterm -e bash -lc "$RUN_IN_TERMINAL" bash "$ROOT"
fi

cd "$ROOT"
echo "[launcher] No supported terminal emulator found. Starting in current process."
./scripts/bootstrap.sh
exec ./scripts/real.sh --dev
