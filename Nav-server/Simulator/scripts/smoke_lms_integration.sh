#!/usr/bin/env bash
set -euo pipefail

MAIN_URL="${MAIN_URL:-http://localhost:8088/api/v1}"
ROBOT_ID="${ROBOT_ID:-tb3_1}"
MAP_ID="${MAP_ID:-robot1_map}"
GOAL_X="${GOAL_X:-0.765}"
GOAL_Y="${GOAL_Y:-0.95}"
GOAL_YAW="${GOAL_YAW:-1.57}"
SEND_COMMAND="${SEND_COMMAND:-0}"
COMMAND_ID="${COMMAND_ID:-lms-gazebo-smoke-$(date +%s)}"

request_json() {
  local method="$1"
  local url="$2"
  local payload="${3:-}"
  if [[ -n "$payload" ]]; then
    curl -fsS -X "$method" "$url" -H "Content-Type: application/json" -d "$payload"
  else
    curl -fsS -X "$method" "$url"
  fi
}

print_json() {
  if command -v jq >/dev/null 2>&1; then
    jq .
  else
    python3 -m json.tool
  fi
}

echo "== Main robots =="
request_json GET "$MAIN_URL/robots" | print_json

echo "== Main movement map-state =="
request_json GET "$MAIN_URL/movement/map-state" | print_json

echo "== Main robot nav-state: $ROBOT_ID =="
request_json GET "$MAIN_URL/robots/$ROBOT_ID/nav-state" | print_json

echo "== Main robot command dry-run preview =="
dry_run_payload="$(python3 - "$ROBOT_ID" "$MAP_ID" "$GOAL_X" "$GOAL_Y" "$GOAL_YAW" "$COMMAND_ID-dry-run" <<'PY'
import json
import sys
robot_id, map_id, x, y, yaw, command_id = sys.argv[1:]
print(json.dumps({
    "robot_id": robot_id,
    "kind": "move_to_point",
    "command_id": command_id,
    "dry_run": True,
    "params": {"map_id": map_id, "x": float(x), "y": float(y), "yaw": float(yaw)},
}))
PY
)"
request_json POST "$MAIN_URL/robot-commands" "$dry_run_payload" | print_json

if [[ "$SEND_COMMAND" == "1" || "$SEND_COMMAND" == "true" ]]; then
  echo "== Main robot command execution =="
  command_payload="$(python3 - "$ROBOT_ID" "$MAP_ID" "$GOAL_X" "$GOAL_Y" "$GOAL_YAW" "$COMMAND_ID" <<'PY'
import json
import sys
robot_id, map_id, x, y, yaw, command_id = sys.argv[1:]
print(json.dumps({
    "robot_id": robot_id,
    "kind": "move_to_point",
    "command_id": command_id,
    "dry_run": False,
    "params": {"map_id": map_id, "x": float(x), "y": float(y), "yaw": float(yaw)},
}))
PY
)"
  request_json POST "$MAIN_URL/robot-commands" "$command_payload" | print_json

  echo "== Main robot command status =="
  request_json GET "$MAIN_URL/robot-commands/$COMMAND_ID?robot_id=$ROBOT_ID" | print_json
else
  echo "Skipping movement command. Set SEND_COMMAND=1 to dispatch through Main to Movement."
fi