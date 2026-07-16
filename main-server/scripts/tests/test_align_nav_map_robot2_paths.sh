#!/usr/bin/env bash
# Contract check: generated Nav instructions must be portable and fail closed.
set -euo pipefail

MAIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
REPO_ROOT="$(cd "$MAIN_ROOT/.." && pwd)"
SCRIPT="$MAIN_ROOT/scripts/align_nav_map_robot2.sh"
tmpdir="$(mktemp -d)"
trap 'rm -rf "$tmpdir"' EXIT

cat >"$tmpdir/curl" <<'EOF'
#!/usr/bin/env bash
set -euo pipefail
url="${!#}"
case "$url" in
  */api/v1/maps)
    printf '%s' '[{"map_id":"robot2_map","asset_status":"ok","runtime_map_id":"robot2_map"}]'
    ;;
  */api/v1/map-assets/robot2_map/map.yaml|*/api/v1/map-assets/robot2_map/map.pgm)
    ;;
  */movement-api/v1/map-state)
    ;;
  *)
    echo "unexpected curl URL: $url" >&2
    exit 1
    ;;
esac
EOF
chmod +x "$tmpdir/curl"

if PATH="$tmpdir:$PATH" MAIN_BASE=http://192.168.30.9:8088 NAV_HOST=smartfactory-nav.local "$SCRIPT" >/dev/null 2>&1; then
  echo 'alignment script unexpectedly accepted a direct Main IP' >&2
  exit 1
fi
if PATH="$tmpdir:$PATH" MAIN_BASE=http://smartfactory-main.local:8088 NAV_HOST=192.168.30.12 "$SCRIPT" >/dev/null 2>&1; then
  echo 'alignment script unexpectedly accepted a direct Nav IP' >&2
  exit 1
fi

output="$(PATH="$tmpdir:$PATH" MAIN_BASE=http://smartfactory-main.local:8088 NAV_PULL_BASE=http://smartfactory-main.local:8088 NAV_HOST=smartfactory-nav.local "$SCRIPT")"

[[ "$output" == *"MAP_DIR=\"$REPO_ROOT/nav-server/map\""* ]]
[[ "$output" == *'NAV_WORKSPACE="${NAV_WORKSPACE:-}"'* ]]
[[ "$output" == *'NAV_WORKSPACE is required: set it to the external Nav workspace'* ]]
[[ "$output" == *'cd "$NAV_WORKSPACE"'* ]]
[[ "$output" == *'"$NAV_WORKSPACE/scripts/start_nav_servers.sh" restart'* ]]
[[ "$output" != *'/home/lucas'* ]]

nav_instructions="$(printf '%s\n' "$output" | awk '
  /^set -euo pipefail$/ { collect = 1 }
  collect { print }
  /^# 기대:/ { exit }
')"
if missing_workspace_output="$(env -u NAV_WORKSPACE bash -c "$nav_instructions" 2>&1)"; then
  echo 'generated instructions unexpectedly accepted an unset NAV_WORKSPACE' >&2
  exit 1
fi
[[ "$missing_workspace_output" == *'NAV_WORKSPACE is required: set it to the external Nav workspace'* ]]

echo '[align_nav_map_robot2_paths] PASS'
