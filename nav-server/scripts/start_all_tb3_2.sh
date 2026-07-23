#!/usr/bin/env bash
#
# tb3_2 전체 스택 원샷 런처
#
# 한 번에 띄우는 것:
#   [로봇 SBC] bringup(odom/scan/TF) + lift_bridge + 카메라 (기본 ON, ssh)
#   [Nav PC]   Nav2+RViz / Movement API(:8002) / ArUco detector
#
# 사용법:
#   scripts/start_all_tb3_2.sh              # terminator split (기본, 로봇 SBC 포함)
#   scripts/start_all_tb3_2.sh restart      # 전체 종료 후 재기동
#   scripts/start_all_tb3_2.sh stop         # Nav PC + 로봇 SBC + terminator 종료
#   scripts/start_all_tb3_2.sh status       # 상태 점검
#   scripts/start_all_tb3_2.sh tmux       # tmux 모드
#   scripts/start_all_tb3_2.sh windows      # gnome-terminal 개별창
#
#   WITH_ROBOT=0 scripts/start_all_tb3_2.sh # 로봇 SBC ssh 생략 (SBC에서 직접 기동할 때)
#   WITH_LIFT=0 scripts/start_all_tb3_2.sh # lift_bridge pane 생략 (도킹만 테스트)
#   WITH_EKF=1 scripts/start_all_tb3_2.sh # robot_localization EKF (wheel odom + IMU)
#
# Lift env (SBC 경로):
#   WITH_LIFT=1 (기본)
#   LIFT_WS_SETUP=~/lift_project/ros2_ws/install/setup.bash
#   LIFT_SERIAL_PORT=   # 비우면 bridge 기본 by-id
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROBOT_SBC_DIR="$SCRIPT_DIR/robot_sbc"
# shellcheck source=lib/local_hardware.sh
source "$SCRIPT_DIR/lib/local_hardware.sh"
LOG_DIR="${LOG_DIR:-$ROOT/logs}"
SESSION_MARKER="$LOG_DIR/tb3_2_stack.session"

# Load only the local hardware connection settings.  This deliberately does
# not source the file: command substitutions and other shell syntax remain
# literal values instead of being executed.
load_local_hardware_env

SESSION="${SESSION:-tb3_2_stack}"
DOMAIN="${DOMAIN:-5}"
MAP="${MAP:-$ROOT/map/robot2_map.yaml}"
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
export DISPLAY="${DISPLAY:-:1}"

# 기본: 로봇 SBC bringup/카메라/lift까지 ssh로 함께 기동
WITH_ROBOT="${WITH_ROBOT:-1}"
WITH_LIFT="${WITH_LIFT:-1}"
WITH_EKF="${WITH_EKF:-0}"
LIFT_WS_SETUP="${LIFT_WS_SETUP:-}"
LIFT_SERIAL_PORT="${LIFT_SERIAL_PORT:-}"
LIFT_BRIDGE_PKG="${LIFT_BRIDGE_PKG:-lift_bridge}"
ROBOT_SSH="${ROBOT_SSH:-musk@192.168.30.102}"
ROBOT_USB="${ROBOT_USB:-/dev/serial/by-id/usb-ROBOTIS_OpenCR_Virtual_ComPort_in_FS_Mode_FFFFFFFEFFFF-if00}"
CAMERA_LAUNCH="${CAMERA_LAUNCH:-turtlebot3_bringup camera.launch.py}"
CAMERA_BACKEND="${CAMERA_BACKEND:-camera_ros}"
ROBOT_WS_SETUP="${ROBOT_WS_SETUP:-}"
ROBOT_LDS_MODEL="${ROBOT_LDS_MODEL:-LDS-03}"
ROBOT_BRINGUP_WAIT_SEC="${ROBOT_BRINGUP_WAIT_SEC:-10}"
ROBOT_TOPIC_WAIT_SEC="${ROBOT_TOPIC_WAIT_SEC:-120}"
CAMERA_TOPIC_WAIT_SEC="${CAMERA_TOPIC_WAIT_SEC:-60}"
STATUS_DELAY_SEC="${STATUS_DELAY_SEC:-50}"
MODE="${MODE:-terminator}"

