#!/usr/bin/env bash
# Copy slam_nav_ws Nav stack into this repo's Nav-server/ folder (excludes runtime junk).
set -euo pipefail

SRC="${SLAM_NAV_WS:-/home/lucas/slam_nav_ws}"
DST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/Nav-server"

if [[ ! -d "$SRC/nav_app" ]]; then
  echo "source workspace not found: $SRC" >&2
  exit 1
fi

mkdir -p "$DST"

rsync -a --delete \
  --exclude '__pycache__/' \
  --exclude '*.py[cod]' \
  --exclude '.pytest_cache/' \
  --exclude '*.bak*' \
  --exclude '*.orig' \
  --exclude '*.rej' \
  "$SRC/nav_app/" "$DST/nav_app/"

rsync -a --delete \
  --exclude '__pycache__/' \
  --exclude '*.py[cod]' \
  --exclude '*.bak*' \
  --exclude '*.orig' \
  --exclude '*.rej' \
  --exclude 'demo_dual_recording.py' \
  --exclude 'robot_sbc/setup_marco_libcamera.sh' \
  "$SRC/scripts/" "$DST/scripts/"

rsync -a --delete \
  --exclude '*.bak*' \
  --exclude '*.orig' \
  --exclude '*.rej' \
  --exclude 'camera/*candidate*' \
  --exclude 'camera/*.pre-*' \
  "$SRC/config/" "$DST/config/"

rsync -a --delete \
  "$SRC/launch/" "$DST/launch/"

rsync -a --delete \
  --exclude '*.bak*' \
  --exclude '*.orig' \
  --exclude '*.rej' \
  --exclude '*.jpg' \
  --exclude '*.png' \
  --exclude '*.svg' \
  --exclude 'camera_snapshot_*' \
  --exclude 'robot2_*_preview.*' \
  --exclude 'robot2_grid_waypoints*.json' \
  --exclude 'robot2_center_wall_*' \
  --exclude 'waypoints_review.*' \
  "$SRC/map/" "$DST/map/"

rsync -a --delete \
  --exclude 'plan/' \
  --exclude 'presentation/' \
  --exclude '*.bak*' \
  --exclude '*.orig' \
  --exclude '*.rej' \
  --exclude '*.zip' \
  "$SRC/docs/" "$DST/docs/"

rsync -a --delete \
  "$SRC/tests/" "$DST/tests/"

install -m 0644 "$SRC/pytest.ini" "$DST/pytest.ini"
install -m 0644 "$SRC/.env.example" "$DST/.env.example"
install -m 0644 "$SRC/README.md" "$DST/README.md"

if [[ -d "$SRC/Simulator" ]]; then
  rsync -a --delete \
    --exclude '.git/' \
    --exclude '.agents/' \
    --exclude 'deps_ws/' \
    --exclude 'generated/' \
    --exclude '__pycache__/' \
    --exclude '*.py[cod]' \
    --exclude '.pytest_cache/' \
    --exclude 'worlds/generated_*.world' \
    --exclude 'worlds/_scratch_*.world' \
    --exclude 'models/_scratch_*' \
    --exclude '.env' \
    "$SRC/Simulator/" "$DST/Simulator/"
fi

mkdir -p "$DST/worklog/sessions"
for note in \
  "$SRC/worklog/SESSION_20260708_EKF.md" \
  "$SRC/worklog/sessions/TB3_2_SLOT_APPROACH_INSERT_HANDOFF_2026-07-07.md" \
  "$SRC/worklog/sessions/LIFT_INTEGRATION_2026-07-06.md"
do
  [[ -f "$note" ]] && install -m 0644 "$note" "$DST/worklog/sessions/"
done

echo "synced Nav-server from $SRC -> $DST"
