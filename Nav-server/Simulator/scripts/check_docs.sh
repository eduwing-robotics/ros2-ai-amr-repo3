#!/usr/bin/env bash
# Lightweight documentation layout checks (see nav2_REFECTOR Policy/01).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
errors=0

fail() {
  echo "[check_docs] $*" >&2
  errors=$((errors + 1))
}

# Root markdown policy
while IFS= read -r -d '' f; do
  base="$(basename "$f")"
  if [[ "$base" != "README.md" && "$base" != "AGENTS.md" ]]; then
    fail "unexpected root markdown: $f"
  fi
done < <(find "$ROOT" -maxdepth 1 -name '*.md' -print0)

# Required docs
for rel in \
  docs/README.md \
  docs/as-built/SIMULATOR.md \
  docs/reference/PATHS.md \
  docs/reference/CONFIG.md \
  docs/reference/DEVELOPER_GUIDE.md \
  docs/reference/AGENT_GUIDE.md \
  docs/reference/SCRIPTS.md \
  docs/runbook/RUN_HOST_NATIVE.md \
  docs/runbook/RUN_WITH_CUSTOM_MAP.md \
  docs/adr/2026-06-29-simulator-config-layout.md \
  .env.example; do
  [[ -f "$ROOT/$rel" ]] || fail "missing $rel"
done

# Profile samples
[[ -f "$ROOT/config/profiles/sample.json" ]] || fail "missing config/profiles/sample.json"

if (( errors > 0 )); then
  echo "[check_docs] $errors error(s)" >&2
  exit 1
fi
echo "[check_docs] OK"
