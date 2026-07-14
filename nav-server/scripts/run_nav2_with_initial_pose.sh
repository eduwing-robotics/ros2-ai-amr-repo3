#!/usr/bin/env bash
#
# Launch Nav2 for one robot and localize it from an arbitrary start pose.
#
# The default workflow is:
#   1) start the robot bringup
#   2) launch navigation2.launch.py
#   3) run observe-only map-wide localization
#
# Explicit coordinates remain available only as a manual recovery path.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
TURTLEBOT3_SETUP="${TURTLEBOT3_SETUP:?TURTLEBOT3_SETUP must point to the TurtleBot3 overlay setup.bash}"
MAP_YAML="${MAP_YAML:-$ROOT/map/robot2_map.yaml}"
NAV2_PARAMS_FILE="${NAV2_PARAMS_FILE:-$ROOT/config/nav2/burger_smartfactory.yaml}"
EKF_PARAMS_FILE="${EKF_PARAMS_FILE:-$ROOT/config/robot_localization/ekf_tb3_burger.yaml}"
WITH_EKF="${WITH_EKF:-0}"
TURTLEBOT3_MODEL="${TURTLEBOT3_MODEL:-burger}"
INITIAL_POSE_DELAY_SEC="${INITIAL_POSE_DELAY_SEC:-8}"
INITIAL_POSE_REPEAT_SEC="${INITIAL_POSE_REPEAT_SEC:-6}"
NAV2_STARTUP_RETRY_SEC="${NAV2_STARTUP_RETRY_SEC:-180}"
ROBOT_READINESS_TIMEOUT_SEC="${ROBOT_READINESS_TIMEOUT_SEC:-30}"
ROBOT_SCAN_MAX_AGE_SEC="${ROBOT_SCAN_MAX_AGE_SEC:-1.0}"
ROS_LOCALHOST_ONLY="${ROS_LOCALHOST_ONLY:-0}"
AUTOMATIC_LOCALIZATION_TIMEOUT_SEC="${AUTOMATIC_LOCALIZATION_TIMEOUT_SEC:-}"
AUTOMATIC_LOCALIZATION_API_TIMEOUT_SEC="${AUTOMATIC_LOCALIZATION_API_TIMEOUT_SEC:-30}"
AUTOMATIC_LOCALIZATION_REFINEMENT_GRACE_SEC="${AUTOMATIC_LOCALIZATION_REFINEMENT_GRACE_SEC:-}"
AUTOMATIC_LOCALIZATION_MAX_REFINEMENT_EXTENSIONS="${AUTOMATIC_LOCALIZATION_MAX_REFINEMENT_EXTENSIONS:-3}"
NAV2_USE_RVIZ="${NAV2_USE_RVIZ:-1}"
RVIZ_CONFIG_FILE="${RVIZ_CONFIG_FILE:-$ROOT/config/rviz/agv_map_debug.rviz}"
RMW_IMPLEMENTATION="${RMW_IMPLEMENTATION:-rmw_cyclonedds_cpp}"
ROBOTS_CONFIG_PATH="${ROBOTS_CONFIG_PATH:-$ROOT/config/robots.json}"

ROBOT_NAME="tb3_2"
ROS_DOMAIN_ID_VALUE=""
NAV_LOCAL_ROS_DOMAIN_ID_VALUE="${NAV_LOCAL_ROS_DOMAIN_ID:-}"
INITIAL_X=""
INITIAL_Y=""
INITIAL_YAW=""

