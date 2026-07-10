#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAV_PY="${ROOT_DIR}/nav-server/.venv/bin/python"
MAIN_PY="${ROOT_DIR}/main-server/.venv/bin/python"
AI_PY="${ROOT_DIR}/ai-server/.venv/bin/python"
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"

for py in "${NAV_PY}" "${MAIN_PY}" "${AI_PY}"; do
  if [[ ! -x "${py}" ]]; then
    echo "[nohardware-tcp] missing executable ${py}" >&2
    exit 127
  fi
done

echo "[nohardware-tcp] Main Movement helper accepts primary routing only"
"${MAIN_PY}" -m pytest -q "${ROOT_DIR}/tests/nohardware/test_main_movement_client_contract.py"

if [[ ! -f "${ROS_SETUP}" ]]; then
  echo "[nohardware-tcp] missing ROS setup ${ROS_SETUP}" >&2
  exit 127
fi
# ROS setup scripts commonly expand unset variables.  Temporarily disable
# nounset so this smoke remains strict without making the source operation
# fragile.
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
with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
    s.bind(("127.0.0.1", 0))
    print(s.getsockname()[1])
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

cleanup() {
  local status=$?
  for pid in ${NAV_PID:-} ${AI_PID:-}; do
    if [[ -n "${pid}" ]] && kill -0 "${pid}" 2>/dev/null; then
      kill "${pid}" 2>/dev/null || true
    fi
  done
  for pid in ${NAV_PID:-} ${AI_PID:-}; do
    if [[ -n "${pid}" ]]; then
      wait "${pid}" 2>/dev/null || true
    fi
  done
  if [[ -n "${LOG_DIR:-}" && -d "${LOG_DIR}" ]]; then
    if [[ ${status} -ne 0 ]]; then
      echo "[nohardware-tcp] logs retained: ${LOG_DIR}" >&2
      for f in "${LOG_DIR}"/*.log; do
        [[ -f "${f}" ]] || continue
        echo "--- ${f} ---" >&2
        tail -120 "${f}" >&2 || true
      done
    else
      rm -rf "${LOG_DIR}"
    fi
  fi
  exit "${status}"
}
trap cleanup EXIT INT TERM

LOG_DIR="$(mktemp -d /tmp/nohardware-tcp.XXXXXX)"
NAV_PORT="$(pick_port)"
AI_PORT="$(pick_port)"
NAV_BASE="http://127.0.0.1:${NAV_PORT}"
AI_BASE="http://127.0.0.1:${AI_PORT}"
# Fixed, test-only Main↔Nav secret. It is scoped to the subprocesses below.
NOHARDWARE_HMAC_SECRET="nohardware-main-nav-hmac-v1"
# Main↔AI mutations are fail-closed. Generate one test-run credential and pass
# the same value to both sides without ever emitting it. Allow the operator
# preflight to provide its ephemeral value to this child process.
NOHARDWARE_VISION_HMAC_SECRET="${LMS_VISION_HMAC_SECRET:-}"
if [[ -z "${NOHARDWARE_VISION_HMAC_SECRET}" ]]; then
  NOHARDWARE_VISION_HMAC_SECRET="$("${AI_PY}" -c 'import secrets; print(secrets.token_urlsafe(32))')"
fi
# Keep the ROS-gateway credential distinct from Main↔AI mutation signing, even
# in the in-process test deployment. operator-preflight may supply this value.
NOHARDWARE_VISION_GATEWAY_HMAC_SECRET="${VISION_GATEWAY_HMAC_SECRET:-}"
if [[ -z "${NOHARDWARE_VISION_GATEWAY_HMAC_SECRET}" ]]; then
  NOHARDWARE_VISION_GATEWAY_HMAC_SECRET="$("${AI_PY}" -c 'import secrets; print(secrets.token_urlsafe(32))')"
fi

echo "[nohardware-tcp] starting actual Nav runtime on ${NAV_BASE}"
(
  cd "${ROOT_DIR}"
  PYTHONPATH="${ROOT_DIR}/nav-server:${ROOT_DIR}/nav-server/scripts${PYTHONPATH:+:${PYTHONPATH}}" \
  ROBOT_ID="tb3_burger_01" \
  ROS_DOMAIN_ID="2" \
  ROS_LOCALHOST_ONLY="1" \
  ROBOTS_CONFIG_PATH="${ROOT_DIR}/nav-server/config/robots.nohardware.json" \
  MAIN_SERVER_ROUTES_PATH="${ROOT_DIR}/nav-server/config/main_server_routes.json" \
  ACTIVE_MAP_YAML="${ROOT_DIR}/nav-server/map/robot1_map.yaml" \
  SIMULATION_MODE="1" \
  DRY_RUN_MISSION="1" \
  MAIN_API_BASE="disabled" \
  NAV_MAIN_HMAC_SECRET="${NOHARDWARE_HMAC_SECRET}" \
  MAIN_CALLBACK_TIMEOUT_SEC="0.2" \
  SIMULATED_STEP_DELAY_SEC="0.01" \
  "${NAV_PY}" -m uvicorn nav_app.app:app --host 127.0.0.1 --port "${NAV_PORT}" --log-level warning
) >"${LOG_DIR}/nav.log" 2>&1 &
NAV_PID=$!
wait_http "${NAV_BASE}/movement-api/v1/health" 20 "${NAV_PY}" >/dev/null

echo "[nohardware-tcp] Main HttpMovementClient -> Nav POST /robot-commands + GET /robot-commands/{id}"
(
  cd "${ROOT_DIR}/main-server/backend"
  LMS_MOVEMENT_BASE_URL="${NAV_BASE}/movement-api/v1" \
  LMS_MOVEMENT_BASE_URLS="tb3_1=${NAV_BASE}/movement-api/v1" \
  LMS_MOVEMENT_HMAC_SECRET="${NOHARDWARE_HMAC_SECRET}" \
  "${MAIN_PY}" "${ROOT_DIR}/tests/nohardware/check_main_movement_tcp.py" --base "${NAV_BASE}/movement-api/v1"
)

echo "[nohardware-tcp] starting AI app.main:app on ${AI_BASE}"
(
  cd "${ROOT_DIR}/ai-server"
  MAIN_HMAC_SECRET="${NOHARDWARE_VISION_HMAC_SECRET}" \
  VISION_GATEWAY_HMAC_SECRET="${NOHARDWARE_VISION_GATEWAY_HMAC_SECRET}" \
  NOHARDWARE_AI_PORT="${AI_PORT}" \
  PYTHONPATH="${ROOT_DIR}/ai-server:${ROOT_DIR}${PYTHONPATH:+:${PYTHONPATH}}" \
  "${AI_PY}" "${ROOT_DIR}/tests/nohardware/serve_ai_person_fixture.py"
) >"${LOG_DIR}/ai.log" 2>&1 &
AI_PID=$!
wait_http "${AI_BASE}/api/v1/health" 30 "${AI_PY}" >/dev/null

echo "[nohardware-tcp] signed vision gateway frame ingress accepts configured credential and rejects unsigned ingress"
"${AI_PY}" "${ROOT_DIR}/tests/nohardware/check_ai_gateway_frame_tcp.py" \
  --base "${AI_BASE}" --secret "${NOHARDWARE_VISION_GATEWAY_HMAC_SECRET}"

echo "[nohardware-tcp] Main vision_proxy.fetch_stream_transports + post_lift_load_evaluate -> AI endpoints"
(
  cd "${ROOT_DIR}/main-server/backend"
  LMS_VISION_HMAC_SECRET="${NOHARDWARE_VISION_HMAC_SECRET}" \
  "${MAIN_PY}" "${ROOT_DIR}/tests/nohardware/check_main_vision_tcp.py" --base "${AI_BASE}"
)

echo "[nohardware-tcp] signed AI person advisory -> Main trusted stop/hold -> signed Nav E-stop -> clear/recovery"
# The person client uses Nav's root compatibility E-stop routes; the versioned
# health endpoint is asserted by the checker after each mutation.
(
  cd "${ROOT_DIR}/main-server/backend"
  LMS_PERSON_HAZARD_ENABLED=true \
  LMS_MOVEMENT_BASE_URL="${NAV_BASE}" \
  LMS_MOVEMENT_BASE_URLS="tb3_1=${NAV_BASE}" \
  LMS_MOVEMENT_HMAC_SECRET="${NOHARDWARE_HMAC_SECRET}" \
  LMS_VISION_API_BASE_URL="${AI_BASE}" \
  LMS_VISION_API_FALLBACK_BASE_URL="" \
  LMS_VISION_HMAC_SECRET="${NOHARDWARE_VISION_HMAC_SECRET}" \
  LMS_VISION_TIMEOUT_SEC="3.0" \
  LMS_PERSON_HAZARD_TIMEOUT_SEC="1.0" \
  "${MAIN_PY}" "${ROOT_DIR}/tests/nohardware/check_person_hazard_tcp.py" --ai-base "${AI_BASE}" --nav-base "${NAV_BASE}/movement-api/v1"
)

# The checker above validates the returned stream contract through Main's real
# HTTP client. The fixture wrapper intentionally suppresses access logs, so do
# not make test success depend on a log-line format.
echo "[nohardware-tcp] observed AI stream discovery through Main HTTP client"

# Start every enabled profile once.  The first Nav process above owns the
# command-composition smoke; these independent profile boots prove each enabled
# robot's declared map is usable in the isolated simulation runtime.
echo "[nohardware-tcp] boot/smoke every enabled robot map and reject mismatched map metadata"
while IFS=$'\t' read -r robot_id bridge_robot_id ros_domain_id active_map_yaml; do
  [[ -n "${robot_id}" ]] || continue
  map_port="$(pick_port)"
  map_base="http://127.0.0.1:${map_port}"
  map_yaml_path="${ROOT_DIR}/nav-server/${active_map_yaml}"
  map_log="${LOG_DIR}/nav-${robot_id}.log"
  (
    cd "${ROOT_DIR}"
    PYTHONPATH="${ROOT_DIR}/nav-server:${ROOT_DIR}/nav-server/scripts${PYTHONPATH:+:${PYTHONPATH}}" \
    ROBOT_ID="${robot_id}" \
    ROS_DOMAIN_ID="${ros_domain_id}" \
    ROS_LOCALHOST_ONLY="1" \
    ROBOTS_CONFIG_PATH="${ROOT_DIR}/nav-server/config/robots.nohardware.json" \
    MAIN_SERVER_ROUTES_PATH="${ROOT_DIR}/nav-server/config/main_server_routes.json" \
    ACTIVE_MAP_YAML="${map_yaml_path}" \
    SIMULATION_MODE="1" \
    DRY_RUN_MISSION="1" \
    MAIN_API_BASE="disabled" \
    NAV_MAIN_HMAC_SECRET="${NOHARDWARE_HMAC_SECRET}" \
    MAIN_CALLBACK_TIMEOUT_SEC="0.2" \
    SIMULATED_STEP_DELAY_SEC="0.01" \
    "${NAV_PY}" -m uvicorn nav_app.app:app --host 127.0.0.1 --port "${map_port}" --log-level warning
  ) >"${map_log}" 2>&1 &
  map_pid=$!
  wait_http "${map_base}/movement-api/v1/health" 20 "${NAV_PY}" >/dev/null
  "${NAV_PY}" "${ROOT_DIR}/tests/nohardware/check_enabled_robot_maps_tcp.py" \
    --base "${map_base}" --robot-id "${robot_id}" --bridge-robot-id "${bridge_robot_id}" --map-yaml "${map_yaml_path}" \
    --robots-config "${ROOT_DIR}/nav-server/config/robots.nohardware.json"
  kill "${map_pid}" 2>/dev/null || true
  wait "${map_pid}" 2>/dev/null || true
done < <(
  "${NAV_PY}" - "${ROOT_DIR}/nav-server/config/robots.nohardware.json" <<'PY'
import json
import sys
for robot in json.load(open(sys.argv[1], encoding="utf-8"))["robots"]:
    if robot.get("enabled"):
        print("\t".join(str(robot[key]) for key in ("robot_id", "bridge_robot_id", "ros_domain_id", "active_map_yaml")))
PY
)

echo "[nohardware-tcp] PASSED"
