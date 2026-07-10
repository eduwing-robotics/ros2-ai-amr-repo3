#!/usr/bin/env bash
# PHASE_79 verification: map visibility, manual robot assignment contract, task robot visibility.
#
# Default mode is read-only. Set LMS_VERIFY_MUTATING=1 only against a test/disposable
# server if you want to create a sample work order and verify robot_id assignment.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_BASE="${LMS_VERIFY_API_BASE:-http://localhost:8088/api/v1}"
PY="${PYTHON:-python3}"

fail() {
  echo "[operator-control] FAIL: $*" >&2
  exit 1
}

pass() {
  echo "[operator-control] OK: $*"
}

need_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "$1 is required"
}

curl_json() {
  local url="$1"
  curl -fsS "$url"
}

post_json() {
  local url="$1" body="$2"
  curl -fsS -X POST "$url" -H "Content-Type: application/json" -d "$body"
}

json_get() {
  local expr="$1"
  "$PY" -c '
import json, sys
data = json.load(sys.stdin)
expr = sys.argv[1]
try:
    safe = {"all": all, "any": any, "bool": bool, "float": float, "int": int, "len": len, "next": next, "str": str, "sum": sum}
    value = eval(expr, {"__builtins__": safe}, {"data": data})
except Exception as exc:
    raise SystemExit(f"json expression failed: {exc}")
if isinstance(value, (dict, list)):
    print(json.dumps(value, ensure_ascii=False))
elif value is None:
    print("")
else:
    print(value)
' "$expr"
}

need_cmd curl
need_cmd "$PY"

echo "[operator-control] API_BASE=$API_BASE"

status_json="$(curl_json "$API_BASE/status")" || fail "cannot reach $API_BASE/status"
movement_mode="$(printf '%s' "$status_json" | json_get 'data.get("system", {}).get("movement_mode", "")')"
[[ "$movement_mode" == "http" ]] || fail "movement_mode is not http: $movement_mode"
pass "Main server is real/http"

maps_json="$(curl_json "$API_BASE/maps")" || fail "cannot reach $API_BASE/maps"
map_count="$(printf '%s' "$maps_json" | json_get 'len(data)')"
[[ "$map_count" -gt 0 ]] || fail "GET /maps returned no maps"

selected_map="$(printf '%s' "$maps_json" | json_get 'next((m for m in data if m.get("map_id") == "robot2_map"), data[0])')"
map_id="$(printf '%s' "$selected_map" | json_get 'data.get("map_id", "")')"
image_url="$(printf '%s' "$selected_map" | json_get 'data.get("image_url", "")')"
asset_status="$(printf '%s' "$selected_map" | json_get 'data.get("asset_status", "")')"
runtime_map_id="$(printf '%s' "$selected_map" | json_get 'data.get("runtime_map_id", "")')"

[[ -n "$image_url" ]] || fail "map $map_id has empty image_url; UI cannot render a background"
curl -fsSI "${API_BASE%/api/v1}${image_url}" >/dev/null || fail "map image is not reachable: $image_url"
pass "map $map_id has reachable image_url ($asset_status, runtime=$runtime_map_id)"

if [[ "$asset_status" == "mismatch" ]]; then
  echo "[operator-control] WARN: map/runtime mismatch remains; UI must show background plus warning, not blank map"
fi

tasks_json="$(curl_json "$API_BASE/tasks?limit=20")" || fail "cannot reach /tasks"
assigned_visible_count="$(printf '%s' "$tasks_json" | json_get 'sum(1 for t in data if t.get("assigned_robot_id"))')"
running_without_robot="$(printf '%s' "$tasks_json" | json_get '[t.get("task_id") for t in data if t.get("status") in {"ASSIGNED", "RUNNING"} and not t.get("assigned_robot_id")]')"
[[ "$running_without_robot" == "[]" ]] || fail "active tasks without assigned_robot_id: $running_without_robot"
pass "active task API exposes assigned_robot_id; assigned rows=$assigned_visible_count"

work_orders_json="$(curl_json "$API_BASE/work-orders?limit=20")" || fail "cannot reach /work-orders"
wo_missing_robot="$(printf '%s' "$work_orders_json" | json_get '[o.get("order_id") for o in data for t in o.get("tasks", []) if t.get("status") in {"ASSIGNED", "RUNNING"} and not t.get("assigned_robot_id")]')"
[[ "$wo_missing_robot" == "[]" ]] || fail "active work order tasks without assigned_robot_id: $wo_missing_robot"
pass "work order API exposes assigned_robot_id for active task rows"

if [[ "${LMS_VERIFY_MUTATING:-0}" != "1" ]]; then
  echo "[operator-control] SKIP: mutating robot_id work-order check (set LMS_VERIFY_MUTATING=1 on a test/disposable server)"
  exit 0
fi

if [[ "${LMS_ALLOW_MUTABLE_DB_TESTS:-0}" != "1" ]]; then
  fail "refusing mutating check without LMS_ALLOW_MUTABLE_DB_TESTS=1"
fi

target_robot="${LMS_VERIFY_ROBOT_ID:-tb3_2}"
item_code="${LMS_VERIFY_ITEM_CODE:-bolt_1}"
quantity="${LMS_VERIFY_QUANTITY:-1}"

body="$(printf '{"operation":"inbound","item_code":"%s","quantity":%s,"auto_start":false,"robot_id":"%s","created_by":"phase79_verify"}' "$item_code" "$quantity" "$target_robot")"
created="$(post_json "$API_BASE/work-orders" "$body")" || fail "work order creation with robot_id failed"
order_id="$(printf '%s' "$created" | json_get 'data.get("order_id")')"
assigned="$(printf '%s' "$created" | json_get 'next((t.get("assigned_robot_id") for t in data.get("tasks", []) if t.get("assigned_robot_id")), "")')"

[[ "$assigned" == "$target_robot" ]] || fail "work order $order_id was not assigned to $target_robot (assigned=$assigned). Manual robot assignment contract is not implemented or sweeper stole it."
pass "work order $order_id honors robot_id=$target_robot"
