#!/usr/bin/env bash
# 슬롯 insert 잔류 시 reverse_out(slot_reverse_out) 선행.
# zones.json approach/dock 기준으로 전 구역 감지.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
BASE="${MOVEMENT_API_URL:-http://127.0.0.1:8002}"
ROBOT_ID="${ROBOT_ID:-tb3_2}"
CID_PREFIX="${CID_PREFIX:-revout}"

poll_done() {
  local cid="$1" timeout="${2:-120}"
  local deadline=$((SECONDS + timeout))
  while (( SECONDS < deadline )); do
    local body state
    body=$(curl -sf "$BASE/robot-commands/$cid") || return 1
    state=$(echo "$body" | python3 -c "import sys,json; print(json.load(sys.stdin).get('state',''))")
    echo "[reverse_out] $cid -> $state"
    [[ "$state" == "DONE" ]] && return 0
    [[ "$state" == "FAILED" || "$state" == "ABORTED" ]] && return 1
    sleep 3
  done
  return 1
}

detected=$(curl -sf "$BASE/movement-api/v1/robots/tb3_2/nav-state" > /tmp/nav_state_for_revout.json && \
NAV_STATE_PATH=/tmp/nav_state_for_revout.json ZONES_PATH="$ROOT/map/zones.json" python3 <<'PY'
import json, math, os

with open(os.environ["ZONES_PATH"], encoding="utf-8") as f:
    zones = json.load(f)
with open(os.environ["NAV_STATE_PATH"], encoding="utf-8") as f:
    pose = json.load(f).get("pose") or {}
x, y = float(pose.get("x", 0)), float(pose.get("y", 0))
wps = zones.get("waypoints", {})
semantic = zones.get("semantic_zones", {})

def in_rect(rect, px, py, shrink=0.03):
    return (
        float(rect["min_x"]) + shrink <= px <= float(rect["max_x"]) - shrink
        and float(rect["min_y"]) + shrink <= py <= float(rect["max_y"]) - shrink
    )

# 대기장: semantic rect 안 + approach보다 안쪽(실제 주차 깊이)
wait_slots = [
    ("wait1", 3, "vehicle_1_approach", "vehicle_1_zone"),
    ("wait2", 4, "vehicle_2_approach", "vehicle_2_zone"),
]
for key, marker, a_id, z_id in wait_slots:
    a = wps.get(a_id)
    z = semantic.get(z_id)
    if not a or not z or "rect" not in z:
        continue
    ay = float(a["y"])
    depth_m = float(a.get("fork_insert_distance_m", 0.30) or 0.30)
    if in_rect(z["rect"], x, y) and y > ay + min(0.12, depth_m * 0.35):
        print(f"{key}|{marker}")
        break
else:
    slots = [
        ("inbound2", 1, "inbound_slot_2_approach", "inbound_slot_2_dock"),
        ("inbound1", 0, "inbound_slot_1_approach", "inbound_slot_1_dock"),
        ("outbound1", 5, "outbound_slot_1_approach", "outbound_slot_1_dock"),
        ("outbound2", 6, "outbound_slot_2_approach", "outbound_slot_2_dock"),
        ("a", 7, "warehouse_a_approach", "warehouse_a_dock"),
        ("b", 8, "warehouse_b_approach", "warehouse_b_dock"),
        ("c", 10, "warehouse_c_approach", "warehouse_c_dock"),
        ("d", 9, "warehouse_d_approach", "warehouse_d_dock"),
    ]

    def inside_vertical(ax, ay, dx, dy, px, py, insert_m, margin=0.08):
        xmin, xmax = sorted((ax, dx))
        depth = max(insert_m, 0.25) + 0.05
        return (xmin - 0.08) <= px <= (xmax + 0.08) and (ay + margin) < py <= (ay + depth)

    def inside_horizontal(ax, ay, dx, dy, px, py, insert_m, margin=0.08):
        ymin, ymax = sorted((ay, dy))
        depth = max(insert_m, 0.25) + 0.05
        return (ymin - 0.08) <= py <= (ymax + 0.08) and (ax + margin) < px <= (ax + depth)

    for key, marker, a_id, d_id in slots:
        a, d = wps.get(a_id), wps.get(d_id)
        if not a or not d:
            continue
        ax, ay = float(a["x"]), float(a["y"])
        dx, dy = float(d["x"]), float(d["y"])
        insert_m = float(a.get("fork_insert_distance_m", 0.35) or 0.35)
        theta = float(a.get("theta", 0))
        inserted = False
        if abs(abs(theta) - math.pi / 2) < 0.35:
            inserted = inside_vertical(ax, ay, dx, dy, x, y, insert_m)
        elif abs(theta) < 0.35 or abs(abs(theta) - math.pi) < 0.35:
            inserted = inside_horizontal(ax, ay, dx, dy, x, y, insert_m)
        else:
            dist_a = math.hypot(x - ax, y - ay)
            dist_d = math.hypot(x - dx, y - dy)
            inserted = dist_d < dist_a and dist_d < insert_m + 0.10
        if inserted:
            print(f"{key}|{marker}")
            break
    else:
        print("no|0")
PY
)

zone_key="${detected%%|*}"
marker_id="${detected##*|}"

if [[ "$zone_key" == "no" ]]; then
  echo "[reverse_out] insert 구역 아님 (pose 기준) — skip"
  exit 0
fi

echo "[reverse_out] $zone_key insert 감지 (marker=#$marker_id) — 후진 선행"
cid="${CID_PREFIX}-rev-${marker_id}"
code=$(curl -s -o /tmp/revout_post.json -w '%{http_code}' -X POST "$BASE/robot-commands" \
  -H 'Content-Type: application/json' \
  -d "{\"command_id\":\"$cid\",\"task_id\":9001,\"robot_id\":\"$ROBOT_ID\",\"kind\":\"reverse_out\",\"params\":{\"aruco_marker_id\":${marker_id}},\"callback_url\":\"\"}")
echo "[reverse_out] HTTP $code"
python3 -m json.tool /tmp/revout_post.json
[[ "$code" == "200" ]] || exit 1
poll_done "$cid" 120
