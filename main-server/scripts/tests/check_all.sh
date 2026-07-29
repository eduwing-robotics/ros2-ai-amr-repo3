#!/usr/bin/env bash
# Compatibility entry point for the canonical Main verification gate.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "$ROOT/scripts/check_all.sh" "$@"
