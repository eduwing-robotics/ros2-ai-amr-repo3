#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8001}"
TIMEOUT_SEC="${TIMEOUT_SEC:-60}"
SEND_GOAL="${SEND_GOAL:-0}"
GOAL_X="${GOAL_X:-0.765}"
GOAL_Y="${GOAL_Y:-0.95}"
GOAL_YAW="${GOAL_YAW:-1.57}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "[smoke] waiting for Nav API at $BASE_URL"
deadline=$((SECONDS + TIMEOUT_SEC))
until curl -fsS "$BASE_URL/movement-api/v1/robots" >/dev/null; do
  if (( SECONDS >= deadline )); then
    echo "[smoke] Nav API did not become ready within ${TIMEOUT_SEC}s" >&2
    exit 1
  fi
  sleep 1
done

"$SCRIPT_DIR/check_ros_topics.sh"
"$SCRIPT_DIR/check_api.sh"

if [[ "$SEND_GOAL" == "1" || "$SEND_GOAL" == "true" ]]; then
  echo "[smoke] sending nav2_pose goal x=$GOAL_X y=$GOAL_Y yaw=$GOAL_YAW"
  "$SCRIPT_DIR/send_nav2_pose.sh" "$GOAL_X" "$GOAL_Y" "$GOAL_YAW"
else
  echo "[smoke] skipping goal send. Set SEND_GOAL=1 to test movement."
fi