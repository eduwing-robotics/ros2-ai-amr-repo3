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

output="$(PATH="$tmpdir:$PATH" MAIN_BASE=http://main.test NAV_PULL_BASE=http://main.test NAV_HOST=nav.test "$SCRIPT")"

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
