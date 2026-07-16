#!/usr/bin/env bash
# Read-only operator preflight.  It never starts services or commands robot motion.
set -u -o pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# shellcheck source=/dev/null
source "$ROOT_DIR/scripts/lib/site_credentials.sh"
MODE=""
JSON_OUTPUT=0
FAILED=0
NOHARDWARE_FAILED=0
SITE_CREDENTIALS_READY=0
SITE_CREDENTIAL_SET_ID=""
SITE_CREDENTIAL_SOURCE="production bundle"
RESULTS_FILE="$(mktemp)"
trap 'rm -f "$RESULTS_FILE"' EXIT

usage() {
  cat <<'EOF'
Usage: scripts/operator-preflight.sh [--software|--nohardware|--hardware-checklist] [--json]

Read-only operator preflight. It does not start services, publish ROS messages,
or command motion (no motion). Choose exactly one mode:
  --software            Validate service venvs, ROS/Nav configuration, secrets,
                        Docker, maps/configuration, and reserved ports.
  --nohardware          Run --software, then scripts/test-nohardware.sh.
  --hardware-checklist  Run --software, then bounded read-only ROS/HTTP health checks.
  --json                Write a machine-readable summary to stdout (logs go to stderr).
  -h, --help            Show this help.

Exit codes: 0 PASS, 2 usage error, 3 preflight failure, 4 no-hardware suite failure.
Next command: scripts/operator-preflight.sh --software

Environment overrides: ROS_SETUP, OPERATOR_PREFLIGHT_REQUIRED_PORTS,
OPERATOR_PREFLIGHT_AI_HEALTH_URL, OPERATOR_PREFLIGHT_TIMEOUT_SEC.
Production HMAC values are loaded from .secrets/service-hmac.env and never printed.
--nohardware creates process-local Movement, Main↔AI, and vision-gateway test secrets.
EOF
}

log() {
  if [[ "$JSON_OUTPUT" -eq 1 ]]; then printf '%s\n' "$*" >&2; else printf '%s\n' "$*"; fi
}

record() {
  local status="$1" name="$2" message="$3"
  printf '%s\t%s\t%s\n' "$status" "$name" "$message" >>"$RESULTS_FILE"
  log "[${status}] ${name}: ${message}"
  [[ "$status" == "PASS" ]] || FAILED=1
}

run_check() {
  local name="$1" message="$2"
  shift 2
  if "$@" >/dev/null 2>&1; then record PASS "$name" "$message"; else record FAIL "$name" "$message"; fi
}

require_path() {
  local name="$1" path="$2"
  if [[ -f "$path" ]]; then record PASS "$name" "present"; else record FAIL "$name" "missing required file"; fi
}

check_venvs() {
  local service venv python
  for service in ai-server main-server nav-server; do
    venv="$ROOT_DIR/$service/.venv"
    python="$venv/bin/python"
    if [[ ! -x "$python" || ! -x "$venv/bin/pip" ]]; then
      record FAIL "venv_${service}" "missing service venv executable or pip"
      continue
    fi
    record PASS "venv_${service}" "executables present"
    run_check "pip_${service}" "pip dependency check passed" "$python" -m pip check
  done
}

check_ros_and_nav() {
  local ros_setup="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
  if [[ ! -f "$ros_setup" ]]; then
    record FAIL ros_setup "ROS setup file is missing"
    record FAIL ros2 "ros2 cannot be checked without ROS setup"
    record FAIL nav_config "Nav config --check cannot run without ROS setup"
    return
  fi
  if (set +u; source "$ros_setup"; command -v ros2 >/dev/null 2>&1); then
    record PASS ros_setup "ROS setup sourced"
    record PASS ros2 "ros2 command available"
  else
    record FAIL ros_setup "ROS setup could not be sourced"
    record FAIL ros2 "ros2 command unavailable after ROS setup"
  fi
  if (cd "$ROOT_DIR/nav-server" && ROS_SETUP="$ros_setup" ./scripts/run_nav_servers.sh --check) >/dev/null 2>&1; then
    record PASS nav_config "Nav config --check passed"
  else
    record FAIL nav_config "Nav config --check failed"
  fi
}

check_static_configuration() {
  run_check field_config "field configuration audit passed" "$ROOT_DIR/scripts/test-nohardware-config.sh"
  local path
  for path in nav-server/config/robots.json nav-server/config/main_server_routes.json nav-server/map/robot1_map.yaml nav-server/map/robot2_map.yaml nav-server/map/robot1_map.pgm nav-server/map/robot2_map.pgm; do
    require_path "required_${path//\//_}" "$ROOT_DIR/$path"
  done
}

