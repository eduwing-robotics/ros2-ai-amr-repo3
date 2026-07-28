#!/usr/bin/env bash
# Source a Simulator profile: eval "$(bash scripts/load_profile.sh sample)"
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIMULATOR_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROFILE="${1:-sample}"

python3 "$SCRIPT_DIR/load_profile.py" "$PROFILE" --root "$SIMULATOR_ROOT"