# SSH keys are the default. Password authentication is opt-in and requires sshpass.
# bringup/카메라는 stdin 파이프(bash -s)를 쓰므로 -tt 사용하지 않음.
ROBOT_PW="${ROBOT_PW:-}"
configure_robot_ssh 8
if [[ -n "$ROBOT_PW" && "$SSH_MODE" == "key" ]]; then
  printf '[start_all] %s\n' "ROBOT_PW was supplied but sshpass is unavailable; using SSH key authentication."
fi

TMUX_BIN="$(command -v tmux || true)"
TERM_BIN="$(command -v gnome-terminal || true)"
TERMINATOR_BIN="$(command -v terminator || true)"

log() { printf '[start_all] %s\n' "$*"; }
die() { printf '[start_all] ERROR: %s\n' "$*" >&2; exit 1; }

preflight_robot_ssh() {
  [[ "$WITH_ROBOT" == "1" ]] || return 0
  [[ -n "$ROBOT_WS_SETUP" ]] || die "ROBOT_WS_SETUP must point to the SBC TurtleBot3 overlay setup.bash when WITH_ROBOT=1"
  if [[ "$WITH_LIFT" == "1" ]]; then
    [[ -n "$LIFT_WS_SETUP" ]] || die "LIFT_WS_SETUP must point to the SBC lift overlay setup.bash when WITH_LIFT=1"
  fi
  log "로봇 SBC ssh 연결 확인: $ROBOT_SSH (mode=$SSH_MODE)"
  local out err rc
  out=$("${SSH_CMD[@]}" "$ROBOT_SSH" "echo ssh_ok" 2>&1) && rc=0 || rc=$?
  if [[ $rc -eq 0 ]] && grep -q ssh_ok <<<"$out"; then
    log "로봇 SBC ssh OK"
    return 0
  fi
  err="$out"
  if grep -qi "no route to host\|network is unreachable" <<<"$err"; then
    die "로봇 SBC 네트워크 연결 불가 ($ROBOT_SSH). 로봇 전원/WiFi·유선·IP(192.168.30.102) 확인 후 재시도."
  fi
  if grep -qi "permission denied\|authentication failed" <<<"$err"; then
    die "로봇 SBC ssh authentication failed. Configure an SSH key for $ROBOT_SSH, or explicitly supply ROBOT_PW with sshpass installed."
  fi
  die "로봇 SBC ssh failed ($ROBOT_SSH)."
}

ssh_robot() {
  "${SSH_CMD[@]}" "$ROBOT_SSH" "$@"
}

shell_assignment() {
  local name="$1" value="$2" quoted
  printf -v quoted '%q' "$value"
  printf '%s=%s\n' "$name" "$quoted"
}

shell_array() {
  local name="$1" value quoted
  shift
  printf '%s=(' "$name"
  for value in "$@"; do
    printf -v quoted '%q' "$value"
    printf ' %s' "$quoted"
  done
  printf ' )\n'
}

shell_export_assignment() {
  local name="$1" value="$2" quoted
  printf -v quoted '%q' "$value"
  printf 'export %s=%s\n' "$name" "$quoted"
}

shell_command() {
  local arg quoted
  for arg in "$@"; do
    printf -v quoted '%q' "$arg"
    printf '%s ' "$quoted"
  done
  printf '\n'
}

ssh_robot_script_body() {
  local remote_env_name="$1" remote_env_ref="$2" script="$3"
  local -n remote_env_values="$remote_env_ref"
  shell_array SSH_CMD "${SSH_CMD[@]}"
  shell_assignment ROBOT_SSH "$ROBOT_SSH"
  shell_array "$remote_env_name" "${remote_env_values[@]}"
  printf '"${SSH_CMD[@]}" "$ROBOT_SSH" "${%s[@]}" bash -s < ' "$remote_env_name"
  printf '%q\n' "$script"
}