check_hmac_secret() {
  if [[ "$SITE_CREDENTIALS_READY" -ne 1 ]]; then
    record FAIL site_credential_bundle "production credential bundle is missing, invalid, or conflicts with local service environment"
    record FAIL movement_hmac_secret "Movement HMAC pair is unavailable because the credential bundle did not load"
    record FAIL vision_hmac_secret "Vision HMAC pair is unavailable because the credential bundle did not load"
    record FAIL vision_gateway_hmac_secret "Vision gateway HMAC is unavailable because the credential bundle did not load"
    return
  fi
  record PASS site_credential_bundle "${SITE_CREDENTIAL_SOURCE} credential set ${SITE_CREDENTIAL_SET_ID} loaded (values hidden)"
  if [[ -n "${NAV_MAIN_HMAC_SECRET:-}" || -n "${LMS_MOVEMENT_HMAC_SECRET:-}" ]]; then
    record PASS movement_hmac_secret "Movement HMAC secret is present (value not displayed)"
  else
    record FAIL movement_hmac_secret "credential bundle loaded without the required Movement HMAC pair"
  fi
  if [[ -n "${MAIN_HMAC_SECRET:-}" || -n "${LMS_VISION_HMAC_SECRET:-}" ]]; then
    record PASS vision_hmac_secret "Vision HMAC secret is present (value not displayed)"
  else
    record FAIL vision_hmac_secret "credential bundle loaded without the required Vision HMAC pair"
  fi
  if [[ -n "${VISION_GATEWAY_HMAC_SECRET:-}" ]]; then
    record PASS vision_gateway_hmac_secret "Vision gateway HMAC secret is present (value not displayed)"
  else
    record FAIL vision_gateway_hmac_secret "credential bundle loaded without the required Vision gateway HMAC credential"
  fi
}

set_nohardware_vision_secret() {
  # Keep these credentials entirely inside the preflight/no-hardware subprocess
  # tree. test-nohardware-tcp.sh uses isolated Movement and Main↔AI credentials
  # and separately signs frame ingress with the gateway-only credential.
  local movement_secret vision_secret gateway_secret
  movement_secret="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  vision_secret="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  gateway_secret="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
  export NAV_MAIN_HMAC_SECRET="$movement_secret"
  export LMS_MOVEMENT_HMAC_SECRET="$movement_secret"
  export LMS_VISION_HMAC_SECRET="$vision_secret"
  export MAIN_HMAC_SECRET="$vision_secret"
  export VISION_GATEWAY_HMAC_SECRET="$gateway_secret"
  SITE_CREDENTIALS_READY=1
  SITE_CREDENTIAL_SET_ID="ephemeral-nohardware"
  SITE_CREDENTIAL_SOURCE="process-local"
}

check_docker() {
  if ! command -v docker >/dev/null 2>&1; then record FAIL docker "docker command is unavailable"; return; fi
  run_check docker "Docker daemon is available" docker info
}

check_ports() {
  local ports="${OPERATOR_PREFLIGHT_REQUIRED_PORTS:-8000,8001,8002,8088}" port listeners=""
  if ! command -v ss >/dev/null 2>&1; then record FAIL ports "ss command is unavailable"; return; fi
  listeners="$(ss -H -ltn 2>/dev/null || true)"
  IFS=',' read -r -a port_list <<<"$ports"
  for port in "${port_list[@]}"; do
    port="${port//[[:space:]]/}"
    [[ -z "$port" ]] && continue
    if grep -Eq "[:.]${port}[[:space:]]" <<<"$listeners"; then
      record FAIL "port_${port}" "reserved port is already listening"
    else
      record PASS "port_${port}" "reserved port is free"
    fi
  done
}

software_preflight() {
  check_venvs
  check_ros_and_nav
  check_static_configuration
  check_hmac_secret
  check_docker
  check_ports
}

ros_read_once() {
  local name="$1" domain="$2" topic="$3" timeout_sec="$4"
  if ROS_DOMAIN_ID="$domain" timeout "$timeout_sec" ros2 topic echo "$topic" --once >/dev/null 2>&1; then
    record PASS "$name" "received one message"
  else
    record FAIL "$name" "no message received within ${timeout_sec}s"
  fi
}

