#!/usr/bin/env bash
#
# tb3_2 전체 스택 원샷 런처
#
# 한 번에 띄우는 것:
#   [로봇 SBC] bringup(odom/scan/TF) + lift_bridge + 카메라 (기본 ON, ssh)
#   [Nav PC]   Nav2+RViz / Movement API(:8002) / ArUco detector
#
# 사용법:
#   scripts/start_all_tb3_2.sh start        # terminator split (기본, 로봇 SBC 포함)
#   scripts/start_all_tb3_2.sh restart      # 이 로봇만 종료 후 재기동 (tb3_1 유지)
#   scripts/start_all_tb3_2.sh stop         # 이 로봇만 종료 (API :8002 / domain 5)
#   scripts/start_all_tb3_2.sh status       # 상태 점검
#   scripts/start_all_tb3_2.sh tmux       # tmux 모드
#   scripts/start_all_tb3_2.sh windows      # gnome-terminal 개별창
#
#   WITH_ROBOT=0 scripts/start_all_tb3_2.sh # 로봇 SBC ssh 생략 (SBC에서 직접 기동할 때)
#   WITH_LIFT=0 scripts/start_all_tb3_2.sh # lift_bridge pane 생략 (도킹만 테스트)
#   WITH_EKF=1 scripts/start_all_tb3_2.sh # 선택: robot_localization EKF (기본은 검증된 wheel odom TF)
#
# Lift env (SBC 경로):
#   WITH_LIFT=1 (기본)
#   LIFT_WS_SETUP=~/lift_project/ros2_ws/install/setup.bash
#   LIFT_SERIAL_PORT=   # 비우면 bridge 기본 by-id
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_VENV="${PROJECT_VENV:-$ROOT/venv}"
if [[ ! -x "$PROJECT_VENV/bin/python" && -x "/home/lucas/slam_nav_ws/venv/bin/python" ]]; then
  PROJECT_VENV="/home/lucas/slam_nav_ws/venv"
fi
ROBOT_SBC_DIR="$SCRIPT_DIR/robot_sbc"
LOG_DIR="${LOG_DIR:-$ROOT/logs}"
SESSION_MARKER="$LOG_DIR/tb3_2_stack.session"

SESSION="${SESSION:-tb3_2_stack}"
DOMAIN="${DOMAIN:-5}"
MAP="${MAP:-$ROOT/map/robot2_map.yaml}"
# 기본: 대기2 approach (대략 대기장). 완전 hold 삽입 후면 INIT_POSE=dock
# dock: 0.836 0.953 1.394
INIT_POSE="${INIT_POSE:-approach}"
if [[ "$INIT_POSE" == "dock" ]]; then
  INIT_X="${INIT_X:-0.836}"
  INIT_Y="${INIT_Y:-0.953}"
  INIT_YAW="${INIT_YAW:-1.394}"
else
  INIT_X="${INIT_X:-0.816}"
  INIT_Y="${INIT_Y:-0.006}"
  INIT_YAW="${INIT_YAW:-1.571}"
fi
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
ROS_NETWORK_SETUP="${ROS_NETWORK_SETUP:-$SCRIPT_DIR/setup_ros_robot_network_env.sh}"
export DISPLAY="${DISPLAY:-:1}"

# 기본: 로봇 SBC bringup/카메라/lift까지 ssh로 함께 기동
WITH_ROBOT="${WITH_ROBOT:-1}"
WITH_LIFT="${WITH_LIFT:-1}"
WITH_EKF="${WITH_EKF:-0}"
LIFT_WS_SETUP="${LIFT_WS_SETUP:-/home/musk/lift_project/ros2_ws/install/setup.bash}"
LIFT_SERIAL_PORT="${LIFT_SERIAL_PORT:-}"
TRAFFIC_COORDINATION_MODE="${TRAFFIC_COORDINATION_MODE:-legacy}"
TRAFFIC_DEPARTURE_STAGGER_SEC="${TRAFFIC_DEPARTURE_STAGGER_SEC:-4}"
TRAFFIC_SEGMENT_WAIT_TIMEOUT_SEC="${TRAFFIC_SEGMENT_WAIT_TIMEOUT_SEC:-300}"
TRAFFIC_SEGMENT_TTL_SEC="${TRAFFIC_SEGMENT_TTL_SEC:-900}"
LIFT_BRIDGE_PKG="${LIFT_BRIDGE_PKG:-lift_bridge}"
ROBOT_SSH="${ROBOT_SSH:-musk@192.168.30.102}"
ROBOT_USB="${ROBOT_USB:-/dev/serial/by-id/usb-ROBOTIS_OpenCR_Virtual_ComPort_in_FS_Mode_FFFFFFFEFFFF-if00}"
CAMERA_LAUNCH="${CAMERA_LAUNCH:-turtlebot3_bringup camera.launch.py}"
ROBOT_WS_SETUP="${ROBOT_WS_SETUP:-/home/musk/turtlebot3_ws/install/setup.bash}"
ROBOT_LDS_MODEL="${ROBOT_LDS_MODEL:-LDS-03}"
ROBOT_BRINGUP_WAIT_SEC="${ROBOT_BRINGUP_WAIT_SEC:-10}"
ROBOT_TOPIC_WAIT_SEC="${ROBOT_TOPIC_WAIT_SEC:-120}"
CAMERA_TOPIC_WAIT_SEC="${CAMERA_TOPIC_WAIT_SEC:-60}"
STATUS_DELAY_SEC="${STATUS_DELAY_SEC:-50}"
MODE="${MODE:-terminator}"

