#!/usr/bin/env bash
# Configure Nav/API/RViz participants to discover only same-PC peers.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export SMARTFACTORY_DDS_PEER_MODE=self
export SMARTFACTORY_DDS_ROUTE_PROBE="${SMARTFACTORY_DDS_ROUTE_PROBE:-smartfactory-robot1.local}"

# shellcheck source=configure_cyclonedds_lan.sh
source "$SCRIPT_DIR/configure_cyclonedds_lan.sh"
