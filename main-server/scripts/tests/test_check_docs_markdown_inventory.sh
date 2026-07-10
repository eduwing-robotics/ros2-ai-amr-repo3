#!/usr/bin/env bash
# Regression checks for the docs gate's Git-backed Markdown inventory.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
GATE="$ROOT/scripts/check_docs.sh"
ignored_markdown="$ROOT/.pytest_cache/check_docs_ignored_cache.md"
misplaced_markdown="$ROOT/check_docs_misplaced_markdown.md"

if [[ -e "$ignored_markdown" || -e "$misplaced_markdown" ]]; then
  echo 'docs gate regression fixture path already exists' >&2
  exit 1
fi

cleanup() {
  rm -f "$ignored_markdown" "$misplaced_markdown"
}
trap cleanup EXIT

mkdir -p "$(dirname "$ignored_markdown")"
printf '# ignored cache markdown\n' >"$ignored_markdown"
git check-ignore -q -- .pytest_cache/check_docs_ignored_cache.md

if ! output="$("$GATE" 2>&1)"; then
  printf '%s\n' "$output" >&2
  echo 'docs gate failed for ignored cache Markdown' >&2
  exit 1
fi
[[ "$output" != *"$ignored_markdown"* ]]

printf '# misplaced markdown\n' >"$misplaced_markdown"
if output="$("$GATE" 2>&1)"; then
  printf '%s\n' "$output" >&2
  echo 'docs gate accepted unignored Markdown outside allowed roots' >&2
  exit 1
fi
[[ "$output" == *'Markdown file outside allowed roots: check_docs_misplaced_markdown.md'* ]]

echo '[check_docs_markdown_inventory] PASS'
