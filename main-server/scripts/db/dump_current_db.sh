#!/usr/bin/env bash
# Compatibility entry point for the canonical database snapshot command.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "$ROOT/scripts/dump_current_db.sh" "$@"