usage() {
  cat <<'EOF'
Usage:
  scripts/run_nav2_with_initial_pose.sh [options]

Options:
  --robot NAME        Robot bridge name. Default: tb3_2
  --domain ID         ROS_DOMAIN_ID for the robot. Default: 5 for tb3_2, 2 for tb3_1
  --local-domain ID   DDS domain for Nav/API/RViz. Defaults to nav_local_domain_id or robot domain
  --map PATH          Nav2 map YAML. Default: map/robot2_map.yaml
  --params PATH       Nav2 params YAML. Default: config/nav2/burger_smartfactory.yaml
  --x VALUE           Initial pose X in map frame
  --y VALUE           Initial pose Y in map frame
  --yaw VALUE         Initial pose yaw in radians
  --delay SEC         Seconds to wait after launch before publishing initial pose. Default: 8
  --repeat SEC        Seconds to repeat initial pose publication. Default: 6
  --startup-retry SEC Seconds to retry Nav2 lifecycle startup after launch. Default: 180
  --with-ekf          Enable robot_localization EKF (wheel odom + IMU)
  --no-ekf            Disable EKF (default unless WITH_EKF=1)
  --rviz              Start one RViz process with the repository config (default)
  --no-rviz           Start Nav2 without RViz (diagnostics/headless operation)

Examples:
  scripts/run_nav2_with_initial_pose.sh --robot tb3_1 --domain 2 --local-domain 42
  scripts/run_nav2_with_initial_pose.sh --robot tb3_2 --domain 5 --x 1.2 --y 0.5 --yaw 1.57

If --x/--y/--yaw are omitted, the script starts observe-only global localization.
Explicit coordinates are a manual recovery path and must be supplied together.
EOF
}

default_domain_for_robot() {
  case "$1" in
    tb3_1) echo "2" ;;
    tb3_2) echo "5" ;;
    *)
      echo ""
      ;;
  esac
}

local_domain_for_robot() {
  python3 - "$ROBOTS_CONFIG_PATH" "$1" <<'PY'
import json
import sys

config_path, robot_name = sys.argv[1:]
with open(config_path, encoding="utf-8") as handle:
    robots = json.load(handle).get("robots", [])
for robot in robots:
    if robot.get("bridge_robot_id") == robot_name:
        print(robot.get("nav_local_domain_id", robot["ros_domain_id"]))
        raise SystemExit(0)
raise SystemExit(1)
PY
}

localization_wait_budgets_for_robot() {
  python3 - "$ROBOTS_CONFIG_PATH" "$1" <<'PY'
import json
import math
import sys

config_path, robot_name = sys.argv[1:]
with open(config_path, encoding="utf-8") as handle:
    robots = json.load(handle).get("robots", [])
for robot in robots:
    if robot.get("bridge_robot_id") != robot_name:
        continue
    localization = robot.get("localization") or {}
    search = localization.get("global_search") or {}
    convergence = float(localization.get("convergence_timeout_sec", 30.0))
    refinement = float(search.get("nomotion_update_timeout_sec", 120.0))
    print(math.ceil(convergence + 30.0), math.ceil(refinement + 15.0))
    raise SystemExit(0)
raise SystemExit(1)
PY
}

monitor_navigation_startup() {
  local deadline output
  deadline=$((SECONDS + NAV2_STARTUP_RETRY_SEC))

  while (( SECONDS < deadline )); do
    output="$(
      timeout 4 ros2 service call /lifecycle_manager_navigation/is_active \
        std_srvs/srv/Trigger "{}" 2>&1 || true
    )"

    if grep -Eq "success(=|:[[:space:]]*)[Tt]rue" <<<"$output"; then
      echo "[nav2_helper] navigation lifecycle already active"
      return 0
    fi

    sleep 4
  done

  echo "[nav2_helper] navigation lifecycle not active yet. Set 2D Pose Estimate in RViz, then retry Nav2 Goal." >&2
  return 1
}

localization_url() {
  local port
  case "$ROBOT_NAME" in
    tb3_1) port="${TB3_1_PORT:-8001}" ;;
    tb3_2) port="${TB3_2_PORT:-8002}" ;;
    *) echo "[nav2_helper] LOCALIZATION_FAILED: unknown robot API for ${ROBOT_NAME}" >&2; return 1 ;;
  esac
  printf '%s/robots/%s/localization\n' \
    "${MOVEMENT_API_URL:-http://127.0.0.1:${port}/movement-api/v1}" "$ROBOT_NAME"
}

expected_robot_id() {
  case "$ROBOT_NAME" in
    tb3_1) echo "tb3_burger_01" ;;
    tb3_2) echo "tb3_burger_02" ;;
    *) return 1 ;;
  esac
}