# ssh 비밀번호는 ROBOT_PW 환경변수로만 전달한다. sshpass 우선, 없으면 SSH_ASKPASS 헬퍼 사용.
# bringup/카메라는 stdin 파이프(bash -s)를 쓰므로 -tt 사용하지 않음.
ROBOT_PW="${ROBOT_PW:?Set ROBOT_PW in the environment}"
SSH_ASKPASS_HELPER="$SCRIPT_DIR/ssh_askpass_robot.sh"
SSH_USE_ASKPASS=0
SSH_MODE="interactive"
SSH_CONNECT_TIMEOUT="${SSH_CONNECT_TIMEOUT:-15}"
SSH_PREFLIGHT_RETRIES="${SSH_PREFLIGHT_RETRIES:-4}"
SSH_PREFLIGHT_SLEEP_SEC="${SSH_PREFLIGHT_SLEEP_SEC:-3}"
if [[ -n "$ROBOT_PW" ]] && command -v sshpass >/dev/null 2>&1; then
  SSH_CMD=(sshpass -p "$ROBOT_PW" ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout="$SSH_CONNECT_TIMEOUT")
  SSH_MODE="sshpass"
elif [[ -n "$ROBOT_PW" && -x "$SSH_ASKPASS_HELPER" ]]; then
  export ROBOT_PW
  export SSH_ASKPASS="$SSH_ASKPASS_HELPER"
  export SSH_ASKPASS_REQUIRE=force
  export DISPLAY="${DISPLAY:-:1}"
  SSH_CMD=(ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout="$SSH_CONNECT_TIMEOUT" -o BatchMode=no)
  SSH_USE_ASKPASS=1
  SSH_MODE="askpass"
else
  SSH_CMD=(ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout="$SSH_CONNECT_TIMEOUT")
  SSH_MODE="interactive"
fi

TMUX_BIN="$(command -v tmux || true)"
TERM_BIN="$(command -v gnome-terminal || true)"
TERMINATOR_BIN="$(command -v terminator || true)"

log() { printf '[start_all] %s\n' "$*"; }
die() { printf '[start_all] ERROR: %s\n' "$*" >&2; exit 1; }

preflight_robot_ssh() {
  [[ "$WITH_ROBOT" == "1" ]] || return 0
  log "로봇 SBC ssh 연결 확인: $ROBOT_SSH (mode=$SSH_MODE, timeout=${SSH_CONNECT_TIMEOUT}s)"
  local out err rc attempt
  for attempt in $(seq 1 "$SSH_PREFLIGHT_RETRIES"); do
    out=$("${SSH_CMD[@]}" "$ROBOT_SSH" "echo ssh_ok" 2>&1) && rc=0 || rc=$?
    if [[ $rc -eq 0 ]] && grep -q ssh_ok <<<"$out"; then
      log "로봇 SBC ssh OK (try ${attempt}/${SSH_PREFLIGHT_RETRIES})"
      return 0
    fi
    err="$out"
    if grep -qi "permission denied\|authentication failed" <<<"$err"; then
      break
    fi
    log "ssh 실패 try ${attempt}/${SSH_PREFLIGHT_RETRIES}: ${err%%$'\n'*} — ${SSH_PREFLIGHT_SLEEP_SEC}s 후 재시도"
    sleep "$SSH_PREFLIGHT_SLEEP_SEC"
  done
  # sshpass 실패 시 askpass 로 한 번 더 시도
  if [[ "$SSH_MODE" == "sshpass" && -x "$SSH_ASKPASS_HELPER" ]]; then
    log "sshpass 실패 — SSH_ASKPASS 로 재시도"
    export ROBOT_PW SSH_ASKPASS="$SSH_ASKPASS_HELPER" SSH_ASKPASS_REQUIRE=force
    export DISPLAY="${DISPLAY:-:1}"
    out=$(ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout="$SSH_CONNECT_TIMEOUT" -o BatchMode=no \
      "$ROBOT_SSH" "echo ssh_ok" 2>&1) && rc=0 || rc=$?
    if [[ $rc -eq 0 ]] && grep -q ssh_ok <<<"$out"; then
      SSH_CMD=(ssh -o StrictHostKeyChecking=accept-new -o ConnectTimeout="$SSH_CONNECT_TIMEOUT" -o BatchMode=no)
      SSH_USE_ASKPASS=1
      SSH_MODE="askpass"
      log "로봇 SBC ssh OK (askpass)"
      return 0
    fi
    err="$out"
  fi
  if grep -qi "no route to host\|network is unreachable\|connection timed out\|connection refused" <<<"$err"; then
    die "로봇 SBC 네트워크/SSH 불가 ($ROBOT_SSH). ping·전원·WiFi 확인 후 재시도. 최근: ${err%%$'\n'*}"
  fi
  if grep -qi "permission denied\|authentication failed" <<<"$err"; then
    die "로봇 SBC ssh 인증 실패. 비번(ROBOT_PW) 확인 또는: ssh-copy-id $ROBOT_SSH"
  fi
  die "로봇 SBC ssh 실패 ($ROBOT_SSH): ${err:-unknown error}"
}

ssh_robot() {
  "${SSH_CMD[@]}" "$ROBOT_SSH" "$@"
}

