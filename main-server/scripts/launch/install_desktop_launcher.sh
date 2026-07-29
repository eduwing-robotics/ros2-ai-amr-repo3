#!/usr/bin/env bash
# Compatibility entry point for the canonical desktop launcher installer.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "$ROOT/scripts/install_desktop_launcher.sh" "$@"
