#!/usr/bin/env bash
# Save a restorable copy of nav-stack files (pre-EKF baseline, etc.).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
SNAP_ROOT="${SNAP_ROOT:-$ROOT/backups/nav_stack_snapshots}"

NAME="${1:-baseline_pre_ekf_$(date +%Y%m%d_%H%M%S)}"
DESC="${2:-Nav stack snapshot before EKF integration}"
DEST="$SNAP_ROOT/$NAME"

# Paths relative to repo root — keep in sync with restore_nav_stack_snapshot.sh
TRACKED=(
  scripts/run_nav2_with_initial_pose.sh
  scripts/logistics_navigator.py
  scripts/robot_sbc/start_bringup.sh
  scripts/start_all_tb3_2.sh
  nav_app/server_core.py
  nav_app/routers/meta.py
  nav_app/services/robot_context.py
  config/nav2/burger_smartfactory.yaml
  launch/navigation2_labeled.launch.py
  tests/test_stack_launcher_contract.py
  tests/test_fastapi_contract.py
)

# Files added when EKF mode is enabled (removed on restore to this snapshot)
EKF_ADDED=(
  config/robot_localization/ekf_tb3_burger.yaml
  config/robot_sbc/tb3_ekf_bringup_overlay.yaml
  config/nav2/burger_smartfactory_ekf.yaml
  launch/ekf_odom.launch.py
)

if [[ -e "$DEST" ]]; then
  echo "[snapshot] already exists: $DEST" >&2
  exit 1
fi

mkdir -p "$DEST/files"
{
  echo "name=$NAME"
  echo "created=$(date -Is)"
  echo "description=$DESC"
  echo ""
  echo "[tracked_files]"
  for rel in "${TRACKED[@]}"; do
    echo "$rel"
  done
  echo ""
  echo "[ekf_added_files]"
  for rel in "${EKF_ADDED[@]}"; do
    echo "$rel"
  done
} >"$DEST/MANIFEST.txt"

for rel in "${TRACKED[@]}"; do
  src="$ROOT/$rel"
  if [[ ! -f "$src" ]]; then
    echo "[snapshot] WARNING: missing (skipped): $rel" >&2
    continue
  fi
  mkdir -p "$DEST/files/$(dirname "$rel")"
  cp -a "$src" "$DEST/files/$rel"
  echo "[snapshot] saved $rel"
done

echo "[snapshot] OK: $DEST"
echo "[snapshot] Restore: scripts/restore_nav_stack_snapshot.sh $NAME"
