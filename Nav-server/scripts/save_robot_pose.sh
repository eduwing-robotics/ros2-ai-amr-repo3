#!/usr/bin/env bash
# 로봇 map pose를 파일에 저장 (재기동 시 initial pose 복원용)
#
# 사용:
#   scripts/save_robot_pose.sh tb3_1                 # :8001 health
#   scripts/save_robot_pose.sh tb3_2                 # :8002 health
#   scripts/save_robot_pose.sh tb3_1 --from-api
#   scripts/save_robot_pose.sh tb3_1 --x 0.5 --y 0.1 --yaw 1.57
#   scripts/save_robot_pose.sh all                   # 둘 다
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
POSE_DIR="${POSE_DIR:-$ROOT/logs/last_poses}"
mkdir -p "$POSE_DIR"

usage() {
  cat <<'EOF'
Usage:
  scripts/save_robot_pose.sh tb3_1|tb3_2|all [--from-api]
  scripts/save_robot_pose.sh tb3_1 --x X --y Y --yaw YAW
EOF
}

api_for_robot() {
  case "$1" in
    tb3_1) echo "${API1:-http://127.0.0.1:8001}" ;;
    tb3_2) echo "${API2:-http://127.0.0.1:8002}" ;;
    *) return 1 ;;
  esac
}

pose_file_for() {
  echo "$POSE_DIR/last_pose_${1}.json"
}

save_xyyaw() {
  local robot="$1" x="$2" y="$3" yaw="$4" source="${5:-manual}"
  local out
  out="$(pose_file_for "$robot")"
  python3 - "$out" "$robot" "$x" "$y" "$yaw" "$source" <<'PY'
import json, sys, datetime
out, robot, x, y, yaw, source = sys.argv[1:]
data = {
    "robot": robot,
    "x": float(x),
    "y": float(y),
    "yaw": float(yaw),
    "frame_id": "map",
    "source": source,
    "saved_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
with open(out, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2)
    f.write("\n")
print(f"[save_pose] {robot} -> {out}  ({data['x']:.3f}, {data['y']:.3f}, yaw={data['yaw']:.3f}) source={source}")
PY
}

save_from_api() {
  local robot="$1"
  local api
  api="$(api_for_robot "$robot")"
  local body
  body="$(curl -sf "$api/movement-api/v1/health")" || {
    echo "[save_pose] ERROR: health fail $api ($robot)" >&2
    return 1
  }
  python3 -c "
import json,sys
d=json.load(sys.stdin)
p=d.get('pose') or {}
for k in ('x','y','yaw'):
  if p.get(k) is None:
    raise SystemExit(f'missing pose.{k}')
print(p['x'], p['y'], p['yaw'])
" <<<"$body" | {
    read -r x y yaw
    save_xyyaw "$robot" "$x" "$y" "$yaw" "health_api"
  }
}

ROBOT="${1:-}"
[[ -n "$ROBOT" ]] || { usage; exit 2; }
shift || true

X=""; Y=""; YAW=""; FROM_API=0
while (($# > 0)); do
  case "$1" in
    --from-api) FROM_API=1; shift ;;
    --x) X="${2:-}"; shift 2 ;;
    --y) Y="${2:-}"; shift 2 ;;
    --yaw) YAW="${2:-}"; shift 2 ;;
    --x=*) X="${1#*=}"; shift ;;
    --y=*) Y="${1#*=}"; shift ;;
    --yaw=*) YAW="${1#*=}"; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown: $1" >&2; exit 2 ;;
  esac
done

save_one() {
  local robot="$1"
  if [[ -n "$X" && -n "$Y" && -n "$YAW" ]]; then
    save_xyyaw "$robot" "$X" "$Y" "$YAW" "cli"
  else
    save_from_api "$robot"
  fi
}

case "$ROBOT" in
  all)
    save_one tb3_1
    save_one tb3_2
    ;;
  tb3_1|tb3_2)
    save_one "$ROBOT"
    ;;
  *)
    echo "[save_pose] unknown robot: $ROBOT" >&2
    exit 2
    ;;
esac
