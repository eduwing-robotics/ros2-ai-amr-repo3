#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8001}"
ROBOT_NAME="${ROBOT_NAME:-tb3_1}"
X="${1:-0.5}"
Y="${2:-0.0}"
YAW="${3:-0.0}"
TASK_ID="$(date +%s%N)"
COMMAND_ID="gazebo-nav2-pose-$TASK_ID"

curl -fsS -X POST "$BASE_URL/movement-api/v1/commands" \
  -H "Content-Type: application/json" \
  -d @- <<JSON | jq .
{
  "command_id": "$COMMAND_ID",
  "task_id": $TASK_ID,
  "robot_name": "$ROBOT_NAME",
  "callback_url": null,
  "steps": [
    {
      "action": "nav2_pose",
      "command": null,
      "duration": null,
      "payload": {
        "frame_id": "map",
        "goal": {
          "x": $X,
          "y": $Y,
          "yaw": $YAW,
          "label": "gazebo_test_goal"
        },
        "timeout_sec": 60
      }
    }
  ]
}
JSON

echo "command_id=$COMMAND_ID"
echo "status:"
for _ in $(seq 1 180); do
  STATUS_JSON="$(curl -fsS "$BASE_URL/movement-api/v1/commands/$COMMAND_ID")"
  echo "$STATUS_JSON" | jq .
  STATE="$(echo "$STATUS_JSON" | jq -r '.state')"
  case "$STATE" in
    SUCCEEDED|DONE)
      exit 0
      ;;
    FAILED|CANCELED|CANCELLED|REJECTED)
      exit 1
      ;;
  esac
  sleep 1
done

echo "Timed out waiting for command $COMMAND_ID" >&2
exit 1