ssh_robot_bringup_body() {
  local ekf_exports="TB3_EKF_MODE=$WITH_EKF"
  if [[ "$WITH_EKF" == "1" ]]; then
    "${SSH_CMD[@]}" "$ROBOT_SSH" "cat > /tmp/tb3_ekf_bringup_overlay.yaml" \
      < "$ROOT/config/robot_sbc/tb3_ekf_bringup_overlay.yaml" 2>/dev/null || true
    ekf_exports="TB3_EKF_MODE=1 TB3_EKF_OVERLAY=/tmp/tb3_ekf_bringup_overlay.yaml"
  fi
  cat <<EOF
${SSH_CMD[*]} $ROBOT_SSH "export ROS_DOMAIN_ID=$DOMAIN ROS_AUTOMATIC_DISCOVERY_RANGE=SUBNET ROS_STATIC_PEERS=192.168.30.12 FASTRTPS_DEFAULT_PROFILES_FILE=/tmp/fastdds_robot_sbc.xml LDS_MODEL=$ROBOT_LDS_MODEL USB_PORT='$ROBOT_USB' WS_SETUP='$ROBOT_WS_SETUP' $ekf_exports; bash -s" < "$ROBOT_SBC_DIR/start_bringup.sh"
EOF
}

ssh_robot_camera_body() {
  cat <<EOF
${SSH_CMD[*]} $ROBOT_SSH "export ROS_DOMAIN_ID=$DOMAIN BRINGUP_WAIT_SEC=$ROBOT_BRINGUP_WAIT_SEC CAMERA_LAUNCH='$CAMERA_LAUNCH' WS_SETUP='$ROBOT_WS_SETUP'; bash -s" < "$ROBOT_SBC_DIR/start_camera.sh"
EOF
}

ssh_robot_lift_body() {
  cat <<EOF
${SSH_CMD[*]} $ROBOT_SSH "export ROS_DOMAIN_ID=$DOMAIN LIFT_WS_SETUP='$LIFT_WS_SETUP' LIFT_SERIAL_PORT='$LIFT_SERIAL_PORT' LIFT_BRIDGE_PKG='$LIFT_BRIDGE_PKG'; bash -s" < "$ROBOT_SBC_DIR/start_lift_bridge.sh"
EOF
}

cmd_nav2_rviz() {
  local ekf_flag=""
  if [[ "$WITH_EKF" == "1" ]]; then
    ekf_flag="--with-ekf"
  fi
  cat <<EOF
cd '$ROOT'
# shellcheck source=/dev/null
source '$SCRIPT_DIR/setup_ros_robot_network_env.sh' 2>/dev/null || true
# shellcheck source=/dev/null
[[ -f "\$HOME/ros2_env.sh" ]] && source "\$HOME/ros2_env.sh" || true
export ROS_DOMAIN_ID=$DOMAIN ROS_LOCALHOST_ONLY=0 DISPLAY='$DISPLAY' WITH_EKF=$WITH_EKF
unset ROS_LOCALHOST_ONLY
export ROS_AUTOMATIC_DISCOVERY_RANGE="\${ROS_AUTOMATIC_DISCOVERY_RANGE:-SUBNET}"
# Keep the complete peer roster loaded by ROS_NETWORK_SETUP.
echo '========================================'
echo '  ROBOT2 | Nav2+RViz | domain $DOMAIN | API :8002'
echo "  DDS peers=\$ROS_STATIC_PEERS range=\$ROS_AUTOMATIC_DISCOVERY_RANGE"
echo '========================================'
echo '[nav2-rviz] bringup 토픽 대기... (WITH_EKF=$WITH_EKF)'
until '$SCRIPT_DIR/wait_for_robot_topics.sh' $DOMAIN $ROBOT_TOPIC_WAIT_SEC; do
  echo '[nav2-rviz] odom/scan 미수신 — 빈 RViz를 띄우지 않고 5s 후 다시 대기'
  sleep 5
done
echo '[nav2-rviz] 로봇 토픽 준비 완료 — Nav2/RViz 기동'
exec scripts/run_nav2_with_initial_pose.sh --robot tb3_2 --domain $DOMAIN --map '$MAP' --x '$INIT_X' --y '$INIT_Y' --yaw='$INIT_YAW' --delay 12 --repeat 5 --startup-retry 180 $ekf_flag
EOF
}

# detector: SBC 카메라 토픽 대기 → ArUco detector (죽으면 자동 재시작)
cmd_detector2() {
  cat <<EOF
cd '$ROOT'
source '$ROS_NETWORK_SETUP' 2>/dev/null || true
export ROS_DOMAIN_ID=$DOMAIN
export ROBOT_ID=tb3_burger_02
# Keep the complete peer roster loaded by ROS_NETWORK_SETUP.
export ARUCO_MARKER_SIZE_M=0.05
export START_CAMERA_LAUNCH=0
export START_CAMERA_RELAY=1
DETECTOR_LOG='$LOG_DIR/detector2_tb3_2.log'
# shellcheck source=/dev/null
source '$ROS_SETUP' 2>/dev/null || true
set +e
echo "========================================"
echo "  ROBOT2 | detector2 (ArUco) | domain $DOMAIN | :8002"
echo "  log: $LOG_DIR/detector2_tb3_2.log"
echo "========================================"
while true; do
  echo '[detector2] 카메라 /camera/image_raw/compressed 대기 중...'
  until [[ "\$(timeout --signal=INT --kill-after=2s 4s ros2 topic info /camera/image_raw/compressed 2>/dev/null | awk '/Publisher count:/ {print \$3}' | head -1)" =~ ^[1-9][0-9]*$ ]]; do
    sleep 3
  done
  echo '[detector2] 카메라 OK — detector 기동'
  {
    echo "===== \$(date -Is) detector2 start ====="
    exec env START_CAMERA_LAUNCH=0 ROBOT_ID=tb3_burger_02 scripts/run_pi_camera_aruco.sh
  } 2>&1 | tee -a "\$DETECTOR_LOG" || true
  echo '[detector2] 프로세스 종료 — 5s 후 재시작' | tee -a "\$DETECTOR_LOG"
  sleep 5
done
EOF
}

