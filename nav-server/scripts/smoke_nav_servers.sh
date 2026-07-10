#!/usr/bin/env bash
#
# Smoke test the two per-robot Nav server API processes.
#
# Prerequisite in another terminal:
#   scripts/run_nav_servers.sh
#
# The default checks are non-moving:
#   - /robots on both ports
#   - /robot/status on both ports
#   - wrong robot_id routing rejection on each server
#
# Use --with-mission with DRY_RUN_MISSION=1 for non-moving lifecycle checks,
# or only when Nav2 and the physical/sim robot are ready to move.

set -euo pipefail

TB3_1_URL="${TB3_1_URL:-http://127.0.0.1:8001}"
TB3_2_URL="${TB3_2_URL:-http://127.0.0.1:8002}"
WITH_MISSION=0

usage() {
  cat <<'EOF'
Usage:
  scripts/smoke_nav_servers.sh [--with-mission]

Environment:
  TB3_1_URL  Base URL for tb3_burger_01 Nav server. Default: http://127.0.0.1:8001
  TB3_2_URL  Base URL for tb3_burger_02 Nav server. Default: http://127.0.0.1:8002

Default mode does not start robot movement. --with-mission sends inbound test missions.
When Nav servers run with DRY_RUN_MISSION=1, --with-mission is non-moving.
EOF
}

while (($# > 0)); do
  case "$1" in
    --with-mission)
      WITH_MISSION=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[smoke_nav_servers] unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
  shift
done

python3 - "$TB3_1_URL" "$TB3_2_URL" "$WITH_MISSION" <<'PYSMOKE'
import json
import sys
import urllib.error
import urllib.request

tb3_1_url, tb3_2_url, with_mission = sys.argv[1], sys.argv[2], sys.argv[3] == "1"


def request(method, url, payload=None, expected_status=200):
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=4) as response:
            body = response.read().decode("utf-8")
            status = response.status
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8")
        status = exc.code

    if status != expected_status:
        raise SystemExit(f"[smoke_nav_servers] FAIL {method} {url}: expected {expected_status}, got {status}, body={body}")
    return json.loads(body) if body else {}


def check_server(base_url, expected_robot_id, expected_domain, wrong_robot_id):
    robots = request("GET", f"{base_url}/robots")
    if robots["active_robot_id"] != expected_robot_id:
        raise SystemExit(f"[smoke_nav_servers] FAIL {base_url}: active_robot_id={robots['active_robot_id']}")
    if int(robots["active_ros_domain_id"]) != expected_domain:
        raise SystemExit(f"[smoke_nav_servers] FAIL {base_url}: active_ros_domain_id={robots['active_ros_domain_id']}")

    status = request("GET", f"{base_url}/robot/status")
    if status["robot_id"] != expected_robot_id:
        raise SystemExit(f"[smoke_nav_servers] FAIL {base_url}: status robot_id={status['robot_id']}")
    if int(status["ros_domain_id"]) != expected_domain:
        raise SystemExit(f"[smoke_nav_servers] FAIL {base_url}: status ros_domain_id={status['ros_domain_id']}")

    wrong_payload = {
        "robot_id": wrong_robot_id,
        "item_name": "smoke_test",
        "count": 1,
        "mission_type": "inbound",
    }
    request("POST", f"{base_url}/mission/start", wrong_payload, expected_status=409)
    print(f"[smoke_nav_servers] PASS {expected_robot_id}: {base_url}, domain={expected_domain}")


check_server(tb3_1_url, "tb3_burger_01", 2, "tb3_burger_02")
check_server(tb3_2_url, "tb3_burger_02", 5, "tb3_burger_01")

if with_mission:
    for base_url, robot_id in ((tb3_1_url, "tb3_burger_01"), (tb3_2_url, "tb3_burger_02")):
        payload = {
            "robot_id": robot_id,
            "item_name": "smoke_test",
            "count": 1,
            "mission_type": "inbound",
        }
        response = request("POST", f"{base_url}/mission/start", payload)
        print(f"[smoke_nav_servers] MISSION {robot_id}: {response['mission_status']} {response['mission_id']} dry_run={response.get('dry_run')}")
PYSMOKE