expected_map_id() {
  local map_name="${MAP_YAML##*/}"
  printf '%s\n' "${map_name%.yaml}"
}

sign_api_request() {
  local secret="$1"
  local endpoint="$2"
  local body="$3"
  python3 - "$secret" "$endpoint" "$body" <<'PY'
import hashlib
import hmac
import secrets
import sys
import time
from urllib.parse import urlsplit

secret, endpoint, body = sys.argv[1:]
parsed = urlsplit(endpoint)
path = parsed.path or "/"
if parsed.query:
    path = f"{path}?{parsed.query}"
timestamp = str(int(time.time()))
nonce = secrets.token_urlsafe(24)
body_hash = hashlib.sha256(body.encode()).hexdigest()
signed = "\n".join(("POST", path, timestamp, nonce, body_hash)).encode()
signature = hmac.new(secret.encode(), signed, hashlib.sha256).hexdigest()
print(timestamp, nonce, signature)
PY
}

trigger_observe_only_localization() {
  local url="$1"
  local endpoint="${url}/global-search"
  local body='{"strategy":"observe_only","allow_motion":false,"source":"nav_startup"}'
  local secret="${NAV_MAIN_HMAC_SECRET:-${LMS_MOVEMENT_HMAC_SECRET:-}}"
  local deadline payload timestamp nonce signature
  local accepted strategy motion_started robot_name robot_id ros_domain_id map_id reason

  if [[ -z "$secret" ]]; then
    echo "[nav2_helper] LOCALIZATION_FAILED: NAV_MAIN_HMAC_SECRET is required for automatic localization" >&2
    return 1
  fi

  deadline=$((SECONDS + AUTOMATIC_LOCALIZATION_API_TIMEOUT_SEC))
  echo "[nav2_helper] triggering automatic observe-only localization: ${endpoint}"
  while ((SECONDS < deadline)); do
    read -r timestamp nonce signature < <(sign_api_request "$secret" "$endpoint" "$body")
    payload="$(curl -fsS --max-time 2 \
      -X POST \
      -H 'Content-Type: application/json' \
      -H "X-SF-Timestamp: ${timestamp}" \
      -H "X-SF-Nonce: ${nonce}" \
      -H "X-SF-Signature: ${signature}" \
      --data-binary "$body" \
      "$endpoint" 2>/dev/null || true)"
    if [[ -n "$payload" ]]; then
      read -r accepted strategy motion_started robot_name robot_id ros_domain_id map_id reason < <(python3 -c '
import json, sys
data = json.load(sys.stdin)
search = data.get("search") or {}
localization = data.get("localization") or {}
print(
    str(bool(data.get("accepted"))).lower(),
    search.get("strategy", "unknown"),
    str(bool(search.get("motion_started"))).lower(),
    data.get("robot_name", "unknown"),
    data.get("robot_id", "unknown"),
    data.get("ros_domain_id", "unknown"),
    localization.get("map_id", "unknown"),
    search.get("reason", "unknown"),
)
' <<<"$payload" 2>/dev/null || echo "false unknown true unknown unknown unknown unknown invalid_response")
      if [[ "$accepted" == "true" \
        && "$strategy" == "observe_only" \
        && "$motion_started" == "false" \
        && "$robot_name" == "$ROBOT_NAME" \
        && "$robot_id" == "$(expected_robot_id)" \
        && "$ros_domain_id" == "$ROS_DOMAIN_ID_VALUE" \
        && "$map_id" == "$(expected_map_id)" ]]; then
        return 0
      fi
      if [[ "$accepted" == "false" \
        && "$strategy" == "observe_only" \
        && "$motion_started" == "false" \
        && "$robot_name" == "$ROBOT_NAME" \
        && "$robot_id" == "$(expected_robot_id)" \
        && "$ros_domain_id" == "$ROS_DOMAIN_ID_VALUE" \
        && "$map_id" == "$(expected_map_id)" ]]; then
        case "$reason" in
          global_localization_service_unavailable|nomotion_update_service_unavailable|previous_search_still_stopping)
            echo "[nav2_helper] localization services not ready yet: ${reason}; retrying"
            sleep 1
            continue
            ;;
        esac
      fi
      echo "[nav2_helper] LOCALIZATION_FAILED: observe-only trigger rejected or identity mismatch: ${reason}" >&2
      return 1
    fi
    sleep 1
  done
  echo "[nav2_helper] LOCALIZATION_FAILED: localization API trigger timeout" >&2
  return 1
}

