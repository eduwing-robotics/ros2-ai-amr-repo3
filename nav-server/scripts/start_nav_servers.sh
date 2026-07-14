#!/usr/bin/env bash
# Compatibility wrapper. New automation should call scripts/sf_nav.sh directly.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SF_NAV="$SCRIPT_DIR/sf_nav.sh"

usage() {
  cat <<'EOF'
Usage: scripts/start_nav_servers.sh {start|dry-run|foreground|status|stop|restart}

The selected runtime profile is controlled by SF_NAV_PROFILE; the manifest
default is tb1-live. Use SF_NAV_PROFILE=all-live for the legacy all-server path.
EOF
}

cmd="${1:-start}"
case "$cmd" in
  start) exec "$SF_NAV" up ;;
  dry-run) exec env DRY_RUN_MISSION=1 "$SF_NAV" up ;;
  # Attached terminal mode: Ctrl+C stops only this owned profile process group.
  foreground) exec "$SF_NAV" foreground ;;
  status) exec "$SF_NAV" status ;;
  stop) exec "$SF_NAV" down ;;
  restart) "$SF_NAV" down; exec "$SF_NAV" up ;;
  -h|--help|help) usage ;;
  *) echo "[nav_start] unknown command: $cmd" >&2; usage >&2; exit 2 ;;
esac
