#!/usr/bin/env bash
# Nav2 active map을 robot2_map으로 맞추기 위한 Main-side 준비·검증·Nav 콘솔 안내.
#
# Movement API에는 map switch 엔드포인트가 없다. Nav PC 콘솔에서 map 파일 배치 +
# ACTIVE_MAP_YAML 변경 + nav 서버 재시작이 필요하다.
#
# Main에서 할 수 있는 것:
#   1) robot2_map 자산·다운로드 URL 확인
#   2) Nav 적용 후 단일 맵 asset/runtime 정합성 검증 안내
#
# 사용법:
#   ./tools/nav2/align_robot2_map.sh
#   MAIN_BASE=http://smartfactory-main.local:8088 NAV_HOST=<nav-host-or-ip> NAV_WORKSPACE=/home/robot/slam_nav_ws ./tools/nav2/align_robot2_map.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
MAIN_BASE="${MAIN_BASE:-http://localhost:8088}"
NAV_PULL_BASE="${NAV_PULL_BASE:-${LMS_PUBLIC_BASE_URL:-http://smartfactory-main.local:8088}}"
API_BASE="${MAIN_BASE%/}/api/v1"
NAV_HOST="${NAV_HOST:-smartfactory-nav.local}"
TARGET_MAP="${TARGET_MAP:-robot2_map}"
NAV_WORKSPACE="${NAV_WORKSPACE:-<nav-workspace>}"
NAV_MAP_DIR="${NAV_MAP_DIR:-${NAV_WORKSPACE%/}/map}"
PY="${PYTHON:-python3}"

fail() { echo "[align-nav] FAIL: $*" >&2; exit 1; }
pass() { echo "[align-nav] OK: $*"; }
warn() { echo "[align-nav] WARN: $*"; }
info() { echo "[align-nav] $*"; }

need_cmd() { command -v "$1" >/dev/null 2>&1 || fail "$1 is required"; }
need_cmd curl
need_cmd "$PY"

info "MAIN_BASE=$MAIN_BASE NAV_HOST=$NAV_HOST TARGET_MAP=$TARGET_MAP"

# --- Main: robot2_map 자산 확인 ---
maps_json="$(curl -fsS "$API_BASE/maps")" || fail "cannot reach $API_BASE/maps"
has_target="$(printf '%s' "$maps_json" | "$PY" -c "
import json,sys
maps=json.load(sys.stdin)
print('yes' if any(m.get('map_id')=='$TARGET_MAP' for m in maps) else 'no')
")"
[[ "$has_target" == "yes" ]] || fail "Main maps folder has no active map_id=$TARGET_MAP"

curl -fsS "$API_BASE/map-assets/$TARGET_MAP/map.yaml" >/dev/null || fail "map.yaml download missing for $TARGET_MAP"
curl -fsS "$API_BASE/map-assets/$TARGET_MAP/map.pgm" >/dev/null || fail "map.pgm download missing for $TARGET_MAP"
pass "Main serves $TARGET_MAP map.yaml + map.pgm"

asset_status="$(printf '%s' "$maps_json" | "$PY" -c "
import json,sys
maps=json.load(sys.stdin)
m=next(x for x in maps if x.get('map_id')=='$TARGET_MAP')
print(m.get('asset_status',''))
runtime=m.get('runtime_map_id','')
print('runtime='+runtime, file=sys.stderr)
")"
runtime_map="$(printf '%s' "$maps_json" | "$PY" -c "
import json,sys
m=next(x for x in json.load(sys.stdin) if x.get('map_id')=='$TARGET_MAP')
print(m.get('runtime_map_id',''))
")"

info "current asset_status=$asset_status runtime_map_id=$runtime_map (target=$TARGET_MAP)"

# --- Movement: 현재 active map ---
nav_state="$(curl -fsS "http://${NAV_HOST}:8002/movement-api/v1/map-state" 2>/dev/null || true)"
if [[ -z "$nav_state" ]]; then
  warn "cannot reach Movement map-state on :8002 — Nav 적용 후 직접 확인"
else
  active="$(printf '%s' "$nav_state" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("active_map_id",""))')"
  yaml_path="$(printf '%s' "$nav_state" | "$PY" -c 'import json,sys; print(json.load(sys.stdin).get("map_yaml",""))')"
  info "Movement active_map_id=$active map_yaml=$yaml_path"
  if [[ "$active" == "$TARGET_MAP" ]]; then
    pass "Movement already reports active_map_id=$TARGET_MAP"
    info "Run on Main: curl -X POST $API_BASE/maps/import-folder"
    info "Then verify: curl $API_BASE/maps | jq '.[] | select(.map_id==\"$TARGET_MAP\") | .asset_status'"
    exit 0
  fi
fi

echo
echo "=== Feasibility ==="
echo "- Movement → $TARGET_MAP: Nav PC 콘솔 작업 필요 (SSH/API map-switch 없음)"
echo "- Main robot2_map 자산: 준비 완료 (다운로드 URL 사용 가능)"
echo "- Nav 재시작 후 initial pose / localization 재확인 필요 (map origin·해상도 변경)"
echo
echo "=== Nav PC에서 실행 (smartfactory-nav 콘솔) ==="
cat <<EOF
set -euo pipefail
MAP_DIR="$NAV_MAP_DIR"
MAIN="$NAV_PULL_BASE"
TARGET="$TARGET_MAP"

sudo mkdir -p "\$MAP_DIR"
curl -fsS "\$MAIN/api/v1/map-assets/\$TARGET/map.yaml" -o "\$MAP_DIR/\$TARGET.yaml"
curl -fsS "\$MAIN/api/v1/map-assets/\$TARGET/map.pgm" -o "\$MAP_DIR/\$TARGET.pgm"

# Nav2 / Movement launch에서 ACTIVE_MAP_YAML 또는 map_server yaml 경로를 아래로 변경:
#   \$MAP_DIR/\$TARGET.yaml
# 예: scripts/start_nav_servers.sh / launch 파일의 default map 경로 수정

cd "$NAV_WORKSPACE"
scripts/start_nav_servers.sh restart   # 또는 현장 restart 절차

# tb3_1 (:8001) 과 tb3_2 (:8002) 모두 확인:
curl -s "http://${NAV_HOST}:8001/movement-api/v1/map-state" | jq '.active_map_id,.width,.height,.resolution'
curl -s "http://${NAV_HOST}:8002/movement-api/v1/map-state" | jq '.active_map_id,.width,.height,.resolution'
# 기대: active_map_id="$TARGET_MAP", width=111, height=112, resolution=0.02
EOF
echo
echo "=== Nav 적용 후 Main에서 실행 ==="
cat <<EOF
curl -X POST $API_BASE/maps/import-folder
curl $API_BASE/maps
# robot2_map asset_status 가 ok 이고 runtime_map_id 가 robot2_map 이면 완료
EOF