ssh_robot_bringup_body() {
  local -a remote_env=(
    env
    "ROS_DOMAIN_ID=$DOMAIN"
    "LDS_MODEL=$ROBOT_LDS_MODEL"
    "USB_PORT=$ROBOT_USB"
    "WS_SETUP=$ROBOT_WS_SETUP"
    "TB3_EKF_MODE=$WITH_EKF"
  )
  if [[ "$WITH_EKF" == "1" ]]; then
    "${SSH_CMD[@]}" "$ROBOT_SSH" "cat > /tmp/tb3_ekf_bringup_overlay.yaml" \
      < "$ROOT/config/robot_sbc/tb3_ekf_bringup_overlay.yaml" 2>/dev/null || true
    remote_env+=("TB3_EKF_OVERLAY=/tmp/tb3_ekf_bringup_overlay.yaml")
  fi
  ssh_robot_script_body REMOTE_ENV remote_env "$ROBOT_SBC_DIR/start_bringup.sh"
}

ssh_robot_camera_body() {
  local -a remote_env=(
    env
    "ROS_DOMAIN_ID=$DOMAIN"
    "BRINGUP_WAIT_SEC=$ROBOT_BRINGUP_WAIT_SEC"
    "CAMERA_BACKEND=$CAMERA_BACKEND"
    "CAMERA_LAUNCH=$CAMERA_LAUNCH"
    "WS_SETUP=$ROBOT_WS_SETUP"
  )
  ssh_robot_script_body REMOTE_ENV remote_env "$ROBOT_SBC_DIR/start_camera.sh"
}

ssh_robot_lift_body() {
  local -a remote_env=(
    env
    "ROS_DOMAIN_ID=$DOMAIN"
    "LIFT_WS_SETUP=$LIFT_WS_SETUP"
    "LIFT_SERIAL_PORT=$LIFT_SERIAL_PORT"
    "LIFT_BRIDGE_PKG=$LIFT_BRIDGE_PKG"
  )
  ssh_robot_script_body REMOTE_ENV remote_env "$ROBOT_SBC_DIR/start_lift_bridge.sh"
}

cmd_nav2_rviz() {
  local -a nav_command=(
    "$SCRIPT_DIR/run_nav2_with_initial_pose.sh"
    --robot tb3_2 --domain "$DOMAIN" --map "$MAP"
    --delay 16 --repeat 10 --startup-retry 90
  )
  if [[ "$WITH_EKF" == "1" ]]; then
    nav_command+=(--with-ekf)
  fi
  shell_command cd "$ROOT"
  shell_export_assignment ROS_DOMAIN_ID "$DOMAIN"
  shell_export_assignment ROS_LOCALHOST_ONLY 0
  shell_export_assignment DISPLAY "$DISPLAY"
  shell_export_assignment WITH_EKF "$WITH_EKF"
  printf 'printf %s\\n '
  printf '%q\n' "[nav2-rviz] bringup 토픽 대기... (WITH_EKF=$WITH_EKF)"
  shell_command "$SCRIPT_DIR/wait_for_robot_topics.sh" "$DOMAIN" "$ROBOT_TOPIC_WAIT_SEC"
  printf '%s\n' "ec=\$?; (( ec == 0 )) || echo '[nav2-rviz] WARNING: odom/scan 미수신 — Nav2 계속 시도'"
  printf 'exec '
  shell_command "${nav_command[@]}"
}

# detector: SBC 카메라 토픽 대기 → ArUco detector (죽으면 자동 재시작)
cmd_detector2() {
  shell_command cd "$ROOT"
  shell_export_assignment ROS_DOMAIN_ID "$DOMAIN"
  shell_export_assignment DETECTOR_LOG "$LOG_DIR/detector2_tb3_2.log"
  local ros_setup_q
  printf -v ros_setup_q '%q' "$ROS_SETUP"
  printf 'source %s 2>/dev/null || true\n' "$ros_setup_q"
  cat <<'EOF'
export ROBOT_ID=tb3_burger_02
export ARUCO_MARKER_SIZE_M=0.055
export START_CAMERA_LAUNCH=0
export START_CAMERA_RELAY=1
set +e
echo "========================================"
echo "  detector2 (ArUco) — robot-camera 옆 pane"
printf '%s\n' "  log: $DETECTOR_LOG"
echo "========================================"
while true; do
  echo '[detector2] 카메라 /camera/image_raw/compressed 대기 중...'
  until timeout 4 ros2 topic echo /camera/image_raw/compressed --once --qos-reliability reliable >/dev/null 2>&1; do
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
  shell_command cd "$ROOT"
  printf 'exec '
  shell_command env SF_NAV_PROFILE=tb2-live "$SCRIPT_DIR/start_nav_servers.sh" foreground
}

