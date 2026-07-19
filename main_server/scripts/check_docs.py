"""책임: 추적 문서의 로컬 링크·경로 드리프트를 읽기 전용으로 검증한다.
비책임: 문서 수정, 외부 URL 가용성과 실행 코드 회귀."""

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
UX_TEST_ID_RE = re.compile(r"\btest\s*\(\s*[`\"]WEB-(\d{2})\b")
UX_DOC_ID_RE = re.compile(r"^## WEB-(\d{2})\b", re.MULTILINE)


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

    ux_spec = ROOT / "frontend/web/tests/e2e/ux-critical.spec.ts"
    ux_doc = ROOT / "docs/TEST_CASES.md"
    if ux_spec.is_file() and ux_doc.is_file():
        code_ids = set(UX_TEST_ID_RE.findall(ux_spec.read_text(encoding="utf-8")))
        doc_ids = set(UX_DOC_ID_RE.findall(ux_doc.read_text(encoding="utf-8")))
        if code_ids != doc_ids:
            missing = sorted(code_ids - doc_ids)
            stale = sorted(doc_ids - code_ids)
            errors.append(
                "UX case ID drift: "
                f"missing docs={missing or 'none'}, missing tests={stale or 'none'}"
            )
        if code_ids:
            expected = {f"{number:02d}" for number in range(1, max(map(int, code_ids)) + 1)}
            if code_ids != expected:
                errors.append(f"UX test IDs must be contiguous: found={sorted(code_ids)}")

    if errors:
        for error in sorted(set(errors)):
            print(f"[docs] ERROR: {error}", file=sys.stderr)
        return 1
    print(f"[docs] links, paths, and UX case IDs OK ({len(docs)} repository Markdown files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