hardware_checklist() {
  local timeout_sec="${OPERATOR_PREFLIGHT_TIMEOUT_SEC:-5}"
  local row robot bridge domain center camera lift_enabled
  while IFS=$'\t' read -r robot bridge domain center camera lift_enabled; do
    ros_read_once "${robot}_scan" "$domain" /scan "$timeout_sec"
    ros_read_once "${robot}_odom" "$domain" /odom "$timeout_sec"
    ros_read_once "${robot}_tf" "$domain" /tf "$timeout_sec"
    ros_read_once "${robot}_camera" "$center" "$camera" "$timeout_sec"
    if [[ "$lift_enabled" == "true" ]]; then
      ros_read_once "${robot}_lift_position" "$domain" /lift/position "$timeout_sec"
      ros_read_once "${robot}_lift_direction" "$domain" /lift/direction "$timeout_sec"
      ros_read_once "${robot}_lift_limit_lower" "$domain" /lift/limit_lower "$timeout_sec"
    fi
  done < <(python3 - "$ROOT_DIR/nav-server/config/robots.json" <<'PY'
import json, sys
for robot in json.load(open(sys.argv[1], encoding="utf-8"))["robots"]:
    if robot.get("enabled", True):
        print("\t".join(map(str, (robot["robot_id"], robot["bridge_robot_id"], robot["ros_domain_id"], robot["center_domain_id"], robot["camera_topic"], str(robot.get("lift", {}).get("enabled", False)).lower()))))
PY
)

  while IFS=$'\t' read -r robot url; do
    if curl -fsS --connect-timeout 2 --max-time "$timeout_sec" "$url/movement-api/v1/health" 2>/dev/null | python3 -c 'import json,sys; d=json.load(sys.stdin); raise SystemExit(0 if d.get("nav2_ready") and d.get("localized") else 1)'; then
      record PASS "${robot}_nav_localization" "Nav health reports nav2_ready and localized"
    else
      record FAIL "${robot}_nav_localization" "Nav health/localization is unavailable or not ready"
    fi
  done < <(python3 - "$ROOT_DIR/nav-server/config/main_server_routes.json" <<'PY'
import json, sys
for robot in json.load(open(sys.argv[1], encoding="utf-8"))["robots"]:
    print(f'{robot["robot_id"]}\t{robot["nav_api_url"]}')
PY
)

  local ai_url="${OPERATOR_PREFLIGHT_AI_HEALTH_URL:-http://127.0.0.1:8000/api/v1/health}"
  if curl -fsS --connect-timeout 2 --max-time "$timeout_sec" "$ai_url" >/dev/null 2>&1; then
    record PASS ai_health "AI health endpoint is reachable"
  else
    record FAIL ai_health "AI health endpoint is unavailable"
  fi
}

emit_json() {
  python3 - "$RESULTS_FILE" "$MODE" "$FAILED" <<'PY'
import json, sys
checks = []
for line in open(sys.argv[1], encoding="utf-8"):
    status, name, message = line.rstrip("\n").split("\t", 2)
    checks.append({"name": name, "status": status, "message": message})
print(json.dumps({"mode": sys.argv[2], "ok": sys.argv[3] == "0", "checks": checks, "next_command": "scripts/operator-preflight.sh --software"}, ensure_ascii=False))
PY
}

while (($#)); do
  case "$1" in
    --software|--nohardware|--hardware-checklist)
      if [[ -n "$MODE" ]]; then usage >&2; exit 2; fi
      MODE="$1"
      ;;
    --json) JSON_OUTPUT=1 ;;
    -h|--help) usage; exit 0 ;;
    *) printf 'unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
[[ -n "$MODE" ]] || { usage >&2; exit 2; }

if [[ "$MODE" == "--nohardware" ]]; then
  set_nohardware_vision_secret
elif sf_load_site_credentials "$ROOT_DIR"; then
  SITE_CREDENTIALS_READY=1
  SITE_CREDENTIAL_SET_ID="$(sf_site_credentials_id "$ROOT_DIR")"
fi

software_preflight
case "$MODE" in
  --nohardware)
    if "$ROOT_DIR/scripts/test-nohardware.sh" >/dev/null 2>&1; then
      record PASS nohardware_suite "existing no-hardware suite passed"
    else
      NOHARDWARE_FAILED=1
      record FAIL nohardware_suite "existing no-hardware suite failed"
    fi
    ;;
  --hardware-checklist) hardware_checklist ;;
esac

if [[ "$JSON_OUTPUT" -eq 1 ]]; then emit_json; else log "Next command: scripts/operator-preflight.sh --software"; fi
if [[ "$FAILED" -ne 0 ]]; then
  [[ "$NOHARDWARE_FAILED" -eq 1 ]] && exit 4
  exit 3
fi
exit 0
