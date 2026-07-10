#!/usr/bin/env bash
# Local ArUco precision parking test without Main/LMS button.
# This keeps the Nav server path active and sends a local Movement command.
#
# Typical robot1 test:
#   cd /home/lucas/slam_nav_ws
#   MARKER_ID=0 ROBOT_ID=tb3_burger_01 scripts/local_aruco_parking_test.sh
#
# If camera launch is already running on the robot SBC, keep START_CAMERA_LAUNCH=0.
# If running this directly on the robot SBC with camera_ros installed, set START_CAMERA_LAUNCH=1.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROBOTS_CONFIG_PATH="${ROBOTS_CONFIG_PATH:-$ROOT/config/robots.json}"
PYTHON_BIN="${PYTHON_BIN:-python3}"
ROBOT_ID="${ROBOT_ID:-tb3_burger_01}"
MARKER_ID="${MARKER_ID:-0}"
START_DETECTOR="${START_DETECTOR:-1}"
START_CAMERA_LAUNCH="${START_CAMERA_LAUNCH:-0}"
ALIGN_FINAL="${ALIGN_FINAL:-hold}"
BASE_URL="${BASE_URL:-}"
COMMAND_ID="${COMMAND_ID:-local-aruco-align-$(date +%Y%m%d-%H%M%S)}"
ARUCO_WAIT_SEC="${ARUCO_WAIT_SEC:-20}"
COMMAND_TIMEOUT_SEC="${COMMAND_TIMEOUT_SEC:-45}"
TARGET_MARKER_WIDTH_PX="${TARGET_MARKER_WIDTH_PX:-65}"
DOCK_LINEAR_SPEED="${DOCK_LINEAR_SPEED:-0.018}"
DOCK_MIN_LINEAR_SPEED="${DOCK_MIN_LINEAR_SPEED:-0.006}"
DOCK_ANGULAR_GAIN="${DOCK_ANGULAR_GAIN:-0.45}"
DOCK_MAX_ANGULAR_SPEED="${DOCK_MAX_ANGULAR_SPEED:-0.16}"
CENTER_TOLERANCE_NORM="${CENTER_TOLERANCE_NORM:-0.12}"
COARSE_CENTER_TOLERANCE_NORM="${COARSE_CENTER_TOLERANCE_NORM:-0.30}"
DOCKING_TIMEOUT_SEC="${DOCKING_TIMEOUT_SEC:-35}"
DRY_RUN="${DRY_RUN:-false}"

robot_field() {
  local field="$1"
  "$PYTHON_BIN" - "$ROBOTS_CONFIG_PATH" "$ROBOT_ID" "$field" <<'PYROBOT'
import json, sys
path, robot_id, field = sys.argv[1:4]
data = json.load(open(path, encoding='utf-8'))
for robot in data.get('robots', []):
    if robot.get('robot_id') == robot_id:
        value = robot.get(field)
        if value is None:
            raise SystemExit(2)
        print(value)
        raise SystemExit(0)
raise SystemExit(1)
PYROBOT
}

BRIDGE_ROBOT_ID="${BRIDGE_ROBOT_ID:-$(robot_field bridge_robot_id)}"
ROS_DOMAIN_ID="${ROS_DOMAIN_ID_OVERRIDE:-$(robot_field ros_domain_id)}"
ARUCO_DETECTION_TOPIC="${ARUCO_DETECTION_TOPIC:-$(robot_field aruco_detection_topic)}"

if [[ -z "$BASE_URL" ]]; then
  if [[ "$BRIDGE_ROBOT_ID" == "tb3_1" ]]; then
    BASE_URL="http://127.0.0.1:8001"
  elif [[ "$BRIDGE_ROBOT_ID" == "tb3_2" ]]; then
    BASE_URL="http://127.0.0.1:8002"
  else
    echo "[local_aruco_test] cannot derive BASE_URL for bridge robot: $BRIDGE_ROBOT_ID" >&2
    exit 2
  fi
fi

