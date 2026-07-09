#!/usr/bin/env bash
#
# Validate the main-server integration contract without moving robots.
#
# This starts the local mock main server, posts representative webhook events,
# reads them back, and checks required fields. It does not call /mission/start.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MOCK_HOST="${MOCK_HOST:-127.0.0.1}"
MOCK_PORT="${MOCK_PORT:-19000}"
MOCK_URL="http://${MOCK_HOST}:${MOCK_PORT}"
MOCK_PID=""

cleanup() {
  if [[ -n "$MOCK_PID" ]]; then
    kill "$MOCK_PID" 2>/dev/null || true
    wait "$MOCK_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

python3 "$SCRIPT_DIR/mock_main_server.py" --host "$MOCK_HOST" --port "$MOCK_PORT" >/tmp/slam_nav_mock_main_server.log 2>&1 &
MOCK_PID="$!"

python3 - "$ROOT" "$MOCK_URL" <<'PYCONTRACT'
import json
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

root = Path(sys.argv[1])
mock_url = sys.argv[2]

robots_config = json.loads((root / "config" / "robots.json").read_text(encoding="utf-8"))
routes_config = json.loads((root / "config" / "main_server_routes.json").read_text(encoding="utf-8"))
robots = {robot["robot_id"]: robot for robot in robots_config["robots"]}
routes = {robot["robot_id"]: robot for robot in routes_config["robots"]}

required_route_ids = {"tb3_burger_01", "tb3_burger_02"}
if set(routes) != required_route_ids:
    raise SystemExit(f"[smoke_main_contract] route ids mismatch: {sorted(routes)}")

for robot_id, route in routes.items():
    robot = robots[robot_id]
    for key in ("ros_domain_id", "bridge_robot_id", "center_domain_id"):
        if route[key] != robot[key]:
            raise SystemExit(f"[smoke_main_contract] {robot_id} {key} mismatch: route={route[key]} robot={robot[key]}")

for _ in range(30):
    try:
        with urllib.request.urlopen(f"{mock_url}/health", timeout=1) as response:
            if response.status == 200:
                break
    except Exception:
        time.sleep(0.1)
else:
    raise SystemExit("[smoke_main_contract] mock server did not start")

required_payload_fields = {
    "event", "robot_id", "bridge_robot_id", "ros_domain_id", "center_domain_id",
    "namespace", "teleop_command_topic", "camera_topic", "aruco_detection_topic", "mission_id",
    "mission_type", "mission_status", "item_name", "count", "navigator_status",
    "battery", "is_emergency", "last_error", "timestamp",
}

def post_event(robot, event, status):
    payload = {
        "event": event,
        "robot_id": robot["robot_id"],
        "bridge_robot_id": robot["bridge_robot_id"],
        "ros_domain_id": robot["ros_domain_id"],
        "center_domain_id": robot["center_domain_id"],
        "namespace": robot["namespace"],
        "teleop_command_topic": robot["teleop_command_topic"],
        "camera_topic": robot["camera_topic"],
        "aruco_detection_topic": robot["aruco_detection_topic"],
        "mission_id": f"contract-{robot['bridge_robot_id']}",
        "mission_type": "inbound",
        "mission_status": status,
        "item_name": "contract_box",
        "count": 1,
        "navigator_status": "IDLE",
        "battery": 100.0,
        "is_emergency": False,
        "last_error": None,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    missing = required_payload_fields - set(payload)
    if missing:
        raise SystemExit(f"[smoke_main_contract] missing payload fields before post: {sorted(missing)}")
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{mock_url}/webhook/robot-status",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=2) as response:
        if response.status != 200:
            raise SystemExit(f"[smoke_main_contract] webhook post failed: {response.status}")

for robot_id in ("tb3_burger_01", "tb3_burger_02"):
    post_event(robots[robot_id], "accepted", "ACCEPTED")
    post_event(robots[robot_id], "running", "RUNNING")
    post_event(robots[robot_id], "succeeded", "SUCCEEDED")

with urllib.request.urlopen(f"{mock_url}/events", timeout=2) as response:
    data = json.loads(response.read().decode("utf-8"))

events = data["events"]
if len(events) != 6:
    raise SystemExit(f"[smoke_main_contract] expected 6 events, got {len(events)}")

for event in events:
    missing = required_payload_fields - set(event)
    if missing:
        raise SystemExit(f"[smoke_main_contract] received event missing fields: {sorted(missing)}")
    if event["robot_id"] not in robots:
        raise SystemExit(f"[smoke_main_contract] unknown robot in event: {event['robot_id']}")

print("[smoke_main_contract] PASS route config matches robots.json")
print("[smoke_main_contract] PASS mock webhook received 6 lifecycle events")
PYCONTRACT
