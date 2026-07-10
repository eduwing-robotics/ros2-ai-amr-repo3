#!/usr/bin/env bash
# lift_project 프리셋(0/6/43/50mm) 기준으로 높이 실측.
# 참고: ~/Downloads/lift_project — teleop PRESETS 1=home 2=6 3=43 4=50
#
# Usage:
#   export ROS_DOMAIN_ID=5
#   bash scripts/run_lift_preset_experiment.sh
#   bash scripts/run_lift_preset_experiment.sh --skip-home
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
ROS_SETUP="${ROS_SETUP:-/opt/ros/jazzy/setup.bash}"
DOMAIN="${ROS_DOMAIN_ID:-5}"
LOG="${LIFT_EXPERIMENT_LOG:-$ROOT/logs/lift_preset_experiment_$(date +%Y%m%d_%H%M%S).log}"
SKIP_HOME=0
WAIT_SEC="${LIFT_MOVE_WAIT_SEC:-15}"

for arg in "$@"; do
  case "$arg" in
    --skip-home) SKIP_HOME=1 ;;
    -h|--help)
      sed -n '2,12p' "$0"
      exit 0
      ;;
  esac
done

source_ros() {
  set +u
  # shellcheck source=/dev/null
  source "$ROS_SETUP"
  set -u
  export ROS_DOMAIN_ID="$DOMAIN"
}

read_position() {
  timeout 6 ros2 topic echo /lift/position --once 2>/dev/null \
    | awk '/^data:/ {gsub(/data: /,""); print; exit}'
}

read_direction() {
  timeout 4 ros2 topic echo /lift/direction --once 2>/dev/null \
    | awk '/^data:/ {gsub(/data: . /,""); gsub(/"/,""); print; exit}'
}

move_mm() {
  local target="$1"
  echo "[lift_exp] cmd_move -> ${target}mm"
  ros2 topic pub --once /lift/cmd_move std_msgs/msg/Float32 "{data: ${target}}" >/dev/null
}

home_lift() {
  echo "[lift_exp] cmd_home"
  ros2 topic pub --once /lift/cmd_home std_msgs/msg/Bool "{data: true}" >/dev/null
}

wait_settle() {
  local target="$1"
  local deadline=$((SECONDS + WAIT_SEC))
  local last=""
  while (( SECONDS < deadline )); do
    local pos dir
    pos="$(read_position || true)"
    dir="$(read_direction || true)"
    if [[ -n "$pos" && "$dir" == "STOP" ]]; then
      if [[ -n "$last" && "$last" == "$pos" ]]; then
        printf '%s\n' "$pos"
        return 0
      fi
      last="$pos"
    fi
    sleep 0.5
  done
  read_position || echo "?"
}

check_bridge() {
  local subs
  subs=$(timeout 5 ros2 topic info /lift/cmd_move 2>/dev/null | awk '/Subscription count:/ {print $3; exit}')
  if [[ "${subs:-0}" -ge 1 ]]; then
    return 0
  fi
  echo "FATAL: lift_bridge 없음 (domain $DOMAIN). SBC에서:" >&2
  echo "  ros2 run lift_bridge lift_bridge" >&2
  return 1
}

mkdir -p "$(dirname "$LOG")"
{
  echo "===== lift preset experiment $(date -Is) domain=$DOMAIN ====="
  echo "reference: lift_project PRESETS home=0 6 43 50 mm"
  echo ""

  source_ros
  check_bridge

  declare -a TARGETS=(6 43 50)
  if (( SKIP_HOME == 0 )); then
    home_lift
    pos="$(wait_settle 0)"
    echo "HOME -> reported ${pos}mm"
    echo ""
  fi

  for mm in "${TARGETS[@]}"; do
    move_mm "$mm"
    pos="$(wait_settle "$mm")"
    err=$(python3 -c "print(f'{(float('$pos') - float($mm)):.1f}')" 2>/dev/null || echo "?")
    echo "TARGET ${mm}mm -> reported ${pos}mm (delta ${err}mm)"
    echo ""
    sleep 1
  done

  echo "===== mapping to dock_transfer (inbound2 L1 -> B L2) ====="
  echo "  1F pickup (load L1)     -> load_height_mm   ~= preset 3 (43mm)"
  echo "  2F travel (carry)       -> carry_height_mm  ~= preset 4 (50mm)"
  echo "  2F unload (after insert)-> unload_height_mm ~= preset 2 (6mm) or lower"
  echo "  2F shelf entry          -> pre_insert_mm    ~= preset 4 (50mm)"
  echo ""
  echo "log: $LOG"
} 2>&1 | tee "$LOG"
