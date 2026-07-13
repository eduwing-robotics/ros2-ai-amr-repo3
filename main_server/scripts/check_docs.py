"""Validate tracked documentation links and repository path references."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]
LINK_RE = re.compile(r"(?<!!)\[[^]]*]\(([^)]+)\)")
PATH_RE = re.compile(
    r"`((?:backend|database|docs|frontend|scripts|tools)/[^`\n]+|(?:README|\.gitignore)[^`\n]*)`"
)
SKIP_MARKERS = ("*", "<", ">", "{", "}", "…", "|")


def repository_markdown() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "*.md"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return sorted(
        path
        for path in {ROOT / line for line in result.stdout.splitlines() if line}
        if path.is_file()
    )


def local_target(source: Path, raw: str) -> Path | None:
    target = raw.strip().split()[0].strip("<>")
    if not target or target.startswith(("#", "http://", "https://", "mailto:")):
        return None
    target = unquote(target.split("#", 1)[0])
    return (source.parent / target).resolve()


def main() -> int:
    errors: list[str] = []
    docs = repository_markdown()
    for source in docs:
        text = source.read_text(encoding="utf-8")
        for raw in LINK_RE.findall(text):
            target = local_target(source, raw)
            if target is not None and not target.exists():
                errors.append(f"broken link: {source.relative_to(ROOT)} -> {raw}")

        for line in text.splitlines():
            # Operations names paths that policy explicitly forbids recreating.
            if "다시 만들" in line:
                continue
            for raw in PATH_RE.findall(line):
                candidate = raw.rstrip("/.,:;)")
                if any(marker in candidate for marker in SKIP_MARKERS):
                    continue
                target = (ROOT / candidate).resolve()
                if not target.exists():
                    errors.append(
                        f"missing repository path: {source.relative_to(ROOT)} -> {raw}"
                    )

    if errors:
        for error in sorted(set(errors)):
            print(f"[docs] ERROR: {error}", file=sys.stderr)
        return 1
    print(f"[docs] links and repository paths OK ({len(docs)} repository Markdown files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