cmd_nav_servers() {
  cat <<EOF
cd '$ROOT'
# shellcheck source=/dev/null
source '$ROS_SETUP' 2>/dev/null || true
# shellcheck source=/dev/null
source '$ROS_NETWORK_SETUP' 2>/dev/null || true
export ROS_DOMAIN_ID=$DOMAIN
# Keep the complete peer roster loaded by ROS_NETWORK_SETUP.
echo '[api-8002] bringup /odom + /scan 준비 대기...'
'$SCRIPT_DIR/wait_for_robot_topics.sh' $DOMAIN 30 || \
  echo '[api-8002] WARNING: bringup readiness timeout — API는 시작하고 health에서 연결 상태를 차단'
echo '[api-8002] 준비 검사 종료 — Movement API 시작'
exec env ONLY_ROBOT=tb3_2 PROJECT_VENV='$PROJECT_VENV' \
  TRAFFIC_COORDINATION_MODE='$TRAFFIC_COORDINATION_MODE' TRAFFIC_DEPARTURE_STAGGER_SEC='$TRAFFIC_DEPARTURE_STAGGER_SEC' \
  TRAFFIC_SEGMENT_WAIT_TIMEOUT_SEC='$TRAFFIC_SEGMENT_WAIT_TIMEOUT_SEC' TRAFFIC_SEGMENT_TTL_SEC='$TRAFFIC_SEGMENT_TTL_SEC' scripts/start_nav_servers.sh foreground
EOF
}

cmd_status() {
  cat <<EOF
cd '$ROOT'
# shellcheck source=/dev/null
source '$ROS_SETUP' 2>/dev/null || true
# shellcheck source=/dev/null
source '$ROS_NETWORK_SETUP' 2>/dev/null || true
export ROS_DOMAIN_ID=$DOMAIN
echo '[status] 1/3 bringup /odom + /scan 대기...'
'$SCRIPT_DIR/wait_for_robot_topics.sh' $DOMAIN $ROBOT_TOPIC_WAIT_SEC || true
echo '[status] 2/3 Movement API :8002 health 대기...'
deadline=\$(( \$(date +%s) + $ROBOT_TOPIC_WAIT_SEC ))
while [[ \$(date +%s) -lt \$deadline ]]; do
  if curl -fsS --max-time 2 'http://127.0.0.1:8002/movement-api/v1/health' >/dev/null 2>&1; then
    echo '[status] API :8002 ready'
    break
  fi
  sleep 2
done
echo '[status] 3/3 ArUco publisher 대기...'
deadline=\$(( \$(date +%s) + $CAMERA_TOPIC_WAIT_SEC ))
while [[ \$(date +%s) -lt \$deadline ]]; do
  publishers=\$(timeout --signal=INT --kill-after=2s 3s ros2 topic info /mission/tb3_2/aruco/detections 2>/dev/null | awk '/Publisher count:/ {print \$3}' | head -1)
  if [[ "\${publishers:-0}" -ge 1 ]]; then
    echo '[status] ArUco publisher ready'
    break
  fi
  sleep 2
done
echo '[status] readiness 대기 완료 — 최종 상태 점검'
scripts/start_all_tb3_2.sh status
echo
echo '(재점검: scripts/start_all_tb3_2.sh status)'
exec bash
EOF
}

remote_stop_robot() {
  log "로봇 SBC bringup/카메라/lift 종료: $ROBOT_SSH"
  ssh_robot "bash -s" <"$ROBOT_SBC_DIR/stop_stack.sh" 2>/dev/null || \
    log "WARNING: 로봇 SBC ssh 종료 실패 (네트워크/비번 확인)"
}

# Kill processes whose environ has ROS_DOMAIN_ID=$DOMAIN (so the other robot survives).
kill_by_domain() {
  local domain="$1"
  local pattern="$2"
  local pid
  for pid in $(pgrep -f "$pattern" 2>/dev/null || true); do
    if grep -zqx "ROS_DOMAIN_ID=${domain}" "/proc/${pid}/environ" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
}

