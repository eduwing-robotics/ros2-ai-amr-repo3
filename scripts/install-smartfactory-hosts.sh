#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_FILE="${SMARTFACTORY_HOSTS_SOURCE:-$ROOT/config/network/smartfactory-hosts}"
HOSTS_FILE="${HOSTS_FILE:-/etc/hosts}"
BEGIN_MARKER="# BEGIN SMARTFACTORY HOSTS"
END_MARKER="# END SMARTFACTORY HOSTS"

usage() {
  cat <<'EOF'
Usage: scripts/install-smartfactory-hosts.sh [--check|--print|--apply]

  --check  Verify that canonical hostnames resolve to their 192.168.30.x addresses.
  --print  Print the managed /etc/hosts block.
  --apply  Replace existing SmartFactory host entries with the canonical block.
EOF
}

render_block() {
  printf '%s\n' "$BEGIN_MARKER"
  cat "$SOURCE_FILE"
  printf '%s\n' "$END_MARKER"
}

check_bindings() {
  local ip name resolved failed=0
  while read -r ip name _; do
    [[ -n "${ip:-}" && "${ip:0:1}" != "#" ]] || continue
    if [[ "$HOSTS_FILE" == "/etc/hosts" ]]; then
      resolved="$(getent ahostsv4 "$name" 2>/dev/null | awk 'NR == 1 {print $1}' || true)"
    else
      resolved="$(awk -v name="$name" '$0 !~ /^[[:space:]]*#/ {for (i = 2; i <= NF; i++) if ($i == name) {print $1; exit}}' "$HOSTS_FILE")"
    fi
    if [[ "$resolved" != "$ip" ]]; then
      printf 'ERROR: %s resolves to %s, expected %s\n' "$name" "${resolved:-<unresolved>}" "$ip" >&2
      failed=1
    else
      printf 'OK: %s -> %s\n' "$name" "$resolved"
    fi
  done < "$SOURCE_FILE"
  return "$failed"
}

apply_bindings() {
  local temp
  temp="$(mktemp)"
  trap "rm -f '$temp'" EXIT
  awk -v begin="$BEGIN_MARKER" -v end="$END_MARKER" '
    $0 == begin {managed = 1; next}
    $0 == end {managed = 0; next}
    managed {next}
    /(^|[[:space:]])smartfactory-(integration|main|nav|vision|robot1|robot2)(\.local)?([[:space:]]|$)/ {next}
    {print}
  ' "$HOSTS_FILE" > "$temp"
  [[ ! -s "$temp" ]] || [[ "$(tail -c 1 "$temp" | wc -l)" -gt 0 ]] || printf '\n' >> "$temp"
  render_block >> "$temp"

  if [[ -w "$HOSTS_FILE" ]]; then
    cat "$temp" > "$HOSTS_FILE"
  elif [[ "$HOSTS_FILE" == "/etc/hosts" ]] && command -v sudo >/dev/null 2>&1; then
    sudo cp -a "$HOSTS_FILE" "${HOSTS_FILE}.smartfactory.bak"
    sudo tee "$HOSTS_FILE" < "$temp" >/dev/null
  else
    printf 'ERROR: %s is not writable\n' "$HOSTS_FILE" >&2
    return 1
  fi
  check_bindings
}

[[ -f "$SOURCE_FILE" ]] || { printf 'ERROR: missing %s\n' "$SOURCE_FILE" >&2; exit 1; }

case "${1:---check}" in
  --check) check_bindings ;;
  --print) render_block ;;
  --apply) apply_bindings ;;
  -h|--help) usage ;;
  *) usage >&2; exit 2 ;;
esac
