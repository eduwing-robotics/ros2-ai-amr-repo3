#!/usr/bin/env bash
# Restore nav-stack files from a snapshot created by save_nav_stack_snapshot.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SNAP_ROOT="${SNAP_ROOT:-$ROOT/backups/nav_stack_snapshots}"

usage() {
  cat <<'EOF'
Usage:
  scripts/restore_nav_stack_snapshot.sh [snapshot_name] [--list]

Examples:
  scripts/restore_nav_stack_snapshot.sh --list
  scripts/restore_nav_stack_snapshot.sh baseline_pre_ekf_20260708
EOF
}

if [[ "${1:-}" == "-h" || "${1:-}" == "--help" ]]; then
  usage
  exit 0
fi

if [[ "${1:-}" == "--list" || -z "${1:-}" ]]; then
  echo "Available snapshots under $SNAP_ROOT:"
  if [[ ! -d "$SNAP_ROOT" ]]; then
    echo "  (none)"
    exit 0
  fi
  find "$SNAP_ROOT" -mindepth 1 -maxdepth 1 -type d -printf '  %f\n' | sort
  [[ -n "${1:-}" ]] || exit 0
fi

NAME="$1"
DEST="$SNAP_ROOT/$NAME"
MANIFEST="$DEST/MANIFEST.txt"

if [[ ! -f "$MANIFEST" ]]; then
  echo "[restore] snapshot not found: $DEST" >&2
  exit 1
fi

echo "[restore] using $DEST"
grep -E '^description=|^created=' "$MANIFEST" || true

mapfile -t TRACKED < <(awk '/^\[tracked_files\]/{f=1;next} /^\[/{f=0} f && NF{print}' "$MANIFEST")
mapfile -t EKF_ADDED < <(awk '/^\[ekf_added_files\]/{f=1;next} /^\[/{f=0} f && NF{print}' "$MANIFEST")

for rel in "${TRACKED[@]}"; do
  src="$DEST/files/$rel"
  dst="$ROOT/$rel"
  if [[ ! -f "$src" ]]; then
    echo "[restore] WARNING: missing in snapshot: $rel" >&2
    continue
  fi
  mkdir -p "$(dirname "$dst")"
  cp -a "$src" "$dst"
  echo "[restore] restored $rel"
done

for rel in "${EKF_ADDED[@]}"; do
  dst="$ROOT/$rel"
  if [[ -e "$dst" ]]; then
    rm -rf "$dst"
    echo "[restore] removed EKF file $rel"
  fi
done

echo "[restore] done. Restart stack: WITH_EKF=0 scripts/start_all_tb3_2.sh restart"