stop_local_stack() {
  log "Nav PC 스택 종료 중 (tb3_2 / domain $DOMAIN only)..."
  ONLY_ROBOT=tb3_2 "$SCRIPT_DIR/start_nav_servers.sh" stop 2>/dev/null || true
  pkill -f "run_nav2_with_initial_pose.sh --robot tb3_2" 2>/dev/null || true
  pkill -f "pane_detector2.sh" 2>/dev/null || true
  pkill -f "detector2_tb3_2" 2>/dev/null || true
  # ArUco / relay for robot2 only
  pkill -f "detection_topic:=/mission/tb3_2/aruco" 2>/dev/null || true
  pkill -f "output_topic:=/mission/tb3_2/camera" 2>/dev/null || true
  pkill -f "ROBOT_ID=tb3_burger_02 scripts/run_pi_camera_aruco" 2>/dev/null || true
  rm -f "$LOG_DIR/detector2_window.pid" 2>/dev/null || true
  # Nav2 / RViz / EKF belonging to this domain only
  kill_by_domain "$DOMAIN" "turtlebot3_navigation2"
  kill_by_domain "$DOMAIN" "component_container_isolated"
  kill_by_domain "$DOMAIN" "nav2_container"
  kill_by_domain "$DOMAIN" "rviz2"
  kill_by_domain "$DOMAIN" "ekf_filter_node"
  kill_by_domain "$DOMAIN" "ekf_odom.launch"
  sleep 2
}

stop_terminator() {
  if [[ -f "$SESSION_MARKER" ]]; then
    # shellcheck source=/dev/null
    source "$SESSION_MARKER" 2>/dev/null || true
    if [[ -n "${TERMINATOR_PID:-}" ]] && kill -0 "$TERMINATOR_PID" 2>/dev/null; then
      kill "$TERMINATOR_PID" 2>/dev/null || true
      log "terminator pid=$TERMINATOR_PID 종료"
    fi
  fi
  pkill -f "terminator -u -g /tmp/tb3_2_term" 2>/dev/null || true
  rm -f "$SESSION_MARKER"
}

stop_stack() {
  stop_terminator
  stop_local_stack
  if [[ "$WITH_ROBOT" == "1" ]]; then
    remote_stop_robot
  fi
  if [[ -n "$TMUX_BIN" ]] && tmux has-session -t "$SESSION" 2>/dev/null; then
    tmux kill-session -t "$SESSION"
    log "tmux 세션 '$SESSION' 종료"
  fi
  log "전체 종료 완료"
}

require_tmux() {
  [[ -n "$TMUX_BIN" ]] || die "tmux 가 필요합니다."
}

new_win() {
  local name="$1"; shift
  local cmd="$*"
  tmux new-window -t "$SESSION" -n "$name" \
    "bash -lc '$cmd; echo; echo \"[$name] 종료됨 - Enter로 닫기\"; read'"
}

write_run_script() {
  local name="$1"
  local content="$2"
  local f="$LOG_DIR/pane_${name}.sh"
  {
    printf '#!/usr/bin/env bash\nset -euo pipefail\n'
    printf '%s\n' "$content"
  } >"$f"
  chmod +x "$f"
  printf '%s' "$f"
}

open_win() {
  local title="$1"; shift
  gnome-terminal --title="$title" -- bash -lc "$*; echo; echo \"[$title] 종료됨 - Enter로 닫기\"; read" &
  sleep 1
}

start_stack_tmux() {
  require_tmux
  tmux has-session -t "$SESSION" 2>/dev/null && die "이미 '$SESSION' 세션 있습니다. stop 먼저."
  log "tmux 세션 시작 (WITH_ROBOT=$WITH_ROBOT WITH_LIFT=$WITH_LIFT WITH_EKF=$WITH_EKF)"

  if [[ "$WITH_ROBOT" == "1" ]]; then
    local bringup_sh camera_sh lift_sh="" detector_sh
    bringup_sh="$(write_run_script robot-bringup "$(ssh_robot_bringup_body)")"
    if [[ "$WITH_LIFT" == "1" ]]; then
      lift_sh="$(write_run_script robot-lift "$(ssh_robot_lift_body)")"
    fi
    camera_sh="$(write_run_script robot-camera "$(ssh_robot_camera_body)")"
    detector_sh="$(write_run_script detector2 "$(cmd_detector2)")"
    tmux new-session -d -s "$SESSION" -n "robot-bringup" \
      "bash -lc '$bringup_sh; echo; echo [robot-bringup] 종료; read'"
    if [[ -n "$lift_sh" ]]; then
      new_win "robot-lift" "$lift_sh"
    fi
    new_win "robot-camera" "$camera_sh"
    new_win "detector2" "$detector_sh"
  else
    tmux new-session -d -s "$SESSION" -n "detector2" \
      "bash -lc '$(write_run_script detector2 "$(cmd_detector2)"); echo; echo [detector2] 종료; read'"
  fi
  new_win "nav2-rviz" "$(cmd_nav2_rviz)"
  sleep 2
  new_win "nav-servers" "$(cmd_nav_servers)"
  new_win "status" "$(cmd_status)"
  log "attach: scripts/start_all_tb3_2.sh attach"
}

start_windows() {
  [[ -n "$TERM_BIN" ]] || die "gnome-terminal 필요"
  if [[ "$WITH_ROBOT" == "1" ]]; then
    open_win "robot-bringup" "$(write_run_script robot-bringup "$(ssh_robot_bringup_body)")"
    if [[ "$WITH_LIFT" == "1" ]]; then
      open_win "robot-lift" "$(write_run_script robot-lift "$(ssh_robot_lift_body)")"
    fi
    open_win "robot-camera" "$(write_run_script robot-camera "$(ssh_robot_camera_body)")"
    open_win "detector2" "$(write_run_script detector2 "$(cmd_detector2)")"
  else
    open_win "detector2" "$(write_run_script detector2 "$(cmd_detector2)")"
  fi
  open_win "nav2-rviz" "$(cmd_nav2_rviz)"
  sleep 2
  open_win "nav-servers" "$(cmd_nav_servers)"
  open_win "status" "$(cmd_status)"
}

