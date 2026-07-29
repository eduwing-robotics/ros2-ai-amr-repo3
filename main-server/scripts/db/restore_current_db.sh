#!/usr/bin/env bash
# Compatibility entry point for the canonical database restore command.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "$ROOT/scripts/restore_current_db.sh" "$@"