request_manual_initial_pose() {
  local url="$1"
  local x="$2"
  local y="$3"
  local yaw="$4"
  local endpoint="${url%/localization}/initial-pose"
  local secret="${NAV_MAIN_HMAC_SECRET:-${LMS_MOVEMENT_HMAC_SECRET:-}}"
  local body deadline payload timestamp nonce signature
  local accepted robot_name robot_id ros_domain_id map_id

  if [[ -z "$secret" ]]; then
    echo "[nav2_helper] LOCALIZATION_FAILED: NAV_MAIN_HMAC_SECRET is required for manual recovery" >&2
    return 1
  fi
  body="$(python3 - "$x" "$y" "$yaw" <<'PY'
import json
import sys

x, y, yaw = (float(value) for value in sys.argv[1:])
print(json.dumps({
    "x": x,
    "y": y,
    "yaw": yaw,
    "frame_id": "map",
    "source": "nav_startup_manual_recovery",
}, separators=(",", ":")))
PY
  )"
  deadline=$((SECONDS + AUTOMATIC_LOCALIZATION_API_TIMEOUT_SEC))
  echo "[nav2_helper] requesting manual initial pose through Movement API: ${endpoint}"
  while ((SECONDS < deadline)); do
    read -r timestamp nonce signature < <(sign_api_request "$secret" "$endpoint" "$body")
    payload="$(curl -fsS --max-time 2 \
      -X POST \
      -H 'Content-Type: application/json' \
      -H "X-SF-Timestamp: ${timestamp}" \
      -H "X-SF-Nonce: ${nonce}" \
      -H "X-SF-Signature: ${signature}" \
      --data-binary "$body" \
      "$endpoint" 2>/dev/null || true)"
    if [[ -n "$payload" ]]; then
      read -r accepted robot_name robot_id ros_domain_id map_id < <(python3 -c '
import json, sys
data = json.load(sys.stdin)
localization = data.get("localization") or {}
print(
    str(bool(data.get("accepted"))).lower(),
    data.get("robot_name", "unknown"),
    data.get("robot_id", "unknown"),
    data.get("ros_domain_id", "unknown"),
    localization.get("map_id", "unknown"),
)
' <<<"$payload" 2>/dev/null || echo "false unknown unknown unknown unknown")
      if [[ "$accepted" == "true" \
        && "$robot_name" == "$ROBOT_NAME" \
        && "$robot_id" == "$(expected_robot_id)" \
        && "$ros_domain_id" == "$ROS_DOMAIN_ID_VALUE" \
        && "$map_id" == "$(expected_map_id)" ]]; then
        return 0
      fi
      echo "[nav2_helper] LOCALIZATION_FAILED: manual initial pose rejected or identity mismatch" >&2
      return 1
    fi
    sleep 1
  done
  echo "[nav2_helper] LOCALIZATION_FAILED: manual initial pose API timeout" >&2
  return 1
}

