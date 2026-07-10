#!/usr/bin/env bash
# Compatibility source wrapper for the canonical PostgreSQL policy helpers.
source "$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)/scripts/lib/pg_bootstrap.sh"
