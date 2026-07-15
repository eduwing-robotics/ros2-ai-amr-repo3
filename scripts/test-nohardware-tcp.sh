#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${ROOT_DIR}/scripts/lib/nohardware-process-groups.sh"
NAV_PY="${NAV_PY:-${ROOT_DIR}/nav-server/.venv/bin/python}"
MAIN_PY="${MAIN_PY:-${ROOT_DIR}/main-server/.venv/bin/python}"
AI_PY="${AI_PY:-${ROOT_DIR}/ai-server/.venv/bin/python}"
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
FRONTEND_DIR="${FRONTEND_DIR:-${ROOT_DIR}/main-server/frontend/web}"

for py in "${NAV_PY}" "${MAIN_PY}" "${AI_PY}"; do
  if [[ ! -x "${py}" ]]; then
    echo "[nohardware-tcp] missing executable ${py}" >&2
    exit 127
  fi
done
for command in setsid docker npm; do
  if ! command -v "${command}" >/dev/null 2>&1; then
    echo "[nohardware-tcp] ${command} is required" >&2
    exit 127
  fi
done
if [[ ! -d "${FRONTEND_DIR}/node_modules" ]]; then
  echo "[nohardware-tcp] frontend dependencies are missing; run scripts/bootstrap-nohardware-envs.sh" >&2
  exit 127
fi

printf '%s\n' "[nohardware-tcp] verify bounded process-group cleanup"
"${MAIN_PY}" -m pytest -q \
  "${ROOT_DIR}/tests/nohardware/test_nohardware_process_cleanup.py" \
  "${ROOT_DIR}/tests/nohardware/test_main_movement_client_contract.py"

printf '%s\n' "[nohardware-tcp] build current frontend for Main static serving"
(
  cd "${FRONTEND_DIR}"
  npm run build
)

if [[ ! -f "${ROS_SETUP}" ]]; then
  echo "[nohardware-tcp] missing ROS setup ${ROS_SETUP}" >&2
  exit 127
fi
set +u
# shellcheck disable=SC1090
source "${ROS_SETUP}"
set -u
if ! command -v ros2 >/dev/null 2>&1; then
  echo "[nohardware-tcp] ros2 is unavailable after sourcing ${ROS_SETUP}" >&2
  exit 127
fi
if ! "${NAV_PY}" -c 'import rclpy, tf2_ros, geometry_msgs, nav2_simple_commander'; then
  echo "[nohardware-tcp] ROS Python runtime imports are unavailable" >&2
  exit 127
fi

pick_port() {
  "${MAIN_PY}" - <<'PY'
import socket
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.bind(("127.0.0.1", 0))
    print(sock.getsockname()[1])
PY
}

wait_http() {
  local url="$1"
  local timeout_sec="${2:-20}"
  local py="$3"
  "${py}" - "${url}" "${timeout_sec}" <<'PY'
import json
import sys
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

url = sys.argv[1]
deadline = time.time() + float(sys.argv[2])
last = None
while time.time() < deadline:
    try:
        req = Request(url, headers={"Accept": "application/json"})
        with urlopen(req, timeout=0.8) as res:
            body = res.read().decode("utf-8")
            if 200 <= res.status < 500:
                payload = json.loads(body) if body else {}
                print(json.dumps({"url": url, "status": res.status, "payload": payload}, ensure_ascii=False, sort_keys=True))
                raise SystemExit(0)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        last = exc
    time.sleep(0.2)
print(f"timeout waiting for {url}: {last}", file=sys.stderr)
raise SystemExit(1)
PY
}

port_is_open() {
  local port="$1"
  "${MAIN_PY}" - "${port}" <<'PY'
import socket
import sys
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    sock.settimeout(0.2)
    raise SystemExit(0 if sock.connect_ex(("127.0.0.1", int(sys.argv[1]))) == 0 else 1)
PY
}