wait_for_localized_state() {
  local url="$1"
  local deadline hard_deadline payload state localized reason robot_name robot_id ros_domain_id map_id
  local refinement_attempts seen_refinement_attempts=0 extended_deadline
  deadline=$((SECONDS + AUTOMATIC_LOCALIZATION_TIMEOUT_SEC))
  hard_deadline=$((
    deadline
    + AUTOMATIC_LOCALIZATION_REFINEMENT_GRACE_SEC * AUTOMATIC_LOCALIZATION_MAX_REFINEMENT_EXTENSIONS
  ))
  echo "[nav2_helper] waiting for localization convergence: ${url}"
  while ((SECONDS < deadline)); do
    payload="$(curl -fsS --max-time 2 "$url" 2>/dev/null || true)"
    if [[ -n "$payload" ]]; then
      read -r state localized reason robot_name robot_id ros_domain_id map_id refinement_attempts < <(python3 -c '
import json, sys
data = json.load(sys.stdin)
alignment = data.get("scan_map_alignment") or {}
print(
    data.get("state", "UNKNOWN"),
    str(bool(data.get("localized"))).lower(),
    data.get("reason", "unknown"),
    data.get("robot_name", "unknown"),
    data.get("robot_id", "unknown"),
    data.get("ros_domain_id", "unknown"),
    data.get("map_id", "unknown"),
    alignment.get("attempts", 0),
)
' <<<"$payload" 2>/dev/null || echo "UNKNOWN false invalid_response unknown unknown unknown unknown 0")
      if [[ "$refinement_attempts" =~ ^[0-9]+$ ]] \
        && (( refinement_attempts > seen_refinement_attempts )); then
        seen_refinement_attempts="$refinement_attempts"
        extended_deadline=$((SECONDS + AUTOMATIC_LOCALIZATION_REFINEMENT_GRACE_SEC))
        (( extended_deadline > hard_deadline )) && extended_deadline="$hard_deadline"
        if (( extended_deadline > deadline )); then
          deadline="$extended_deadline"
          echo "[nav2_helper] extending convergence wait for scan-map refinement attempt ${refinement_attempts}"
        fi
      fi
      if [[ "$state" == "LOCALIZED" \
        && "$localized" == "true" \
        && "$robot_name" == "$ROBOT_NAME" \
        && "$robot_id" == "$(expected_robot_id)" \
        && "$ros_domain_id" == "$ROS_DOMAIN_ID_VALUE" \
        && "$map_id" == "$(expected_map_id)" ]]; then
        echo "[nav2_helper] automatic localization converged: state=${state} reason=${reason}"
        return 0
      fi
      if [[ "$state" == "FAILED" ]]; then
        echo "[nav2_helper] LOCALIZATION_FAILED: ${reason}" >&2
        return 1
      fi
    fi
    sleep 1
  done
  echo "[nav2_helper] LOCALIZATION_FAILED: automatic localization timeout" >&2
  return 1
}

wait_for_automatic_localization() {
  local url
  url="$(localization_url)"
  trigger_observe_only_localization "$url"
  wait_for_localized_state "$url"
}

wait_for_robot_readiness() {
  local deadline remaining output url payload ready reason request_timeout last_reason
  deadline=$((SECONDS + ROBOT_READINESS_TIMEOUT_SEC))
  url="$(localization_url)"
  last_reason="api_unavailable"

  echo "[nav2_helper] waiting for fresh robot scan through localization API: ${url}"
  while (( SECONDS < deadline )); do
    remaining=$((deadline - SECONDS))
    request_timeout=2
    (( remaining < request_timeout )) && request_timeout="$remaining"
    payload="$(curl -fsS --max-time "$request_timeout" "$url" 2>/dev/null || true)"
    if [[ -n "$payload" ]]; then
      read -r ready reason < <(python3 -c '
import json
import math
import sys

expected_name, expected_id, expected_domain, expected_map, max_age = sys.argv[1:]
try:
    data = json.load(sys.stdin)
    scan_age = float(data.get("scan_age_sec"))
    checks = (
        (data.get("robot_name") == expected_name, "robot_name_mismatch"),
        (data.get("robot_id") == expected_id, "robot_id_mismatch"),
        (str(data.get("ros_domain_id")) == expected_domain, "ros_domain_id_mismatch"),
        (data.get("map_id") == expected_map, "map_id_mismatch"),
        (data.get("robot_online") is True, "robot_offline"),
        (math.isfinite(scan_age) and 0.0 <= scan_age <= float(max_age), "scan_missing_or_stale"),
    )
    reason = next((reason for valid, reason in checks if not valid), "ready")
    print(str(reason == "ready").lower(), reason)
except (TypeError, ValueError, json.JSONDecodeError):
    print("false invalid_response")
' "$ROBOT_NAME" "$(expected_robot_id)" "$ROS_DOMAIN_ID_VALUE" "$(expected_map_id)" "$ROBOT_SCAN_MAX_AGE_SEC" <<<"$payload")
      last_reason="$reason"
      if [[ "$ready" == "true" ]]; then
        break
      fi
    fi
    sleep 1
  done
  if [[ "${ready:-false}" != "true" ]]; then
    echo "[nav2_helper] LOCALIZATION_FAILED: fresh /scan unavailable via localization API (${last_reason})" >&2
    return 1
  fi

  remaining=$((deadline - SECONDS))
  if (( remaining <= 0 )); then
    echo "[nav2_helper] LOCALIZATION_FAILED: odom -> base_footprint TF unavailable" >&2
    return 1
  fi
  # tf2_echo is a long-running diagnostic. Stop on the first valid transform
  # instead of consuming the whole readiness timeout on every healthy start.
  output="$(timeout "$remaining" bash -c '
    set -o pipefail
    ros2 run tf2_ros tf2_echo odom base_footprint 2>&1 | grep -m1 "Translation:"
  ' || true)"
  if ! grep -q "Translation:" <<<"$output"; then
    echo "[nav2_helper] LOCALIZATION_FAILED: odom -> base_footprint TF unavailable" >&2
    return 1
  fi
  echo "[nav2_helper] robot scan and odom TF ready"
}

while (($# > 0)); do
  case "$1" in
    --robot)
      ROBOT_NAME="${2:-}"
      shift 2
      ;;
    --domain)
      ROS_DOMAIN_ID_VALUE="${2:-}"
      shift 2
      ;;
    --local-domain)
      NAV_LOCAL_ROS_DOMAIN_ID_VALUE="${2:-}"
      shift 2
      ;;
    --map)
      MAP_YAML="${2:-}"
      shift 2
      ;;
    --params)
      NAV2_PARAMS_FILE="${2:-}"
      shift 2
      ;;
    --x)
      INITIAL_X="${2:-}"
      shift 2
      ;;
    --y)
      INITIAL_Y="${2:-}"
      shift 2
      ;;
    --yaw)
      INITIAL_YAW="${2:-}"
      shift 2
      ;;
    --delay)
      INITIAL_POSE_DELAY_SEC="${2:-}"
      shift 2
      ;;
    --repeat)
      INITIAL_POSE_REPEAT_SEC="${2:-}"
      shift 2
      ;;
    --startup-retry)
      NAV2_STARTUP_RETRY_SEC="${2:-}"
      shift 2
      ;;
    --with-ekf)
      WITH_EKF=1
      shift
      ;;
    --no-ekf)
      WITH_EKF=0
      shift
      ;;
    --rviz)
      NAV2_USE_RVIZ=1
      shift
      ;;
    --no-rviz)
      NAV2_USE_RVIZ=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "[nav2_helper] unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

