#!/usr/bin/env bash
# Backward-compatible entry point for the disposable no-hardware DB gate.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec "$ROOT/scripts/tests/check_nohardware_pg.sh"
