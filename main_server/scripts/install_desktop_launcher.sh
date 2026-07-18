#!/usr/bin/env bash
# 책임: 현재 checkout을 가리키는 사용자별 desktop launcher를 설치한다.
# 소유: desktop entry 파일. 비책임: 서버 실행 상태와 시스템 전역 설치.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NAME="서버 실행기.desktop"

desktop_dir="${XDG_DESKTOP_DIR:-}"
if [[ -z "$desktop_dir" && -f "${HOME}/.config/user-dirs.dirs" ]]; then
  # shellcheck disable=SC1090
  source "${HOME}/.config/user-dirs.dirs"
  desktop_dir="${XDG_DESKTOP_DIR:-}"
fi
desktop_dir="${desktop_dir/#\$HOME/$HOME}"
desktop_dir="${desktop_dir:-$HOME/Desktop}"

mkdir -p "$desktop_dir"
target="$desktop_dir/$NAME"

cat > "$target" <<EOF2
[Desktop Entry]
Type=Application
Name=LMS Real Server
Comment=Prepare dependencies and start LMS real FastAPI server with production UI
Path=$ROOT
Exec=$ROOT/scripts/launch_main_terminal.sh
Terminal=false
Categories=Development;
EOF2

chmod +x "$target"

if command -v gio >/dev/null 2>&1; then
  gio set "$target" metadata::trusted true >/dev/null 2>&1 || true
fi

echo "[launcher] installed: $target"
echo "[launcher] double-click it to prepare dependencies and start the real server."