cmd_status() {
  shell_command cd "$ROOT"
  shell_command sleep "$STATUS_DELAY_SEC"
  shell_command "$SCRIPT_DIR/start_all_tb3_2.sh" status
  printf '%s\n' 'echo'
  printf '%s\n' "echo '(재점검: scripts/start_all_tb3_2.sh status)'"
  shell_command exec bash
}

remote_stop_robot() {
  log "로봇 SBC bringup/카메라/lift 종료: $ROBOT_SSH"
  ssh_robot "bash -s" <"$ROBOT_SBC_DIR/stop_stack.sh" 2>/dev/null || \
    log "WARNING: 로봇 SBC ssh 종료 실패 (네트워크/비번 확인)"
}

stop_local_stack() {
  log "Nav PC 스택 종료 중..."
  env SF_NAV_PROFILE=tb2-live "$SCRIPT_DIR/start_nav_servers.sh" stop 2>/dev/null || true
  rm -f "$LOG_DIR/detector2_window.pid" 2>/dev/null || true
  sleep 3
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
  local name="$1" script="$2" script_q message_q
  printf -v script_q '%q' "$script"
  printf -v message_q '%q' "[$name] 종료됨 - Enter로 닫기"
  tmux new-window -t "$SESSION" -n "$name" \
    "bash $script_q; echo; printf '%s\\n' $message_q; read"
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
  local title="$1" script="$2" script_q message_q
  printf -v script_q '%q' "$script"
  printf -v message_q '%q' "[$title] 종료됨 - Enter로 닫기"
  gnome-terminal --title="$title" -- bash -lc "bash $script_q; echo; printf '%s\\n' $message_q; read" &
  sleep 1
}

prepare_robot_start() {
  preflight_robot_ssh
}

start_stack_tmux() {
  require_tmux
  tmux has-session -t "$SESSION" 2>/dev/null && die "이미 '$SESSION' 세션 있습니다. stop 먼저."
  prepare_robot_start
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
      "bash $(printf '%q' "$bringup_sh"); echo; printf '%s\\n' '[robot-bringup] 종료'; read"
    if [[ -n "$lift_sh" ]]; then
      new_win "robot-lift" "$lift_sh"
    fi
    new_win "robot-camera" "$camera_sh"
    new_win "detector2" "$detector_sh"
  else
    detector_sh="$(write_run_script detector2 "$(cmd_detector2)")"
    tmux new-session -d -s "$SESSION" -n "detector2" \
      "bash $(printf '%q' "$detector_sh"); echo; printf '%s\\n' '[detector2] 종료'; read"
  fi
  new_win "nav-servers" "$(write_run_script nav-servers "$(cmd_nav_servers)")"
  sleep 2
  new_win "nav2-rviz" "$(write_run_script nav2-rviz "$(cmd_nav2_rviz)")"
  new_win "status" "$(write_run_script status "$(cmd_status)")"
  log "attach: scripts/start_all_tb3_2.sh attach"
}

start_windows() {
  [[ -n "$TERM_BIN" ]] || die "gnome-terminal 필요"
  prepare_robot_start
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
  open_win "nav-servers" "$(write_run_script nav-servers "$(cmd_nav_servers)")"
  sleep 2
  open_win "nav2-rviz" "$(write_run_script nav2-rviz "$(cmd_nav2_rviz)")"
  open_win "status" "$(write_run_script status "$(cmd_status)")"
}