if [[ -z "$ROS_DOMAIN_ID_VALUE" ]]; then
  ROS_DOMAIN_ID_VALUE="$(default_domain_for_robot "$ROBOT_NAME")"
fi

EXPECTED_ROS_DOMAIN_ID="$(default_domain_for_robot "$ROBOT_NAME")"
if [[ -z "$EXPECTED_ROS_DOMAIN_ID" ]]; then
  echo "[nav2_helper] unsupported robot identity: $ROBOT_NAME" >&2
  exit 2
fi
if [[ "$ROS_DOMAIN_ID_VALUE" != "$EXPECTED_ROS_DOMAIN_ID" ]]; then
  echo "[nav2_helper] robot/domain mismatch: ${ROBOT_NAME} requires ROS_DOMAIN_ID=${EXPECTED_ROS_DOMAIN_ID}, got ${ROS_DOMAIN_ID_VALUE}" >&2
  exit 2
fi
if [[ -z "$NAV_LOCAL_ROS_DOMAIN_ID_VALUE" ]]; then
  NAV_LOCAL_ROS_DOMAIN_ID_VALUE="$(local_domain_for_robot "$ROBOT_NAME")"
fi
if [[ ! "$NAV_LOCAL_ROS_DOMAIN_ID_VALUE" =~ ^[0-9]+$ ]] || (( NAV_LOCAL_ROS_DOMAIN_ID_VALUE > 232 )); then
  echo "[nav2_helper] invalid local ROS domain: ${NAV_LOCAL_ROS_DOMAIN_ID_VALUE}" >&2
  exit 2
