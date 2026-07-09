#!/usr/bin/env bash
#
# End-to-end dry-run smoke test for the latest Movement API contract.
#
# Flow:
#   mock main server
#   DRY_RUN_MISSION=1 Nav/Movement API servers
#   POST /movement-api/v1/commands on both robot API ports
#   verify Main callbacks: /movement/results and /movement/robots/{robot}/status

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
MOCK_HOST="${MOCK_HOST:-127.0.0.1}"
MOCK_PORT="${MOCK_PORT:-19001}"
MOCK_URL="http://${MOCK_HOST}:${MOCK_PORT}"
MAIN_API_BASE="${MAIN_API_BASE:-$MOCK_URL/api/v1}"
TB3_1_URL="${TB3_1_URL:-http://127.0.0.1:8001}"
TB3_2_URL="${TB3_2_URL:-http://127.0.0.1:8002}"
MOCK_PID=""
NAV_PID=""

cleanup() {
  if [[ -n "$NAV_PID" ]]; then
    kill "$NAV_PID" 2>/dev/null || true
    wait "$NAV_PID" 2>/dev/null || true
  fi
  if [[ -n "$MOCK_PID" ]]; then
    kill "$MOCK_PID" 2>/dev/null || true
    wait "$MOCK_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

python3 "$SCRIPT_DIR/mock_main_server.py" --host "$MOCK_HOST" --port "$MOCK_PORT" >/tmp/slam_nav_movement_mock_main.log 2>&1 &
MOCK_PID="$!"

DRY_RUN_MISSION=1 MAIN_API_BASE="$MAIN_API_BASE" "$SCRIPT_DIR/run_nav_servers.sh" >/tmp/slam_nav_movement_api.log 2>&1 &
NAV_PID="$!"

python3 - "$MOCK_URL" "$TB3_1_URL" "$TB3_2_URL" <<'PYSMOKE'
import json
import sys
import time
import urllib.error
import urllib.request

mock_url, tb3_1_url, tb3_2_url = sys.argv[1], sys.argv[2], sys.argv[3]


def get_json(url, timeout=2):
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def request_json(method, url, payload=None, expected=200, timeout=4):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            status = response.status
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        status = exc.code
        body = exc.read().decode("utf-8")
    if status != expected:
        raise SystemExit(f"[smoke_movement_api] FAIL {method} {url}: expected {expected}, got {status}, body={body}")
    return json.loads(body) if body else {}


def wait_url(url, label):
    for _ in range(60):
        try:
            return get_json(url, timeout=1)
        except Exception:
            time.sleep(0.2)
    raise SystemExit(f"[smoke_movement_api] {label} did not start: {url}")


def wait_for_command(url, command_id, expected_states, timeout_sec=8.0):
    deadline = time.time() + timeout_sec
    expected_states = set(expected_states)
    while time.time() < deadline:
        command = get_json(f"{url}/robot-commands/{command_id}", timeout=1)
        if command.get("state") in expected_states:
            return command
        time.sleep(0.2)
    raise SystemExit(f"[smoke_movement_api] command {command_id} did not reach {sorted(expected_states)}: {command}")

wait_url(f"{mock_url}/health", "mock main server")
wait_url(f"{tb3_1_url}/movement-api/v1/health", "tb3_1 movement api")
wait_url(f"{tb3_2_url}/movement-api/v1/health", "tb3_2 movement api")

endpoints_1 = request_json("GET", f"{tb3_1_url}/movement-api/v1/endpoints")
endpoints_2 = request_json("GET", f"{tb3_2_url}/movement-api/v1/endpoints")
expected_robot2_ip = "192.168.30.102"
if endpoints_1.get("robot_fixed_ips", {}).get("tb3_2") != expected_robot2_ip:
    raise SystemExit(f"[smoke_movement_api] endpoint contract missing tb3_2 fixed IP: {endpoints_1}")
if endpoints_2.get("robot_fixed_ip") != expected_robot2_ip:
    raise SystemExit(f"[smoke_movement_api] tb3_2 endpoint contract wrong robot_fixed_ip: {endpoints_2}")

robots_1 = request_json("GET", f"{tb3_1_url}/movement-api/v1/robots")
robots_2 = request_json("GET", f"{tb3_2_url}/movement-api/v1/robots")
if robots_1["robots"][0]["robot_name"] != "tb3_1":
    raise SystemExit("[smoke_movement_api] tb3_1 robot listing mismatch")
if robots_2["robots"][0]["robot_name"] != "tb3_2":
    raise SystemExit("[smoke_movement_api] tb3_2 robot listing mismatch")

waypoint_catalog = request_json("GET", f"{tb3_1_url}/movement-api/v1/waypoints")
waypoint_ids = {item.get("waypoint_id") for item in waypoint_catalog.get("waypoints", [])}
if "warehouse_b_approach" not in waypoint_ids:
    raise SystemExit(f"[smoke_movement_api] waypoint catalog missing warehouse_b_approach: {waypoint_catalog}")

inventory = request_json("GET", f"{tb3_1_url}/movement-api/v1/inventory")
inventory_items = inventory.get("items", [])
if not inventory_items:
    raise SystemExit(f"[smoke_movement_api] inventory is empty: {inventory}")
expected_items = [item.get("item_code") for item in inventory_items if item.get("item_code")]
if not expected_items:
    raise SystemExit(f"[smoke_movement_api] inventory missing item_code values: {inventory}")

manual_translate = request_json("POST", f"{tb3_2_url}/movement-api/v1/manual/translate", {
    "robot_name": "tb3_2",
    "direction": "forward",
    "duration_sec": 0.1,
    "linear_x": 0.1,
})
if not manual_translate.get("accepted") or manual_translate.get("linear_x") != 0.1:
    raise SystemExit(f"[smoke_movement_api] manual translate failed: {manual_translate}")

manual_backward = request_json("POST", f"{tb3_2_url}/movement-api/v1/manual/translate", {
    "robot_name": "tb3_2",
    "direction": "backward",
    "duration_sec": 0.1,
    "linear_x": 0.1,
})
if not manual_backward.get("accepted") or manual_backward.get("linear_x") != -0.1:
    raise SystemExit(f"[smoke_movement_api] manual backward failed: {manual_backward}")

manual_start = request_json("POST", f"{tb3_2_url}/movement-api/v1/manual/start", {
    "robot_name": "tb3_2",
    "command": "forward",
    "linear_x": 0.1,
    "timeout_sec": 0.2,
})
if not manual_start.get("accepted") or manual_start.get("command") != "forward":
    raise SystemExit(f"[smoke_movement_api] manual start failed: {manual_start}")

manual_start_stop = request_json("POST", f"{tb3_2_url}/movement-api/v1/manual/start", {
    "robot_name": "tb3_2",
    "command": "stop",
})
if not manual_start_stop.get("accepted") or not manual_start_stop.get("stopped"):
    raise SystemExit(f"[smoke_movement_api] manual start stop failed: {manual_start_stop}")

manual_stop = request_json("POST", f"{tb3_2_url}/movement-api/v1/manual/stop", {"robot_name": "tb3_2"})
if not manual_stop.get("accepted") or not manual_stop.get("stopped"):
    raise SystemExit(f"[smoke_movement_api] manual stop failed: {manual_stop}")

robot_move = request_json("POST", f"{tb3_1_url}/robot-commands", {
    "command_id": "robot-command-move-tb3-1",
    "task_id": 901,
    "robot_id": "tb3_1",
    "kind": "move_to_point",
    "dry_run": True,
    "params": {"x": 0.54, "y": 1.236, "yaw": 0.0, "waypoint_id": "warehouse_a_approach", "traffic_segments": []},
})
if not robot_move.get("accepted") or robot_move.get("kind") != "move_to_point":
    raise SystemExit(f"[smoke_movement_api] robot move command not accepted: {robot_move}")
robot_move_final = wait_for_command(tb3_1_url, "robot-command-move-tb3-1", {"ARRIVED"})
if robot_move_final.get("state") != "ARRIVED":
    raise SystemExit(f"[smoke_movement_api] robot move command wrong terminal state: {robot_move_final}")

robot_waypoint_move = request_json("POST", f"{tb3_1_url}/robot-commands", {
    "command_id": "robot-command-waypoint-only-tb3-1",
    "task_id": 903,
    "robot_id": "tb3_1",
    "kind": "move_to_point",
    "dry_run": True,
    "params": {"waypoint_id": "warehouse_b_approach", "traffic_segments": []},
})
if not robot_waypoint_move.get("accepted") or robot_waypoint_move.get("kind") != "move_to_point":
    raise SystemExit(f"[smoke_movement_api] waypoint-only move command not accepted: {robot_waypoint_move}")
robot_waypoint_final = wait_for_command(tb3_1_url, "robot-command-waypoint-only-tb3-1", {"ARRIVED"})
if robot_waypoint_final.get("state") != "ARRIVED" or robot_waypoint_final.get("params", {}).get("waypoint_id") != "warehouse_b_approach":
    raise SystemExit(f"[smoke_movement_api] waypoint-only move command wrong final state: {robot_waypoint_final}")

robot_lock_move = request_json("POST", f"{tb3_1_url}/robot-commands", {
    "command_id": "robot-command-traffic-lock-move-tb3-1",
    "task_id": 907,
    "robot_id": "tb3_1",
    "kind": "move_to_point",
    "dry_run": True,
    "params": {"waypoint_id": "warehouse_a_approach"},
})
if not robot_lock_move.get("accepted"):
    raise SystemExit(f"[smoke_movement_api] traffic lock move not accepted: {robot_lock_move}")
robot_lock_arrived = wait_for_command(tb3_1_url, "robot-command-traffic-lock-move-tb3-1", {"ARRIVED"})
if "warehouse_aisle" not in robot_lock_arrived.get("traffic_segments", []):
    raise SystemExit(f"[smoke_movement_api] atomic move did not lock warehouse_aisle: {robot_lock_arrived}")

blocked_atomic_move = request_json("POST", f"{tb3_2_url}/robot-commands", {
    "command_id": "robot-command-blocked-atomic-move-tb3-2",
    "task_id": 908,
    "robot_id": "tb3_2",
    "kind": "move_to_point",
    "dry_run": True,
    "params": {"waypoint_id": "warehouse_b_approach"},
}, expected=409)
if blocked_atomic_move.get("detail", {}).get("traffic_state") != "WAITING_TRAFFIC":
    raise SystemExit(f"[smoke_movement_api] atomic traffic conflict did not report WAITING_TRAFFIC: {blocked_atomic_move}")

robot_lock_dock = request_json("POST", f"{tb3_1_url}/robot-commands", {
    "command_id": "robot-command-traffic-lock-dock-tb3-1",
    "task_id": 907,
    "robot_id": "tb3_1",
    "kind": "dock_transfer",
    "dry_run": True,
    "params": {"aruco_marker_id": 101, "action": "unload", "level": 1},
})
if not robot_lock_dock.get("accepted"):
    raise SystemExit(f"[smoke_movement_api] traffic lock dock handoff not accepted: {robot_lock_dock}")
robot_lock_dock_final = wait_for_command(tb3_1_url, "robot-command-traffic-lock-dock-tb3-1", {"DONE"})
if robot_lock_dock_final.get("state") != "DONE":
    raise SystemExit(f"[smoke_movement_api] traffic lock dock handoff did not finish: {robot_lock_dock_final}")
traffic_locks_after_atomic = request_json("GET", f"{tb3_1_url}/traffic/locks")
if "warehouse_aisle" in traffic_locks_after_atomic.get("locks", {}):
    raise SystemExit(f"[smoke_movement_api] atomic traffic lock was not released after dock: {traffic_locks_after_atomic}")

dock_without_gate = request_json("POST", f"{tb3_2_url}/robot-commands", {
    "command_id": "robot-command-dock-no-gate-tb3-2",
    "task_id": 902,
    "robot_id": "tb3_2",
    "kind": "dock_transfer",
    "dry_run": True,
    "params": {"aruco_marker_id": 101, "action": "unload", "level": 1},
}, expected=409)
if dock_without_gate.get("detail", {}).get("required_previous_state") != "ARRIVED":
    raise SystemExit(f"[smoke_movement_api] dock_transfer without ARRIVED gate should be rejected: {dock_without_gate}")

robot_dock_gate_move = request_json("POST", f"{tb3_2_url}/robot-commands", {
    "command_id": "robot-command-dock-gate-move-tb3-2",
    "task_id": 902,
    "robot_id": "tb3_2",
    "kind": "move_to_point",
    "dry_run": True,
    "params": {"waypoint_id": "warehouse_a_approach"},
})
if not robot_dock_gate_move.get("accepted"):
    raise SystemExit(f"[smoke_movement_api] dock gate move not accepted: {robot_dock_gate_move}")
robot_dock_gate_arrived = wait_for_command(tb3_2_url, "robot-command-dock-gate-move-tb3-2", {"ARRIVED"})
if robot_dock_gate_arrived.get("state") != "ARRIVED" or robot_dock_gate_arrived.get("robot_at") != "approach":
    raise SystemExit(f"[smoke_movement_api] dock gate move did not ARRIVE at approach: {robot_dock_gate_arrived}")

robot_dock = request_json("POST", f"{tb3_2_url}/robot-commands", {
    "command_id": "robot-command-dock-tb3-2",
    "task_id": 902,
    "robot_id": "tb3_2",
    "kind": "dock_transfer",
    "dry_run": True,
    "params": {"aruco_marker_id": 101, "action": "unload", "level": 1},
})
if not robot_dock.get("accepted") or robot_dock.get("kind") != "dock_transfer":
    raise SystemExit(f"[smoke_movement_api] robot dock command not accepted: {robot_dock}")
robot_dock_final = wait_for_command(tb3_2_url, "robot-command-dock-tb3-2", {"DONE"})
if robot_dock_final.get("state") != "DONE":
    raise SystemExit(f"[smoke_movement_api] robot dock command wrong terminal state: {robot_dock_final}")

robot_align_gate_move = request_json("POST", f"{tb3_2_url}/robot-commands", {
    "command_id": "robot-command-align-gate-move-tb3-2",
    "task_id": 904,
    "robot_id": "tb3_2",
    "kind": "move_to_point",
    "dry_run": True,
    "params": {"waypoint_id": "warehouse_b_approach"},
})
if not robot_align_gate_move.get("accepted"):
    raise SystemExit(f"[smoke_movement_api] aruco_align gate move not accepted: {robot_align_gate_move}")
robot_align_gate_arrived = wait_for_command(tb3_2_url, "robot-command-align-gate-move-tb3-2", {"ARRIVED"})
if robot_align_gate_arrived.get("state") != "ARRIVED":
    raise SystemExit(f"[smoke_movement_api] aruco_align gate move did not ARRIVE: {robot_align_gate_arrived}")
robot_align = request_json("POST", f"{tb3_2_url}/robot-commands", {
    "command_id": "robot-command-align-tb3-2",
    "task_id": 904,
    "robot_id": "tb3_2",
    "kind": "aruco_align",
    "dry_run": True,
    "params": {"aruco_marker_id": 21, "final": "hold", "tolerance": {"xy_m": 0.02, "yaw_deg": 2}},
})
if not robot_align.get("accepted") or robot_align.get("kind") != "aruco_align":
    raise SystemExit(f"[smoke_movement_api] robot aruco_align command not accepted: {robot_align}")
robot_align_final = wait_for_command(tb3_2_url, "robot-command-align-tb3-2", {"DONE"})
if robot_align_final.get("state") != "DONE":
    raise SystemExit(f"[smoke_movement_api] robot aruco_align command wrong terminal state: {robot_align_final}")

timeout_gate = request_json("POST", f"{tb3_2_url}/robot-commands", {
    "command_id": "robot-command-gate-timeout-tb3-2",
    "task_id": 905,
    "robot_id": "tb3_2",
    "kind": "move_to_point",
    "dry_run": True,
    "params": {"waypoint_id": "vehicle_1_approach", "gate_timeout_sec": 0.5},
    "callback_url": f"{mock_url}/api/v1/movement/command-events",
})
if not timeout_gate.get("accepted"):
    raise SystemExit(f"[smoke_movement_api] timeout gate move not accepted: {timeout_gate}")
timeout_final = wait_for_command(tb3_2_url, "robot-command-gate-timeout-tb3-2", {"ABORTED"}, timeout_sec=4.0)
if timeout_final.get("reason") != "timeout" or timeout_final.get("robot_at") != "approach" or timeout_final.get("resumable") is not True:
    raise SystemExit(f"[smoke_movement_api] gate timeout did not report ABORTED timeout/resumable: {timeout_final}")

failing_align = request_json("POST", f"{tb3_1_url}/movement-api/v1/commands", {
    "command_id": "contract-failing-align-stage",
    "task_id": 906,
    "robot_name": "tb3_1",
    "steps": [{"action": "aruco_align", "payload": {"dry_run": True}}],
})
if not failing_align.get("accepted"):
    raise SystemExit(f"[smoke_movement_api] failing align command not accepted: {failing_align}")
failing_align_final = wait_for_command(tb3_1_url, "contract-failing-align-stage", {"FAILED"})
if failing_align_final.get("state") != "FAILED" or failing_align_final.get("stage") != "aruco":
    raise SystemExit(f"[smoke_movement_api] failing align did not report FAILED with stage: {failing_align_final}")

sim_state = request_json("GET", f"{tb3_1_url}/movement-api/v1/simulation-state")
if "simulation_mode" not in sim_state:
    raise SystemExit(f"[smoke_movement_api] simulation-state missing simulation_mode: {sim_state}")

expected_items = [item.get("item_code") for item in inventory_items if item.get("item_code")]
if not expected_items:
    raise SystemExit(f"[smoke_movement_api] inventory items missing item_code values: {inventory}")
expected_operation_sequence = [
    "go_to_pickup_approach",
    "pickup_dock_lift_up_reverse",
    "go_to_dropoff_approach",
    "dropoff_dock_lift_down_reverse",
    "return_to_standby",
    "wait",
]

def assert_full_transfer_preview(preview, route_type, item_code):
    if preview.get("route_type") != route_type or preview.get("item", {}).get("item_code") != item_code:
        raise SystemExit(f"[smoke_movement_api] route preview mismatch: {preview}")
    actions = [step.get("action") for step in preview.get("steps", [])]
    if actions.count("nav2_waypoints") < 3 or actions.count("dock_transfer") != 2:
        raise SystemExit(f"[smoke_movement_api] route preview is not full nav/dock/nav/dock/return sequence: {preview}")
    if preview.get("operation_sequence") != expected_operation_sequence:
        raise SystemExit(f"[smoke_movement_api] wrong operation sequence: {preview}")
    dock_steps = [step for step in preview.get("steps", []) if step.get("action") == "dock_transfer"]
    dock_actions = [step.get("payload", {}).get("action") for step in dock_steps]
    if dock_actions != ["load", "unload"]:
        raise SystemExit(f"[smoke_movement_api] route dock actions must be load then unload: {preview}")
    pickup = preview.get("pickup_transfer") or {}
    dropoff = preview.get("dropoff_transfer") or {}
    if pickup.get("action") != "load" or dropoff.get("action") != "unload":
        raise SystemExit(f"[smoke_movement_api] pickup/dropoff transfer mismatch: {preview}")
    if route_type == "inbound" and preview.get("source_section_id") != "inbound_slot_1":
        raise SystemExit(f"[smoke_movement_api] inbound source section mismatch: {preview}")
    if route_type == "outbound" and preview.get("target_section_id") != "outbound_slot_1":
        raise SystemExit(f"[smoke_movement_api] outbound target section mismatch: {preview}")
    if preview.get("return_waypoint") != "vehicle_1_approach":
        raise SystemExit(f"[smoke_movement_api] route return waypoint mismatch: {preview}")
    if preview.get("traffic_policy", {}).get("rule") != "right_hand_traffic":
        raise SystemExit(f"[smoke_movement_api] route preview missing right-hand traffic policy: {preview}")
    if "warehouse_aisle" not in preview.get("traffic_segments", []):
        raise SystemExit(f"[smoke_movement_api] route preview missing warehouse_aisle segment: {preview}")
    if not any(name.startswith("aisle_right_") for name in preview.get("waypoints", [])):
        raise SystemExit(f"[smoke_movement_api] route preview missing right-hand waypoint: {preview}")

for route_type in ("inbound", "outbound"):
    for item_code in expected_items:
        preview_payload = {
            "command_id": f"preview-{route_type}-{item_code}",
            "task_id": 77,
            "robot_name": "tb3_1",
            "route_type": route_type,
            "item_name": item_code,
            "count": 1,
            "wait_sec": 0.1,
        }
        preview = request_json("POST", f"{tb3_1_url}/movement-api/v1/routes/preview", preview_payload)
        assert_full_transfer_preview(preview, route_type, item_code)

standby_payload = {
    "command_id": "preview-standby-return",
    "task_id": 76,
    "robot_name": "tb3_1",
    "route_type": "standby",
    "wait_sec": 0.0,
    "return_waypoint": "vehicle_1_approach",
}
standby_preview = request_json("POST", f"{tb3_1_url}/movement-api/v1/routes/preview", standby_payload)
if standby_preview.get("operation_sequence") != ["return_to_standby"]:
    raise SystemExit(f"[smoke_movement_api] standby route wrong operation sequence: {standby_preview}")
standby_actions = [step.get("action") for step in standby_preview.get("steps", [])]
if standby_actions != ["nav2_waypoints"] or standby_preview.get("dock_transfer") is not None:
    raise SystemExit(f"[smoke_movement_api] standby route must be nav-only without dock_transfer: {standby_preview}")
if standby_preview.get("traffic_segments"):
    raise SystemExit(f"[smoke_movement_api] standby route should not lock traffic segments: {standby_preview}")
standby_command_payload = {**standby_payload, "command_id": "route-command-standby-return"}
standby_response = request_json("POST", f"{tb3_1_url}/movement-api/v1/routes/commands", standby_command_payload)
if not standby_response.get("accepted") or standby_response.get("operation_sequence") != ["return_to_standby"]:
    raise SystemExit(f"[smoke_movement_api] standby route command not accepted: {standby_response}")
standby_final = wait_for_command(tb3_1_url, "route-command-standby-return", {"DONE"})
if standby_final.get("state") != "DONE":
    raise SystemExit(f"[smoke_movement_api] standby route wrong terminal state: {standby_final}")

traffic_lock = request_json("POST", f"{tb3_2_url}/traffic/lock", {
    "segment_id": "warehouse_aisle",
    "robot_id": "tb3_2",
    "command_id": "blocking-traffic-smoke",
    "ttl_sec": 30,
    "route_type": "outbound",
})
if traffic_lock.get("lock", {}).get("segment_id") != "warehouse_aisle":
    raise SystemExit(f"[smoke_movement_api] traffic lock failed: {traffic_lock}")

blocked_payload = {
    "command_id": "route-command-blocked-by-traffic",
    "task_id": 79,
    "robot_name": "tb3_1",
    "route_type": "inbound",
    "item_name": "bolt",
    "count": 1,
    "wait_sec": 0.1,
}
blocked = request_json("POST", f"{tb3_1_url}/movement-api/v1/routes/commands", blocked_payload, expected=409)
if blocked.get("detail", {}).get("traffic_state") != "WAITING_TRAFFIC":
    raise SystemExit(f"[smoke_movement_api] traffic conflict did not report WAITING_TRAFFIC: {blocked}")

release = request_json("POST", f"{tb3_2_url}/traffic/release", {
    "segment_id": "warehouse_aisle",
    "robot_id": "tb3_2",
    "command_id": "blocking-traffic-smoke",
})
if not release.get("released"):
    raise SystemExit(f"[smoke_movement_api] traffic release failed: {release}")

route_command_payload = {
    "command_id": "route-command-bolt-inbound",
    "task_id": 78,
    "robot_name": "tb3_1",
    "route_type": "inbound",
    "item_name": "볼트",
    "count": 1,
    "wait_sec": 0.1,
}
route_response = request_json("POST", f"{tb3_1_url}/movement-api/v1/routes/commands", route_command_payload)
if not route_response.get("accepted") or route_response.get("item", {}).get("item_code") != "bolt":
    raise SystemExit(f"[smoke_movement_api] route command not accepted: {route_response}")
assert_full_transfer_preview(route_response, "inbound", "bolt")
route_final = wait_for_command(tb3_1_url, "route-command-bolt-inbound", {"DONE"})
if route_final.get("state") != "DONE":
    raise SystemExit(f"[smoke_movement_api] full route command wrong terminal state: {route_final}")

coordinate_preview_payload = {
    "command_id": "route-coordinate-preview",
    "task_id": 80,
    "robot_name": "tb3_1",
    "x": 0.1,
    "y": 1.3,
    "yaw": 0.0,
    "waypoint": "operator_clicked_goal",
}
coordinate_preview = request_json("POST", f"{tb3_1_url}/movement-api/v1/routes/preview", coordinate_preview_payload)
if coordinate_preview.get("input_mode") != "coordinates" or coordinate_preview.get("steps", [{}])[0].get("action") != "nav2_pose":
    raise SystemExit(f"[smoke_movement_api] coordinate route preview failed: {coordinate_preview}")

coordinate_command_payload = {
    "command_id": "route-coordinate-command",
    "task_id": 81,
    "robot_name": "tb3_1",
    "goal": {"x": 0.1, "y": 1.3, "yaw": 0.0, "waypoint": "operator_clicked_goal"},
}
coordinate_response = request_json("POST", f"{tb3_1_url}/movement-api/v1/routes/commands", coordinate_command_payload)
if not coordinate_response.get("accepted") or coordinate_response.get("input_mode") != "coordinates":
    raise SystemExit(f"[smoke_movement_api] coordinate route command not accepted: {coordinate_response}")
coordinate_final = wait_for_command(tb3_1_url, "route-coordinate-command", {"DONE"})
if coordinate_final.get("state") != "DONE":
    raise SystemExit(f"[smoke_movement_api] coordinate route command wrong terminal state: {coordinate_final}")

estop_target = request_json("POST", f"{tb3_1_url}/movement-api/v1/commands", {
    "command_id": "contract-estop-abort",
    "task_id": 907,
    "robot_name": "tb3_1",
    "callback_url": f"{mock_url}/api/v1/movement/command-events",
    "steps": [{"action": "dock_transfer", "payload": {"dry_run": True, "aruco_marker_id": 11, "action": "load", "level": 1}}],
})
if not estop_target.get("accepted"):
    raise SystemExit(f"[smoke_movement_api] estop target command not accepted: {estop_target}")
time.sleep(0.1)
estop_response = request_json("POST", f"{tb3_1_url}/robot/estop")
if "contract-estop-abort" not in estop_response.get("aborted_commands", []):
    raise SystemExit(f"[smoke_movement_api] estop did not abort running command: {estop_response}")
estop_final = wait_for_command(tb3_1_url, "contract-estop-abort", {"ABORTED"})
if estop_final.get("reason") != "estop" or not estop_final.get("stage"):
    raise SystemExit(f"[smoke_movement_api] estop abort missing reason/stage: {estop_final}")
request_json("POST", f"{tb3_1_url}/robot/clear_estop")

commands = [
    (tb3_1_url, "contract-command-tb3-1", "tb3_1"),
    (tb3_2_url, "contract-command-tb3-2", "tb3_2"),
]
for base_url, command_id, robot_name in commands:
    payload = {
        "command_id": command_id,
        "task_id": 12,
        "robot_name": robot_name,
        "steps": [
            {"action": "nav2_pose", "command": None, "duration": None, "payload": {"frame_id": "map", "goal": {"x": 1.2, "y": 0.5, "yaw": 1.57}, "timeout_sec": 60}},
            {"action": "wait", "command": None, "duration": 0.1, "payload": {}},
        ],
    }
    response = request_json("POST", f"{base_url}/movement-api/v1/commands", payload)
    if not response.get("accepted") or response.get("state") != "ACCEPTED":
        raise SystemExit(f"[smoke_movement_api] command not accepted: {response}")
    duplicate = request_json("POST", f"{base_url}/movement-api/v1/commands", payload)
    if not duplicate.get("duplicate"):
        raise SystemExit(f"[smoke_movement_api] duplicate command not idempotent: {duplicate}")

for _ in range(40):
    results = get_json(f"{mock_url}/movement/results")["results"]
    statuses = get_json(f"{mock_url}/movement/robot-statuses")["statuses"]
    if len(results) >= 4 and len(statuses) >= 8:
        break
    time.sleep(0.2)
else:
    raise SystemExit("[smoke_movement_api] callbacks did not arrive")

for robot_name in ("tb3_1", "tb3_2"):
    if not any(item.get("robot_name") == robot_name and item.get("result") == "DONE" for item in results):
        raise SystemExit(f"[smoke_movement_api] missing DONE result for {robot_name}: {results}")
    robot_statuses = [item for item in statuses if item.get("robot_name") == robot_name]
    states = {item["state"] for item in robot_statuses}
    if "busy" not in states or "idle" not in states:
        raise SystemExit(f"[smoke_movement_api] missing busy/idle status for {robot_name}: {robot_statuses}")

print("[smoke_movement_api] PASS /movement-api/v1/endpoints fixed robot IP contract")
print("[smoke_movement_api] PASS /movement-api/v1/waypoints catalog")
print("[smoke_movement_api] PASS /movement-api/v1/robots")
print("[smoke_movement_api] PASS /movement-api/v1/inventory, /robot-commands waypoint_id/coordinate moves, and /simulation-state")
print("[smoke_movement_api] PASS /movement-api/v1/manual/start, /manual/translate, and /manual/stop")
print("[smoke_movement_api] PASS /movement-api/v1/routes right-hand traffic metadata")
print("[smoke_movement_api] PASS traffic segment lock conflict -> WAITING_TRAFFIC, including atomic robot-commands")
print("[smoke_movement_api] PASS /movement-api/v1/routes item and coordinate route commands")
print("[smoke_movement_api] PASS /movement-api/v1/commands idempotent acceptance")
print("[smoke_movement_api] PASS Main callbacks /movement/results and /movement/robots/{robot}/status")
PYSMOKE
