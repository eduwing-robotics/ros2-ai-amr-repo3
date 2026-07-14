#!/usr/bin/env bash
# Compatibility shim. Repository documentation policy lives at the root.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec "$ROOT/scripts/check_docs.sh" --scope main-server
