#!/usr/bin/env bash
# Documentation structure and style checks.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

fail=0
err() { echo "[docs] ERROR: $*" >&2; fail=1; }
# WARN 은 비차단(리뷰 넛지)이다. exit code 에 영향을 주지 않는다.
warn() { echo "[docs] WARN: $*" >&2; }

# Root markdown policy. Git's inventory includes tracked files and unignored
# working-tree files, but excludes generated ignored caches.
while IFS= read -r -d '' file; do
  [[ "$file" == *.md ]] || continue
  case "$file" in
    database/legacy/*|ref/*|slides/*) continue ;;
  esac
  case "$file" in
    README.md|AGENTS.md) ;;
    docs/*|worklog/*) ;;
    *) err "Markdown file outside allowed roots: $file" ;;
  esac
done < <(git ls-files --cached --others --exclude-standard -z)


while IFS= read -r file; do
  case "$file" in
    docs/README.md|docs/DOCUMENTATION_GUIDE.md) ;;
    *) err "Markdown file directly under docs/ is not allowed: $file" ;;
  esac
done < <(find docs -maxdepth 1 -name '*.md' -type f -print)

required_meta=("상태:" "소유:" "최종 갱신:" "목적:")
should_check_meta() {
  case "$1" in
    ./docs/README.md|./docs/DOCUMENTATION_GUIDE.md) return 0 ;;
    ./docs/ui-ux/*|./docs/api/*|./docs/interfaces/*|./docs/architecture/*|./docs/operations/*|./docs/decisions/*|./docs/contributing/*|./docs/assets/*) return 0 ;;
    ./worklog/*) return 0 ;;
    *) return 1 ;;
  esac
}

allow_long_doc() {
  case "$1" in
    # long worklog phase logs (historical); docs/ has no length exemption
    worklog/phases/PHASE_05_INBOUND_OUTBOUND_AUTOMATION.md|worklog/phases/PHASE_06_MOVEMENT_SYNC_DIAGNOSTICS.md|worklog/phases/PHASE_47_DEBUG_FIX_RECOMMENDATIONS_AND_TELEOP_TEST.md) return 0 ;;
    *) return 1 ;;
  esac
}

skip_timestamp_check() {
  case "$1" in
    *) return 1 ;;
  esac
}

while IFS= read -r file; do
  case "$file" in
    ./README.md|./AGENTS.md) continue ;;
  esac
  should_check_meta "$file" || continue
  head -n 12 "$file" | grep -q '^# ' || err "Missing title heading: $file"
  for meta in "${required_meta[@]}"; do
    head -n 12 "$file" | grep -q "$meta" || err "Missing metadata '$meta' in $file"
  done
  updated_line=$(head -n 12 "$file" | grep '^최종 갱신:' || true)
  if [[ -n "$updated_line" ]] && ! skip_timestamp_check "$file"; then
    if ! grep -Eq '^최종 갱신: ([0-9]{4})-([0-9]{2})-([0-9]{2}) ([0-9]{2}):([0-9]{2}) KST$|^최종 갱신: YYYY-MM-DD HH:MM KST$' <<< "$updated_line"; then
      err "Invalid updated timestamp format in $file: expected YYYY-MM-DD HH:MM KST"
    fi
  fi
done < <(find docs worklog -name '*.md' -type f -print 2>/dev/null | sed 's#^#./#')

while IFS= read -r file; do
  base="$(basename "$file")"
  case "$file" in
    *) [[ "$base" =~ \([0-9]+\) ]] && err "Copy suffix is not allowed: $file" ;;
  esac
done < <(find docs worklog -name '*.md' -type f -print 2>/dev/null | sed 's#^#./#')

check_limit() {
  local dir="$1" glob="$2" limit="$3"
  [[ -d "$dir" ]] || return 0
  while IFS= read -r file; do
    [[ -e "$file" ]] || continue
    local lines
    lines=$(wc -l < "$file")
    if (( lines > limit )) && ! allow_long_doc "$file"; then
      err "Line limit exceeded ($lines > $limit): $file"
    fi
  done < <(find "$dir" -maxdepth 1 -name "$glob" -type f -print)
}

# 상세 스펙·파운데이션 영역 300 / 페이지·운영 180 / api·contributing 220 / decisions 140
check_limit 'docs/ui-ux' '*.md' 300
check_limit 'docs/ui-ux/features' '*.md' 180
check_limit 'docs/ui-ux/pages' '*.md' 180
check_limit 'docs/api' '*.md' 280
check_limit 'docs/interfaces' '*.md' 300
check_limit 'docs/interfaces/movement' '*.md' 300
check_limit 'docs/architecture' '*.md' 300
check_limit 'docs/architecture/db' '*.md' 300
check_limit 'docs/operations' '*.md' 180
check_limit 'docs/decisions' '*.md' 140
check_limit 'docs/contributing' '*.md' 220
check_limit 'docs/contributing/templates' '*.md' 220
check_limit 'docs/assets' '*.md' 120
check_limit 'worklog/phases' '*.md' 180
check_limit 'worklog/sessions' '*.md' 120
check_limit 'worklog/handoff' '*.md' 180

# --- 커플링 drift 리포터 (비차단 WARN) ---
check_drift() {
  local doc="$1"; shift
  [[ -f "$doc" ]] || return 0
  local dirs=() d
  for d in "$@"; do [[ -e "$d" ]] && dirs+=("$d"); done
  (( ${#dirs[@]} )) || return 0
  local newer
  newer=$(find "${dirs[@]}" -type f \
      -not -path '*/node_modules/*' -not -path '*/dist/*' \
      -not -path '*/__pycache__/*' -not -path '*/.venv/*' -not -path '*/.omx/*' \
      -newer "$doc" -print -quit 2>/dev/null)
  if [[ -n "$newer" ]]; then
    warn "$doc 검토 필요 — 대상 코드가 더 최근에 변경됨 (예: ${newer#./})"
  fi
}

check_drift docs/ui-ux/FRONTEND.md frontend/web/src
check_drift docs/api/API_MAIN.md backend/app/api
check_drift docs/architecture/db/README.md database backend/app/db
check_drift docs/architecture/BACKEND.md backend/app/services backend/app/core

# --- 시각자료 넛지 (비차단 WARN) — 영역 landing README 는 다이어그램 권장 ---
while IFS= read -r file; do
  case "$file" in docs/assets/*|docs/contributing/templates/*) continue ;; esac
  grep -q '```mermaid' "$file" || grep -q '!\[' "$file" || warn "$file — 영역 개요에 다이어그램(mermaid/이미지) 권장"
done < <(find docs -mindepth 2 -maxdepth 2 -name 'README.md' -type f -print)

if (( fail )); then
  exit 1
fi
echo "[docs] OK"