start_terminator() {
  [[ -n "$TERMINATOR_BIN" ]] || die "terminator 필요 (sudo apt install terminator)"
  preflight_robot_ssh
  if [[ "$WITH_ROBOT" == "1" ]]; then
    log "로봇 SBC Fast DDS 프로필 배포 → $ROBOT_SSH"
    "${SSH_CMD[@]}" "$ROBOT_SSH" "tee /tmp/fastdds_robot_sbc.xml >/dev/null" \
      < "$ROOT/config/fastdds_robot_sbc.xml" || die "SBC Fast DDS 프로필 배포 실패"
    log "로봇 SBC 카메라 스크립트 배포 → $ROBOT_SSH"
    ROBOT_SSH="$ROBOT_SSH" ROBOT_PW="$ROBOT_PW" \
      "$ROBOT_SBC_DIR/deploy_camera_to_sbc.sh" || die "카메라 스크립트 SBC 배포 실패"
  fi
  log "terminator split 시작 ROBOT2 WITH_ROBOT=$WITH_ROBOT WITH_LIFT=$WITH_LIFT WITH_EKF=$WITH_EKF DOMAIN=$DOMAIN"

  local tmpd; tmpd="$(mktemp -d /tmp/tb3_2_term.XXXXXX)"
  local manifest="$tmpd/manifest.tsv"
  : > "$manifest"
  local idx=0

  add_pane() {
    local title="$1"; shift
    local body="$1"
    local w="$tmpd/pane_${idx}.sh"
    {
      printf '#!/usr/bin/env bash\nset +e\n'
      # Keep this wrapper alive while the pane command runs. Some pane bodies
      # use `exec`, which previously replaced the wrapper and made the health
      # check falsely report those live panes as missing.
      printf '(\n'
      printf '%s\n' "$body"
      printf ')\n'
      printf 'ec=$?\n'
      printf 'echo\n'
      printf 'echo "[%s] 종료됨(exit=$ec) - Enter로 이 pane 닫기"\n' "$title"
      printf 'read _\n'
    } > "$w"
    chmod +x "$w"
    printf '%s\t%s\n' "$title" "$w" >> "$manifest"
    idx=$((idx+1))
  }

  if [[ "$WITH_ROBOT" == "1" ]]; then
    add_pane "R2-bringup" "$(ssh_robot_bringup_body)"
    if [[ "$WITH_LIFT" == "1" ]]; then
      add_pane "R2-lift" "$(ssh_robot_lift_body)"
    fi
    add_pane "R2-camera" "$(ssh_robot_camera_body)"
    add_pane "R2-detector" "$(cmd_detector2)"
  else
    add_pane "R2-detector" "$(cmd_detector2)"
  fi
  add_pane "R2-nav2-rviz" "$(cmd_nav2_rviz)"
  add_pane "R2-api-8002" "sleep 3; $(cmd_nav_servers)"
  add_pane "R2-status" "$(cmd_status)"

  local cfg="$tmpd/terminator.config"
  MANIFEST="$manifest" CFG="$cfg" python3 - <<'PY'
import os

manifest = os.environ["MANIFEST"]
cfg = os.environ["CFG"]
items = []
with open(manifest) as f:
    for line in f:
        line = line.rstrip("\n")
        if not line:
            continue
        title, cmd = line.split("\t", 1)
        items.append((title, cmd))

by_title = {t: w for t, w in items}

def need(title):
    path = by_title.get(title)
    if not path:
        raise SystemExit(f"missing pane in manifest: {title}")
    return path

lines = [
    "[global_config]",
    "  title_use_system_font = True",
    "[profiles]",
    "  [[default]]",
    "    scrollback_lines = 5000",
    "[layouts]",
    "  [[tb3_2]]",
    "    [[[window0]]]",
    "      type = Window",
    '      parent = ""',
    "      order = 0",
    "      size = 1680, 1000",
    "      maximised = True",
    '      title = ROBOT2 | tb3_2 | :8002 | domain5',
    # 좌: 로봇+비전(카메라|detector) / 우: Nav2+API
    "    [[[root_split]]]",
    "      type = HPaned",
    "      parent = window0",
    "      order = 0",
    "      ratio = 0.46",
    "    [[[left_col]]]",
    "      type = VPaned",
    "      parent = root_split",
    "      order = 0",
    "      ratio = 0.5",
    "    [[[right_col]]]",
    "      type = VPaned",
    "      parent = root_split",
    "      order = 1",
    "      ratio = 0.5",
    "    [[[vision_row]]]",
    "      type = HPaned",
    "      parent = left_col",
    "      order = 1",
    "      ratio = 0.66",
    "    [[[nav_mid]]]",
    "      type = HPaned",
    "      parent = right_col",
    "      order = 1",
    "      ratio = 0.28",
]

# WITH_LIFT=0 이면 robot_row HPaned에 자식 1개만 남아 terminator가 레이아웃을 깨뜨림.
has_lift = "R2-lift" in by_title
if has_lift:
    lines.extend(
        [
            "    [[[robot_row]]]",
            "      type = HPaned",
            "      parent = left_col",
            "      order = 0",
            "      ratio = 0.34",
        ]
    )

def term(name, parent, order, title, cmd):
    lines.extend(
        [
            f"    [[[{name}]]]",
            "      type = Terminal",
            f"      parent = {parent}",
            f"      order = {order}",
            "      profile = default",
            f"      command = {cmd}",
            f"      title = {title}",
        ]
    )

if has_lift:
    term("term_bringup", "robot_row", 0, "R2-bringup", need("R2-bringup"))
    term("term_lift", "robot_row", 1, "R2-lift", need("R2-lift"))
else:
    term("term_bringup", "left_col", 0, "R2-bringup", need("R2-bringup"))

# vision row — camera | detector 나란히
term("term_camera", "vision_row", 0, "R2-camera", need("R2-camera"))
term("term_detector", "vision_row", 1, "R2-detector", need("R2-detector"))

# right column
term("term_nav2", "right_col", 0, "R2-nav2-rviz", need("R2-nav2-rviz"))
term("term_navsrv", "nav_mid", 0, "R2-api-8002", need("R2-api-8002"))
term("term_status", "nav_mid", 1, "R2-status", need("R2-status"))

open(cfg, "w").write("\n".join(lines) + "\n")
PY

  verify_terminator_panes() {
    local tmpd="$1" n="$2"
    sleep 5
    local i running=0 missing=""
    for i in $(seq 0 $((n - 1))); do
      if pgrep -f "${tmpd}/pane_${i}.sh" >/dev/null 2>&1; then
        running=$((running + 1))
      else
        missing="${missing} pane_${i}"
      fi
    done
    if [[ "$running" -ge "$n" ]]; then
      log "terminator pane ${running}/${n} 모두 실행 중"
      return 0
    fi
    log "WARNING: terminator pane ${running}/${n}만 실행 — 누락:${missing}"
    log "  → scripts/start_all_tb3_2.sh restart (레이아웃 ratio/maximise 적용)"
    # detector pane(보통 idx=3)이 죽었으면 백그라운드 fallback — 시나리오는 계속 가능
    if [[ "$WITH_ROBOT" == "1" ]] && ! pgrep -f "${tmpd}/pane_3.sh" >/dev/null 2>&1 \
        && ! pgrep -f "aruco_detector_node.py" >/dev/null 2>&1 \
        && [[ -x "${tmpd}/pane_3.sh" ]]; then
      log "detector2 pane 미기동 — 백그라운드 fallback (로그: $LOG_DIR/detector2_fallback.log)"
      nohup bash "${tmpd}/pane_3.sh" >>"$LOG_DIR/detector2_fallback.log" 2>&1 &
    fi
  }

  local tlog="$tmpd/terminator.log"
  nohup setsid dbus-run-session -- terminator -m -u -g "$cfg" -l tb3_2 >"$tlog" 2>&1 < /dev/null &
  local tpid=$!
  disown 2>/dev/null || true
  sleep 2
  {
    printf 'TERMINATOR_PID=%s\n' "$tpid"
    printf 'TERMINATOR_CFG=%s\n' "$cfg"
    printf 'TERMINATOR_TMPD=%s\n' "$tmpd"
  } >"$SESSION_MARKER"
  if kill -0 "$tpid" 2>/dev/null; then
    log "terminator 실행됨 pid=$tpid"
    log "레이아웃: 왼쪽 아래 vision_row = robot-camera | detector2 (나란히)"
    verify_terminator_panes "$tmpd" "$idx"
  else
    log "WARNING: terminator 미기동. $tlog:"
    sed 's/^/  /' "$tlog" 2>/dev/null || true
  fi
  log "상태 점검 (${STATUS_DELAY_SEC}s 후 status pane): scripts/start_all_tb3_2.sh status"
  log "전체 종료: scripts/start_all_tb3_2.sh stop"
}