LOG_DIR=""
DB_CID=""
declare -a NOHARDWARE_PORTS=()
cleanup() {
  local status=$?
  local cleanup_failed=0
  local port secret file attempt
  trap - EXIT INT TERM

  nohardware_stop_all_process_groups || cleanup_failed=1
  if [[ ${#NOHARDWARE_OWNED_PROCESS_GROUPS[@]} -ne 0 ]]; then
    echo "[nohardware-tcp] owned process-group registry was not emptied" >&2
    cleanup_failed=1
  fi
  if [[ -n "${DB_CID}" ]]; then
    docker rm -f "${DB_CID}" >/dev/null 2>&1 || cleanup_failed=1
    DB_CID=""
  fi

  if [[ -n "${LOG_DIR}" && -d "${LOG_DIR}" ]]; then
    for secret in \
      "${NOHARDWARE_HMAC_SECRET:-}" \
      "${NOHARDWARE_VISION_HMAC_SECRET:-}" \
      "${NOHARDWARE_VISION_GATEWAY_HMAC_SECRET:-}" \
      "${DB_PASSWORD:-}"; do
      [[ -n "${secret}" ]] || continue
      if grep -FR -- "${secret}" "${LOG_DIR}" >/dev/null 2>&1; then
        echo "[nohardware-tcp] secret value appeared in fixture logs" >&2
        cleanup_failed=1
      fi
    done
    if [[ ${status} -ne 0 ]]; then
      for file in "${LOG_DIR}"/*.log; do
        [[ -f "${file}" ]] || continue
        echo "--- $(basename "${file}") ---" >&2
        tail -120 "${file}" \
          | sed \
              -e "s|${NOHARDWARE_HMAC_SECRET:-__unset_main_nav__}|[REDACTED]|g" \
              -e "s|${NOHARDWARE_VISION_HMAC_SECRET:-__unset_main_ai__}|[REDACTED]|g" \
              -e "s|${NOHARDWARE_VISION_GATEWAY_HMAC_SECRET:-__unset_gateway__}|[REDACTED]|g" \
              -e "s|${DB_PASSWORD:-__unset_db__}|[REDACTED]|g" >&2 || true
      done
    fi
    rm -rf "${LOG_DIR}"
    [[ ! -e "${LOG_DIR}" ]] || cleanup_failed=1
  fi

  for port in "${NOHARDWARE_PORTS[@]}"; do
    for ((attempt = 0; attempt < 20; attempt++)); do
      port_is_open "${port}" || break
      sleep 0.05
    done
    if port_is_open "${port}"; then
      echo "[nohardware-tcp] listener remained on 127.0.0.1:${port}" >&2
      cleanup_failed=1
    fi
  done
  if [[ ${cleanup_failed} -ne 0 ]]; then
    echo "[nohardware-tcp] CLEANUP FAILED original_status=${status}" >&2
    status=1
  else
    echo "[nohardware-tcp] CLEANUP PASSED exit_status=${status}" >&2
  fi
  exit "${status}"
}
trap cleanup EXIT
trap 'exit 130' INT TERM

LOG_DIR="$(mktemp -d /tmp/nohardware-tcp.XXXXXX)"
NAV_PORT="$(pick_port)"
AI_PORT="$(pick_port)"
MAIN_PORT="$(pick_port)"
NAV_BASE="http://127.0.0.1:${NAV_PORT}"
AI_BASE="http://127.0.0.1:${AI_PORT}"
MAIN_BASE="http://127.0.0.1:${MAIN_PORT}"
NOHARDWARE_PORTS+=("${NAV_PORT}" "${AI_PORT}" "${MAIN_PORT}")
NOHARDWARE_HMAC_SECRET="$("${MAIN_PY}" -c 'import secrets; print(secrets.token_urlsafe(32))')"
NOHARDWARE_VISION_HMAC_SECRET="$("${AI_PY}" -c 'import secrets; print(secrets.token_urlsafe(32))')"
NOHARDWARE_VISION_GATEWAY_HMAC_SECRET="$("${AI_PY}" -c 'import secrets; print(secrets.token_urlsafe(32))')"
DB_PASSWORD="$("${MAIN_PY}" -c 'import secrets; print(secrets.token_urlsafe(24))')"
DB_NAME="lms_nohardware_fullstack"
DB_USER="postgres"
DB_CONTAINER_NAME="nohardware-fullstack-${RANDOM}-$$"

printf '%s\n' "[nohardware-tcp] starting disposable PostgreSQL"
DB_CID="$(docker run -d \
  --name "${DB_CONTAINER_NAME}" \
  -e POSTGRES_USER="${DB_USER}" \
  -e POSTGRES_PASSWORD="${DB_PASSWORD}" \
  -e POSTGRES_DB="${DB_NAME}" \
  -p 127.0.0.1::5432 \
  postgres:16-alpine)"
DB_PORT="$(docker port "${DB_CID}" 5432/tcp | sed -E 's/.*:([0-9]+)$/\1/')"
NOHARDWARE_PORTS+=("${DB_PORT}")
DATABASE_URL="postgresql://${DB_USER}:${DB_PASSWORD}@127.0.0.1:${DB_PORT}/${DB_NAME}"
for _ in {1..60}; do
  if docker exec "${DB_CID}" psql -U "${DB_USER}" -d "${DB_NAME}" -c 'SELECT 1' >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
if ! docker exec "${DB_CID}" psql -U "${DB_USER}" -d "${DB_NAME}" -c 'SELECT 1' >/dev/null 2>&1; then
  echo "[nohardware-tcp] PostgreSQL did not become ready" >&2
  exit 1
fi
printf '%s\n' "[nohardware-tcp] READY postgres container=${DB_CONTAINER_NAME} port=${DB_PORT}"

printf '%s\n' "[nohardware-tcp] starting actual Nav runtime on ${NAV_BASE}"
# Positional parameters belong to the isolated child shell.
# shellcheck disable=SC2016
setsid bash -c 'cd "$1"; shift; exec "$@"' nohardware-nav "${ROOT_DIR}" \
  env PYTHONPATH="${ROOT_DIR}/nav-server:${ROOT_DIR}/nav-server/scripts${PYTHONPATH:+:${PYTHONPATH}}" \
  ROBOT_ID="tb3_burger_01" \
  ROS_DOMAIN_ID="2" \
  ROS_LOCALHOST_ONLY="1" \
  ROBOTS_CONFIG_PATH="${ROOT_DIR}/nav-server/config/robots.nohardware.json" \
  MAIN_SERVER_ROUTES_PATH="${ROOT_DIR}/nav-server/config/main_server_routes.json" \
  ACTIVE_MAP_YAML="${ROOT_DIR}/nav-server/map/robot2_map.yaml" \
  SIMULATION_MODE="1" \
  DRY_RUN_MISSION="1" \
  NAV2_SKIP_ACTIVE_WAIT="1" \
  MAIN_API_BASE="${MAIN_BASE}/api/v1" \
  NAV_NOHARDWARE="true" \
  NAV_NOHARDWARE_CALLBACK_ALLOWLIST="${MAIN_BASE}" \
  NAV_MAIN_HMAC_SECRET="${NOHARDWARE_HMAC_SECRET}" \
  MAIN_CALLBACK_TIMEOUT_SEC="1.0" \
  SIMULATED_STEP_DELAY_SEC="2.0" \
  "${NAV_PY}" -m uvicorn nav_app.app:app --host 127.0.0.1 --port "${NAV_PORT}" --log-level warning \
  >"${LOG_DIR}/nav.log" 2>&1 &
NAV_PID=$!
nohardware_register_process_group "${NAV_PID}"
wait_http "${NAV_BASE}/movement-api/v1/health" 20 "${NAV_PY}" >/dev/null
printf '%s\n' "[nohardware-tcp] READY nav pid=${NAV_PID} base=${NAV_BASE}"

printf '%s\n' "[nohardware-tcp] starting actual AI runtime on ${AI_BASE}"
# Positional parameters belong to the isolated child shell.
# shellcheck disable=SC2016
setsid bash -c 'cd "$1"; shift; exec "$@"' nohardware-ai "${ROOT_DIR}/ai-server" \
  env MAIN_HMAC_SECRET="${NOHARDWARE_VISION_HMAC_SECRET}" \
  VISION_GATEWAY_HMAC_SECRET="${NOHARDWARE_VISION_GATEWAY_HMAC_SECRET}" \
  NOHARDWARE_AI_PORT="${AI_PORT}" \
  PYTHONPATH="${ROOT_DIR}/ai-server:${ROOT_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
  "${AI_PY}" "${ROOT_DIR}/tests/nohardware/serve_ai_person_fixture.py" \
  >"${LOG_DIR}/ai.log" 2>&1 &
AI_PID=$!
nohardware_register_process_group "${AI_PID}"
wait_http "${AI_BASE}/api/v1/health" 30 "${AI_PY}" >/dev/null
printf '%s\n' "[nohardware-tcp] READY ai pid=${AI_PID} base=${AI_BASE}"

printf '%s\n' "[nohardware-tcp] starting assembled Main + built UI on ${MAIN_BASE}"
# Positional parameters belong to the isolated child shell.
# shellcheck disable=SC2016
setsid bash -c 'cd "$1"; shift; exec "$@"' nohardware-main "${ROOT_DIR}/main-server/backend" \
  env PYTHONPATH="${ROOT_DIR}/main-server/backend:${ROOT_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
  LMS_DATABASE_URL="${DATABASE_URL}" \
  LMS_MOVEMENT_CLIENT_MODE="http" \
  LMS_MOVEMENT_BASE_URLS="tb3_1=${NAV_BASE}/movement-api/v1" \
  LMS_MOVEMENT_HMAC_SECRET="${NOHARDWARE_HMAC_SECRET}" \
  LMS_MOVEMENT_ACTIVE_MAP_ID="robot2_map" \
  LMS_PUBLIC_BASE_URL="${MAIN_BASE}" \
  LMS_CALLBACK_BASE_URL="${MAIN_BASE}" \
  LMS_CALLBACK_ALLOW_HTTP="true" \
  LMS_NOHARDWARE="true" \
  LMS_NOHARDWARE_CALLBACK_ALLOWLIST="${MAIN_BASE}" \
  LMS_VISION_API_BASE_URL="${AI_BASE}" \
  LMS_VISION_STREAM_BASE_URL="${AI_BASE}" \
  LMS_VISION_HMAC_SECRET="${NOHARDWARE_VISION_HMAC_SECRET}" \
  LMS_VISION_TIMEOUT_SEC="3.0" \
  LMS_LIFT_LOAD_EVIDENCE_ENABLED="true" \
  LMS_LIFT_LOAD_EVIDENCE_MODE="gate" \
  LMS_LIFT_LOAD_EVIDENCE_SOURCE="global_cam_01" \
  LMS_LIFT_LOAD_MARKER_MAP_JSON='{"BOX-A":"20"}' \
  LMS_LIFT_LOAD_BURST_FRAMES="1" \
  LMS_LIFT_LOAD_MIN_PASS_FRAMES="1" \
  LMS_LIFT_LOAD_SAMPLE_INTERVAL_MS="0" \
  LMS_LIFT_LOAD_MAX_FRAME_AGE_S="3.0" \
  LMS_PERSON_HAZARD_ENABLED="true" \
  LMS_PERSON_HAZARD_POLL_HZ="10" \
  LMS_PERSON_HAZARD_STALE_SEC="5" \
  LMS_PERSON_HAZARD_TIMEOUT_SEC="1.0" \
  LMS_RECOVERY_SAFE_LOCATION_ID="HOME_01" \
  "${MAIN_PY}" -m uvicorn app.main:app --host 127.0.0.1 --port "${MAIN_PORT}" --log-level warning \
  >"${LOG_DIR}/main.log" 2>&1 &
MAIN_PID=$!
nohardware_register_process_group "${MAIN_PID}"
wait_http "${MAIN_BASE}/health" 30 "${MAIN_PY}" >/dev/null
printf '%s\n' "[nohardware-tcp] READY main pid=${MAIN_PID} base=${MAIN_BASE}"

# Mutable demo data is test-only. Main startup owns the current schema,
# migrations, static robot/camera seed, and lifespan initialization.
docker exec -i "${DB_CID}" psql -U "${DB_USER}" -d "${DB_NAME}" -v ON_ERROR_STOP=1 \
  < "${ROOT_DIR}/main-server/backend/tests/fixtures/demo_seed_pg.sql" >/dev/null

printf '%s\n' "[nohardware-tcp] production robot2_map reference sync replay + persisted identity"
env PYTHONPATH="${ROOT_DIR}/main-server/backend:${ROOT_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
  LMS_DATABASE_URL="${DATABASE_URL}" \
  "${MAIN_PY}" "${ROOT_DIR}/tests/nohardware/check_reference_sync_pg.py"

printf '%s\n' "[nohardware-tcp] enabled robot, release-managed HTTP boundary, and vision transport"
LMS_MOVEMENT_HMAC_SECRET="${NOHARDWARE_HMAC_SECRET}" \
LMS_VISION_HMAC_SECRET="${NOHARDWARE_VISION_HMAC_SECRET}" \
  "${MAIN_PY}" "${ROOT_DIR}/tests/nohardware/check_full_stack_tcp.py" \
    --phase preseed \
    --main-base "${MAIN_BASE}" \
    --nav-base "${NAV_BASE}" \
    --ai-base "${AI_BASE}"

printf '%s\n' "[nohardware-tcp] seed RUNNING INBOUND for public safe-stop proof"
SAFE_STOP_RESULT="$(
  env PYTHONPATH="${ROOT_DIR}/main-server/backend:${ROOT_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
    LMS_DATABASE_URL="${DATABASE_URL}" \
    "${MAIN_PY}" "${ROOT_DIR}/tests/nohardware/seed_running_work_order_pg.py"
)"
read -r SAFE_STOP_ORDER_ID SAFE_STOP_COMMAND_ID < <(
  "${MAIN_PY}" -c \
    'import json,sys; p=json.loads(sys.argv[1]); print(p["order_id"], p["command_id"])' \
    "${SAFE_STOP_RESULT}"
)

printf '%s\n' "[nohardware-tcp] public work-order stop -> signed Nav cancel -> signed terminal callback"
LMS_MOVEMENT_HMAC_SECRET="${NOHARDWARE_HMAC_SECRET}" \
LMS_VISION_HMAC_SECRET="${NOHARDWARE_VISION_HMAC_SECRET}" \
  "${MAIN_PY}" "${ROOT_DIR}/tests/nohardware/check_full_stack_tcp.py" \
    --phase safe-stop \
    --main-base "${MAIN_BASE}" \
    --nav-base "${NAV_BASE}" \
    --ai-base "${AI_BASE}" \
    --safe-stop-order-id "${SAFE_STOP_ORDER_ID}" \
    --safe-stop-command-id "${SAFE_STOP_COMMAND_ID}"

printf '%s\n' "[nohardware-tcp] production Main PRE_DROP_OFF evaluation over live AI + PostgreSQL"
EVIDENCE_RESULT="$(
  env PYTHONPATH="${ROOT_DIR}/main-server/backend:${ROOT_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
    LMS_DATABASE_URL="${DATABASE_URL}" \
    LMS_VISION_API_BASE_URL="${AI_BASE}" \
    LMS_VISION_HMAC_SECRET="${NOHARDWARE_VISION_HMAC_SECRET}" \
    LMS_VISION_TIMEOUT_SEC="3.0" \
    LMS_LIFT_LOAD_EVIDENCE_ENABLED="true" \
    LMS_LIFT_LOAD_EVIDENCE_MODE="gate" \
    LMS_LIFT_LOAD_EVIDENCE_SOURCE="global_cam_01" \
    LMS_LIFT_LOAD_MARKER_MAP_JSON='{"BOX-A":"20"}' \
    LMS_LIFT_LOAD_BURST_FRAMES="1" \
    LMS_LIFT_LOAD_MIN_PASS_FRAMES="1" \
    LMS_LIFT_LOAD_SAMPLE_INTERVAL_MS="0" \
    LMS_LIFT_LOAD_MAX_FRAME_AGE_S="3.0" \
    "${MAIN_PY}" "${ROOT_DIR}/tests/nohardware/check_lift_load_evidence_pg.py" --ai-base "${AI_BASE}"
)"
read -r EVIDENCE_TASK_ID EVIDENCE_ID < <(
  "${MAIN_PY}" -c \
    'import json,sys; p=json.loads(sys.argv[1]); print(p["task_id"], p["evidence_id"])' \
    "${EVIDENCE_RESULT}"
)

printf '%s\n' "[nohardware-tcp] seed only the ASSIGNED INBOUND commissioning-gate precondition"
ASSIGNED_RESULT="$(
  env PYTHONPATH="${ROOT_DIR}/main-server/backend:${ROOT_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
    LMS_DATABASE_URL="${DATABASE_URL}" \
    "${MAIN_PY}" "${ROOT_DIR}/tests/nohardware/seed_assigned_inbound_pg.py"
)"
ASSIGNED_INBOUND_TASK_ID="$(
  "${MAIN_PY}" -c 'import json,sys; print(json.loads(sys.argv[1])["task_id"])' "${ASSIGNED_RESULT}"
)"

printf '%s\n' "[nohardware-tcp] dedicated frame-gateway HMAC boundary"
VISION_GATEWAY_HMAC_SECRET="${NOHARDWARE_VISION_GATEWAY_HMAC_SECRET}" \
MAIN_HMAC_SECRET="${NOHARDWARE_VISION_HMAC_SECRET}" \
  "${AI_PY}" "${ROOT_DIR}/tests/nohardware/check_ai_gateway_frame_tcp.py" --base "${AI_BASE}"

printf '%s\n' "[nohardware-tcp] assembled Main/Nav/AI/PostgreSQL/UI acceptance"
LMS_MOVEMENT_HMAC_SECRET="${NOHARDWARE_HMAC_SECRET}" \
LMS_VISION_HMAC_SECRET="${NOHARDWARE_VISION_HMAC_SECRET}" \
VISION_GATEWAY_HMAC_SECRET="${NOHARDWARE_VISION_GATEWAY_HMAC_SECRET}" \
  "${MAIN_PY}" "${ROOT_DIR}/tests/nohardware/check_full_stack_tcp.py" \
    --main-base "${MAIN_BASE}" \
    --nav-base "${NAV_BASE}" \
    --ai-base "${AI_BASE}" \
    --assigned-inbound-task-id "${ASSIGNED_INBOUND_TASK_ID}" \
    --evidence-task-id "${EVIDENCE_TASK_ID}" \
    --evidence-id "${EVIDENCE_ID}"

printf '%s\n' "[nohardware-tcp] boot/smoke every enabled robot map"
while IFS=$'\t' read -r robot_id bridge_robot_id ros_domain_id active_map_yaml; do
  [[ -n "${robot_id}" ]] || continue
  map_port="$(pick_port)"
  NOHARDWARE_PORTS+=("${map_port}")
  map_base="http://127.0.0.1:${map_port}"
  map_yaml_path="${ROOT_DIR}/nav-server/${active_map_yaml}"
  map_log="${LOG_DIR}/nav-${robot_id}.log"
  # Positional parameters belong to the isolated child shell.
  # shellcheck disable=SC2016
  setsid bash -c 'cd "$1"; shift; exec "$@"' nohardware-map "${ROOT_DIR}" \
    env PYTHONPATH="${ROOT_DIR}/nav-server:${ROOT_DIR}/nav-server/scripts${PYTHONPATH:+:${PYTHONPATH}}" \
    ROBOT_ID="${robot_id}" \
    ROS_DOMAIN_ID="${ros_domain_id}" \
    ROS_LOCALHOST_ONLY="1" \
    ROBOTS_CONFIG_PATH="${ROOT_DIR}/nav-server/config/robots.nohardware.json" \
    MAIN_SERVER_ROUTES_PATH="${ROOT_DIR}/nav-server/config/main_server_routes.json" \
    ACTIVE_MAP_YAML="${map_yaml_path}" \
    SIMULATION_MODE="1" \
    DRY_RUN_MISSION="1" \
    NAV2_SKIP_ACTIVE_WAIT="1" \
    MAIN_API_BASE="disabled" \
    NAV_MAIN_HMAC_SECRET="${NOHARDWARE_HMAC_SECRET}" \
    MAIN_CALLBACK_TIMEOUT_SEC="0.2" \
    SIMULATED_STEP_DELAY_SEC="0.01" \
    "${NAV_PY}" -m uvicorn nav_app.app:app --host 127.0.0.1 --port "${map_port}" --log-level warning \
    >"${map_log}" 2>&1 &
  map_pid=$!
  nohardware_register_process_group "${map_pid}"
  wait_http "${map_base}/movement-api/v1/health" 20 "${NAV_PY}" >/dev/null
  "${NAV_PY}" "${ROOT_DIR}/tests/nohardware/check_enabled_robot_maps_tcp.py" \
    --base "${map_base}" \
    --robot-id "${robot_id}" \
    --bridge-robot-id "${bridge_robot_id}" \
    --map-yaml "${map_yaml_path}" \
    --robots-config "${ROOT_DIR}/nav-server/config/robots.nohardware.json"
  nohardware_stop_process_group "${map_pid}"
done < <(
  "${NAV_PY}" - "${ROOT_DIR}/nav-server/config/robots.nohardware.json" <<'PY'
import json
import sys
for robot in json.load(open(sys.argv[1], encoding="utf-8"))["robots"]:
    if robot.get("enabled"):
        print("\t".join(str(robot[key]) for key in ("robot_id", "bridge_robot_id", "ros_domain_id", "active_map_yaml")))
PY
)

printf '%s\n' "[nohardware-tcp] PASSED"
