#!/usr/bin/env bash
# Compatibility entry point for the canonical local database reset.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "$ROOT/scripts/reset_local_db.sh" "$@"