start_terminator() {
  [[ -n "$TERMINATOR_BIN" ]] || die "terminator 필요 (sudo apt install terminator)"
  prepare_robot_start
  if [[ "$WITH_ROBOT" == "1" ]]; then
    log "로봇 SBC 카메라 스크립트 배포"
    "$ROBOT_SBC_DIR/deploy_camera_to_sbc.sh" || die "카메라 스크립트 SBC 배포 실패"
  fi
  log "terminator split 시작 WITH_ROBOT=$WITH_ROBOT WITH_LIFT=$WITH_LIFT WITH_EKF=$WITH_EKF DOMAIN=$DOMAIN"

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
      printf '%s\n' "$body"
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
    add_pane "robot-bringup" "$(ssh_robot_bringup_body)"
    if [[ "$WITH_LIFT" == "1" ]]; then
      add_pane "robot-lift" "$(ssh_robot_lift_body)"
    fi
    add_pane "robot-camera" "$(ssh_robot_camera_body)"
    add_pane "detector2" "$(cmd_detector2)"
  else
    add_pane "detector2" "$(cmd_detector2)"
  fi
  add_pane "nav-servers" "$(cmd_nav_servers)"
  add_pane "nav2-rviz" "sleep 3; $(cmd_nav2_rviz)"
  add_pane "status" "$(cmd_status)"

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
    "    [[[robot_row]]]",
    "      type = HPaned",
    "      parent = left_col",
    "      order = 0",
    "      ratio = 0.34",
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

# robot stack (bringup / optional lift)
if "robot-bringup" in by_title:
    term("term_bringup", "robot_row", 0, "robot-bringup", need("robot-bringup"))
if "robot-lift" in by_title:
    term("term_lift", "robot_row", 1, "robot-lift", need("robot-lift"))

# vision row — camera | detector2 나란히 (카메라는 WITH_ROBOT일 때만)
if "robot-camera" in by_title:
    term("term_camera", "vision_row", 0, "robot-camera", need("robot-camera"))
term("term_detector", "vision_row", 1 if "robot-camera" in by_title else 0, "detector2", need("detector2"))

# right column
term("term_nav2", "right_col", 0, "nav2-rviz", need("nav2-rviz"))
term("term_navsrv", "nav_mid", 0, "nav-servers", need("nav-servers"))
term("term_status", "nav_mid", 1, "status", need("status"))

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
  terminator -m -u -g "$cfg" -l tb3_2 >"$tlog" 2>&1 &
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
  export ROS_DOMAIN_ID="$DOMAIN"

  printf '/odom 발행: '
  if timeout 5 ros2 topic echo /odom --once >/dev/null 2>&1; then echo "OK"
  else echo "없음 (bringup/OpenCR 확인)"; fi

  printf '/scan 발행: '
  if timeout 5 ros2 topic echo /scan --once >/dev/null 2>&1; then echo "OK"
  else echo "없음 (bringup/LDS 확인)"; fi

  printf 'odom->base_footprint TF: '
  if timeout 4 ros2 run tf2_ros tf2_echo odom base_footprint 2>/dev/null | head -1 | grep -q "At time"; then echo "OK"
  else echo "없음"; fi

  printf '카메라 /camera/image_raw/compressed: '
  if timeout 5 ros2 topic echo /camera/image_raw/compressed --once --qos-reliability reliable >/dev/null 2>&1; then echo "OK"
  else echo "없음 (카메라 pane 확인)"; fi

  printf 'ArUco /mission/tb3_2/aruco/detections: '
  aruco_pub=$(timeout 3 ros2 topic info /mission/tb3_2/aruco/detections 2>/dev/null | awk '/Publisher count:/ {print $3}' | head -1 || true)
  if [[ "${aruco_pub:-0}" -ge 1 ]]; then
    echo "OK (publisher=$aruco_pub)"
  else
    echo "없음 — detector2 pane 확인 (scripts/nav_ops.sh detector2)"
    if pgrep -f "aruco_detector_node.py" >/dev/null 2>&1; then
      echo "  (aruco_detector_node 프로세스는 있으나 publisher 미연결)"
    fi
  fi

  echo ""
  echo "===== Lift (DOMAIN=$DOMAIN) ====="
  lift_subs=$(timeout 4 ros2 topic info /lift/cmd_move 2>/dev/null | awk '/Subscription count:/ {print $3}' | head -1 || true)
  lift_pub=$(timeout 4 ros2 topic info /lift/position 2>/dev/null | awk '/Publisher count:/ {print $3}' | head -1 || true)
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