fi

read -r profile_localization_timeout profile_refinement_grace < <(
  localization_wait_budgets_for_robot "$ROBOT_NAME"
)
if [[ -z "$AUTOMATIC_LOCALIZATION_TIMEOUT_SEC" ]]; then
  AUTOMATIC_LOCALIZATION_TIMEOUT_SEC="$profile_localization_timeout"
fi
if [[ -z "$AUTOMATIC_LOCALIZATION_REFINEMENT_GRACE_SEC" ]]; then
  AUTOMATIC_LOCALIZATION_REFINEMENT_GRACE_SEC="$profile_refinement_grace"
fi
for timeout_value in \
  "$AUTOMATIC_LOCALIZATION_TIMEOUT_SEC" \
  "$AUTOMATIC_LOCALIZATION_REFINEMENT_GRACE_SEC" \
  "$AUTOMATIC_LOCALIZATION_MAX_REFINEMENT_EXTENSIONS"; do
  if [[ ! "$timeout_value" =~ ^[1-9][0-9]*$ ]]; then
    echo "[nav2_helper] localization timeout budgets must be positive integers" >&2
    exit 2
  fi
done
echo "[nav2_helper] localization wait budget: base=${AUTOMATIC_LOCALIZATION_TIMEOUT_SEC}s refinement=${AUTOMATIC_LOCALIZATION_REFINEMENT_GRACE_SEC}s"

pose_arg_count=0
[[ -n "$INITIAL_X" ]] && ((pose_arg_count += 1))
[[ -n "$INITIAL_Y" ]] && ((pose_arg_count += 1))
[[ -n "$INITIAL_YAW" ]] && ((pose_arg_count += 1))
if (( pose_arg_count != 0 && pose_arg_count != 3 )); then
  echo "[nav2_helper] --x, --y, and --yaw must be supplied together for manual recovery" >&2
  exit 2
fi

if [[ -z "$ROS_DOMAIN_ID_VALUE" ]]; then
  echo "[nav2_helper] ROS domain is required for robot: $ROBOT_NAME" >&2
  exit 2
fi

if [[ ! -f "$ROS_SETUP" ]]; then
  echo "[nav2_helper] missing ROS setup: $ROS_SETUP" >&2
  exit 1
fi

if [[ ! -f "$TURTLEBOT3_SETUP" ]]; then
  echo "[nav2_helper] missing TurtleBot3 setup: $TURTLEBOT3_SETUP" >&2
  exit 1
fi

if [[ ! -f "$MAP_YAML" ]]; then
  echo "[nav2_helper] missing map yaml: $MAP_YAML" >&2
  exit 1
fi

if [[ "$WITH_EKF" == "1" && -z "${NAV2_PARAMS_FILE##*burger_smartfactory.yaml}" ]]; then
  NAV2_PARAMS_FILE="$ROOT/config/nav2/burger_smartfactory_ekf.yaml"
fi

if [[ ! -f "$NAV2_PARAMS_FILE" ]]; then
  echo "[nav2_helper] missing Nav2 params yaml: $NAV2_PARAMS_FILE" >&2
  exit 1
fi

if [[ "$NAV2_USE_RVIZ" == "1" && ! -f "$RVIZ_CONFIG_FILE" ]]; then
  echo "[nav2_helper] missing RViz config: $RVIZ_CONFIG_FILE" >&2
  exit 1
fi

if [[ "$WITH_EKF" == "1" && ! -f "$EKF_PARAMS_FILE" ]]; then
  echo "[nav2_helper] missing EKF params yaml: $EKF_PARAMS_FILE" >&2
  exit 1