attach_stack() {
  require_tmux
  tmux has-session -t "$SESSION" 2>/dev/null || die "'$SESSION' 없음"
  exec tmux attach -t "$SESSION"
}

status_stack() {
  echo "===== Movement API health ====="
  for p in 8001 8002; do
    printf 'port %s: ' "$p"
    curl -s --max-time 3 "http://127.0.0.1:$p/movement-api/v1/health" \
      | python3 -c "import sys,json; d=json.load(sys.stdin); print('online=%s accepting=%s localized=%s nav=%s active=%s' % (d['robot_online'], d['command_accepting'], d['localized'], d['navigator_status'], d.get('active_commands',[])))" 2>/dev/null \
      || echo "unreachable"
  done

  echo ""
  echo "===== ROS 토픽/TF (DOMAIN=$DOMAIN) ====="
  set +u
  # shellcheck source=/dev/null
  source "$ROS_SETUP" 2>/dev/null
  set -u
  # status must use the same DDS discovery settings as the launched stack.
  # shellcheck source=/dev/null
  source "$ROS_NETWORK_SETUP" 2>/dev/null || true
  export ROS_DOMAIN_ID="$DOMAIN"
  # Keep the complete peer roster loaded by ROS_NETWORK_SETUP.

  printf '/odom 발행: '
  if timeout --signal=INT --kill-after=2s 45s ros2 topic echo /odom --once >/dev/null 2>&1; then echo "OK"
  else echo "없음 (bringup/OpenCR 확인)"; fi

  printf '/scan 발행: '
  if timeout --signal=INT --kill-after=2s 45s ros2 topic echo /scan --once --qos-reliability best_effort >/dev/null 2>&1; then echo "OK"
  else echo "없음 (bringup/LDS 확인)"; fi

  printf 'odom->base_footprint TF: '
  if timeout --signal=INT --kill-after=2s 30s ros2 run tf2_ros tf2_echo odom base_footprint 2>/dev/null | head -1 | grep -q "At time"; then echo "OK"
  else echo "없음"; fi

  printf '카메라 /camera/image_raw/compressed: '
  if timeout --signal=INT --kill-after=2s 45s ros2 topic echo /camera/image_raw/compressed --once --qos-reliability best_effort >/dev/null 2>&1; then echo "OK"
  else echo "없음 (카메라 pane 확인)"; fi

  printf 'ArUco /mission/tb3_2/aruco/detections: '
  aruco_pub=$(timeout --signal=INT --kill-after=2s 3s ros2 topic info /mission/tb3_2/aruco/detections 2>/dev/null | awk '/Publisher count:/ {print $3}' | head -1)
  if [[ "${aruco_pub:-0}" -ge 1 ]]; then
    echo "OK (publisher=$aruco_pub)"
  else
    echo "없음 — detector2 pane 확인 (scripts/nav_ops.sh detector2)"
    if pgrep -f "aruco_detector_node.py" >/dev/null 2>&1; then
      echo "  (aruco_detector_node 프로세스는 있으나 publisher 미연결)"
    fi
  fi

  echo ""
  echo "===== Nav2 lifecycle ====="
  local lifecycle_node lifecycle_state
  for lifecycle_node in map_server amcl controller_server planner_server bt_navigator; do
    lifecycle_state=$(timeout --signal=INT --kill-after=2s 20s ros2 lifecycle get "/$lifecycle_node" 2>/dev/null || true)
    if [[ "$lifecycle_state" == *"active [3]"* ]]; then
      echo "$lifecycle_node: active"
    elif [[ -n "$lifecycle_state" ]]; then
      echo "$lifecycle_node: $lifecycle_state"
    else
      echo "$lifecycle_node: 없음/응답없음"
    fi
  done

  echo ""
  echo "===== Lift (DOMAIN=$DOMAIN) ====="
  lift_subs=$(timeout --signal=INT --kill-after=2s 4s ros2 topic info /lift/cmd_move 2>/dev/null | awk '/Subscription count:/ {print $3}' | head -1)
  lift_pub=$(timeout --signal=INT --kill-after=2s 4s ros2 topic info /lift/position 2>/dev/null | awk '/Publisher count:/ {print $3}' | head -1)
  if [[ "${lift_subs:-0}" -ge 1 && "${lift_pub:-0}" -ge 1 ]]; then
    echo "lift_bridge OK (cmd_move subs=$lift_subs, position pub=$lift_pub)"
  elif [[ "${lift_subs:-0}" -ge 1 ]]; then
    echo "lift_bridge partial (cmd_move subs=$lift_subs, position pub=${lift_pub:-0})"
  else
    echo "lift_bridge 없음 — robot-lift pane 또는: scripts/test_lift_tb3_2.sh status"
    echo "  (lift 생략: WITH_LIFT=0 scripts/start_all_tb3_2.sh restart)"
  fi

  echo ""
  echo "===== 세션 ====="
  if pgrep -f "aruco_detector_node.py" >/dev/null 2>&1; then
    echo "detector2: aruco_detector_node 실행 중"
  else
    echo "detector2: 없음 — robot-camera 오른쪽 pane 또는 fallback 로그 확인"
  fi
  if [[ -f "$SESSION_MARKER" ]]; then
    # shellcheck source=/dev/null
    source "$SESSION_MARKER" 2>/dev/null || true
    if [[ -n "${TERMINATOR_TMPD:-}" && -d "$TERMINATOR_TMPD" ]]; then
      local pane_total pane_up pi
      pane_total=$(wc -l <"${TERMINATOR_TMPD}/manifest.tsv" 2>/dev/null || echo 0)
      pane_up=0
      for pi in "${TERMINATOR_TMPD}"/pane_*.sh; do
        [[ -f "$pi" ]] || continue
        pgrep -f "$pi" >/dev/null 2>&1 && pane_up=$((pane_up + 1))
      done
      echo "terminator panes: ${pane_up}/${pane_total} 실행 (detector2 = robot-camera 오른쪽 pane)"
      if [[ "$pane_up" -lt "$pane_total" ]]; then
        echo "  → pane 누락 시: scripts/start_all_tb3_2.sh restart"
      fi
    fi
    echo "terminator: $(tr '\n' ' ' <"$SESSION_MARKER")"
  else
    echo "terminator: 없음"
  fi
  tmux has-session -t "$SESSION" 2>/dev/null && tmux list-windows -t "$SESSION" || echo "tmux: 없음"
}

restart_stack() {
  stop_stack
  sleep 3
  start_terminator
}

case "${1:-$MODE}" in
  start|terminator|term) start_terminator ;;
  tmux)                start_stack_tmux ;;
  windows)             start_windows ;;
  attach)              attach_stack ;;
  status)              status_stack ;;
  stop)                stop_stack ;;
  restart)             restart_stack ;;
  -h|--help|help)
    grep -E '^#( |$)' "$0" | sed 's/^# \{0,1\}//'
    ;;
  *) die "알 수 없는 명령: $1 (start|stop|restart|status|tmux|windows)" ;;
esac
