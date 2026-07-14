#!/usr/bin/env bash
# Compatibility entrypoint for the supported signed Main↔Nav↔AI no-hardware smoke.

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

echo "[smoke_movement_api] delegating to repository signed no-hardware TCP E2E"
exec "$REPO_ROOT/scripts/test-nohardware-tcp.sh"
