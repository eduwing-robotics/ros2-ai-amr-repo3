#!/usr/bin/env bash
#
# Show whether the two Nav server API processes are alive and reachable.

set -euo pipefail

detect_nav_pc_ip() {
  local detected
  detected="$(hostname -I 2>/dev/null | tr ' ' '\n' | awk '/^192\.168\.10\./ { print; exit }')"
  if [[ -n "$detected" ]]; then
    echo "$detected"
  else
    echo "127.0.0.1"
  fi
}

NAV_PC_IP="${NAV_PC_IP:-$(detect_nav_pc_ip)}"
TB3_1_PORT="${TB3_1_PORT:-8001}"
TB3_2_PORT="${TB3_2_PORT:-8002}"
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"

check_http() {
  local label="$1"
  local port="$2"
  local expected_robot="$3"
  local url="http://${NAV_PC_IP}:${port}/movement-api/v1/health"
  local body

  if body="$(curl -fsS --max-time 2 "$url" 2>/dev/null)"; then
    echo "[OK] ${label} API alive: ${url}"
    BODY="$body" EXPECTED_ROBOT="$expected_robot" python3 - <<'PY'
import json
import os

body = os.environ["BODY"]
expected = os.environ["EXPECTED_ROBOT"]
data = json.loads(body)
robot = data.get("robot_name")
dry_run = data.get("dry_run")
domain = data.get("ros_domain_id")
status = "OK" if robot == expected else "WARN"
print(f"     robot_name={robot} expected={expected} ros_domain_id={domain} dry_run={dry_run} [{status}]")
PY
  else
    echo "[FAIL] ${label} API not reachable: ${url}"
  fi
}

check_processes() {
  echo
  echo "== Processes =="
  if pgrep -af "uvicorn nav_app.app:app" >/dev/null; then
    pgrep -af "uvicorn nav_app.app:app" | sed 's/^/  /'
  else
    echo "  [FAIL] no uvicorn nav_app.app process found"
  fi
}

check_cmd_vel() {
  local label="$1"
  local domain="$2"

  if [[ ! -f "$ROS_SETUP" ]]; then
    echo "[SKIP] ${label} /cmd_vel: missing ROS setup: $ROS_SETUP"
    return
  fi

  echo
  echo "== ${label} /cmd_vel (ROS_DOMAIN_ID=${domain}) =="
  set +u
  # shellcheck source=/dev/null
  source "$ROS_SETUP"
  set -u
  ROS_DOMAIN_ID="$domain" ROS_LOCALHOST_ONLY=0 timeout 3 ros2 topic info /cmd_vel -v \
    | awk '
      /Type:/ || /Publisher count:/ || /Subscription count:/ || /Node name:/ {
        print "  " $0
      }
    ' || echo "  [WARN] ros2 topic info failed"
}

echo "== Nav Server HTTP =="
echo "Using NAV_PC_IP=${NAV_PC_IP} (override with NAV_PC_IP=... scripts/nav_server_status.sh)"
check_http "robot1" "$TB3_1_PORT" "tb3_1"
check_http "robot2" "$TB3_2_PORT" "tb3_2"

check_processes
check_cmd_vel "robot1" 2
check_cmd_vel "robot2" 5

echo
echo "정상 기준:"
echo "- HTTP 둘 다 [OK]"
echo "- dry_run=false이면 실제 이동 모드, dry_run=true이면 API 테스트 모드"
echo "- /cmd_vel Subscription count가 1 이상이면 로봇 구동 노드가 명령을 듣는 상태"