pids=()
cleanup() {
  if ((${#pids[@]} > 0)); then
    echo
    echo "[local_aruco_test] stopping detector child processes..."
    kill "${pids[@]}" 2>/dev/null || true
    wait 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

http_json() {
  local method="$1"
  local url="$2"
  local body="${3:-}"
  if [[ -n "$body" ]]; then
    curl -fsS -X "$method" "$url" -H 'Content-Type: application/json' -d "$body"
  else
    curl -fsS -X "$method" "$url"
  fi
}

json_field() {
  "$PYTHON_BIN" - "$1" "$2" <<'PYJSON'
import json, sys
data = json.loads(sys.argv[1])
path = sys.argv[2].split('.')
value = data
for part in path:
    if isinstance(value, dict):
        value = value.get(part)
    else:
        value = None
        break
if isinstance(value, (dict, list)):
    print(json.dumps(value, ensure_ascii=False))
elif value is None:
    print("")
else:
    print(value)
PYJSON
}

json_len() {
  "$PYTHON_BIN" - "$1" "$2" <<'PYJSON'
import json, sys
data = json.loads(sys.argv[1])
path = sys.argv[2].split('.')
value = data
for part in path:
    if isinstance(value, dict):
        value = value.get(part)
    else:
        value = None
        break
print(len(value) if isinstance(value, list) else 0)
PYJSON
}

echo "[local_aruco_test] robot=$ROBOT_ID bridge=$BRIDGE_ROBOT_ID domain=$ROS_DOMAIN_ID base=$BASE_URL marker=$MARKER_ID"
echo "[local_aruco_test] detector topic=$ARUCO_DETECTION_TOPIC"

echo "[local_aruco_test] checking Nav server health..."
health="$(http_json GET "$BASE_URL/movement-api/v1/health")"
echo "$health" | "$PYTHON_BIN" -m json.tool
cmd_subs="$(json_field "$health" cmd_vel_subscribers)"
accepting="$(json_field "$health" command_accepting)"
if [[ "$DRY_RUN" != "true" && "$cmd_subs" == "0" ]]; then
  echo "[local_aruco_test] FAIL: /cmd_vel subscriber is 0. TurtleBot3 bringup is not connected." >&2
  exit 3
fi
if [[ "$DRY_RUN" != "true" && "$accepting" != "True" && "$accepting" != "true" ]]; then
  echo "[local_aruco_test] FAIL: command_accepting is not true." >&2
  exit 4
fi

if [[ "$START_DETECTOR" != "0" ]]; then
  echo "[local_aruco_test] starting ArUco detector. START_CAMERA_LAUNCH=$START_CAMERA_LAUNCH"
  START_CAMERA_LAUNCH="$START_CAMERA_LAUNCH" ROBOT_ID="$ROBOT_ID" "$SCRIPT_DIR/run_pi_camera_aruco.sh" &
  pids+=("$!")
  sleep 2
fi

echo "[local_aruco_test] waiting for marker $MARKER_ID detection for up to ${ARUCO_WAIT_SEC}s..."
deadline=$((SECONDS + ARUCO_WAIT_SEC))
latest=""
while (( SECONDS < deadline )); do
  latest="$(curl -fsS "$BASE_URL/movement-api/v1/aruco/latest?marker_id=$MARKER_ID" || true)"
  detection_count="$(json_len "${latest:-{}}" detections 2>/dev/null || echo 0)"
  if (( detection_count > 0 )); then
    echo "$latest" | "$PYTHON_BIN" -m json.tool
    break
  fi
  sleep 1
done
if (( $(json_len "${latest:-{}}" detections 2>/dev/null || echo 0) == 0 )); then
  echo "[local_aruco_test] FAIL: marker $MARKER_ID was not detected. Show the marker to the Pi Camera and retry." >&2
  exit 5
fi

payload="$($PYTHON_BIN - <<PYREQ
import json
print(json.dumps({
    "command_id": "$COMMAND_ID",
    "task_id": None,
    "robot_name": "$BRIDGE_ROBOT_ID",
    "steps": [{
        "action": "aruco_align",
        "payload": {
            "aruco_marker_id": int("$MARKER_ID"),
            "final": "$ALIGN_FINAL",
            "terminal_state": "DONE",
            "dry_run": "$DRY_RUN".lower() == "true",
            "target_marker_width_px": float("$TARGET_MARKER_WIDTH_PX"),
            "dock_linear_speed": float("$DOCK_LINEAR_SPEED"),
            "dock_min_linear_speed": float("$DOCK_MIN_LINEAR_SPEED"),
            "dock_angular_gain": float("$DOCK_ANGULAR_GAIN"),
            "dock_max_angular_speed": float("$DOCK_MAX_ANGULAR_SPEED"),
            "center_tolerance_norm": float("$CENTER_TOLERANCE_NORM"),
            "coarse_center_tolerance_norm": float("$COARSE_CENTER_TOLERANCE_NORM"),
            "docking_timeout_sec": float("$DOCKING_TIMEOUT_SEC")
        }
    }]
}, ensure_ascii=False))
PYREQ
)"

echo "[local_aruco_test] sending local aruco_align command: $COMMAND_ID"
http_json POST "$BASE_URL/movement-api/v1/commands" "$payload" | "$PYTHON_BIN" -m json.tool

echo "[local_aruco_test] waiting for command result..."
deadline=$((SECONDS + COMMAND_TIMEOUT_SEC))
while (( SECONDS < deadline )); do
  result="$(http_json GET "$BASE_URL/movement-api/v1/commands/$COMMAND_ID")"
  state="$(json_field "$result" state)"
  echo "[local_aruco_test] state=$state"
  if [[ "$state" == "DONE" || "$state" == "FAILED" || "$state" == "ABORTED" ]]; then
    echo "$result" | "$PYTHON_BIN" -m json.tool
    [[ "$state" == "DONE" ]]
    exit $?
  fi
  sleep 1
done

echo "[local_aruco_test] FAIL: command timeout" >&2
exit 6