fi

# shellcheck source=/dev/null
set +u
source "$ROS_SETUP"
source "$TURTLEBOT3_SETUP"
set -u
export TURTLEBOT3_MODEL
export ROS_DOMAIN_ID="$NAV_LOCAL_ROS_DOMAIN_ID_VALUE"
export NAV_LOCAL_ROS_DOMAIN_ID="$NAV_LOCAL_ROS_DOMAIN_ID_VALUE"
export ROS_LOCALHOST_ONLY
export RMW_IMPLEMENTATION

if [[ "$NAV_LOCAL_ROS_DOMAIN_ID_VALUE" != "$ROS_DOMAIN_ID_VALUE" ]]; then
  # Nav2/RViz discover only the same-PC bridge participant. They do not attach
  # every Nav2 endpoint directly to the robot SBC.
  # shellcheck source=configure_cyclonedds_local_domain.sh
  source "$SCRIPT_DIR/configure_cyclonedds_local_domain.sh"
else
  # Backward-compatible direct mode for profiles without a local bridge.
  # shellcheck source=configure_cyclonedds_lan.sh
  source "$SCRIPT_DIR/configure_cyclonedds_lan.sh"
fi

launch_pid=""
ekf_pid=""
rviz_pid=""

cleanup() {
  if [[ -n "$rviz_pid" ]]; then
    kill -TERM -- "-$rviz_pid" 2>/dev/null || true
    wait "$rviz_pid" 2>/dev/null || true
  fi
  if [[ -n "$launch_pid" ]]; then
    kill -TERM -- "-$launch_pid" 2>/dev/null || true
    wait "$launch_pid" 2>/dev/null || true
  fi
  if [[ -n "$ekf_pid" ]]; then
    kill -TERM -- "-$ekf_pid" 2>/dev/null || true
    wait "$ekf_pid" 2>/dev/null || true
  fi
}

trap cleanup EXIT INT TERM

cd "$ROOT"

if [[ "$WITH_EKF" == "1" ]]; then
  echo "[nav2_helper] launching EKF: params=${EKF_PARAMS_FILE}"
  setsid ros2 launch "$ROOT/launch/ekf_odom.launch.py" "params_file:=$EKF_PARAMS_FILE" &
  ekf_pid="$!"
  sleep 2
fi

echo "[nav2_helper] launching Nav2: robot=${ROBOT_NAME} hardware_domain=${ROS_DOMAIN_ID_VALUE} local_domain=${ROS_DOMAIN_ID} ekf=${WITH_EKF} map=${MAP_YAML} params=${NAV2_PARAMS_FILE}"
wait_for_robot_readiness
setsid ros2 launch nav2_bringup bringup_launch.py \
  map:="$MAP_YAML" \
  params_file:="$NAV2_PARAMS_FILE" \
  use_sim_time:=False \
  use_composition:=True &
launch_pid="$!"

if [[ "$NAV2_USE_RVIZ" == "1" ]]; then
  echo "[nav2_helper] launching RViz: config=${RVIZ_CONFIG_FILE}"
  setsid rviz2 -d "$RVIZ_CONFIG_FILE" &
  rviz_pid="$!"
fi

sleep "$INITIAL_POSE_DELAY_SEC"

if [[ -n "$INITIAL_X" && -n "$INITIAL_Y" && -n "$INITIAL_YAW" ]]; then
  localization_endpoint="$(localization_url)"
  request_manual_initial_pose "$localization_endpoint" "$INITIAL_X" "$INITIAL_Y" "$INITIAL_YAW"
  wait_for_localized_state "$localization_endpoint"
else
  wait_for_automatic_localization
fi

# Navigation activation needs a valid map -> base_link transform.  Publish the
# AMCL seed first, then perform lifecycle startup in the foreground so a failed
# activation cannot be hidden by an untracked background job.
monitor_navigation_startup
echo "[nav2_helper] navigation-ready: localization and lifecycle gates passed"

wait "$launch_pid"
