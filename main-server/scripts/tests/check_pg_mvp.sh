#!/usr/bin/env bash
# Compatibility entry point for the canonical PostgreSQL MVP gate.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "$ROOT/scripts/check_pg_mvp.sh" "$@"
