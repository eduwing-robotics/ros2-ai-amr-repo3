#!/usr/bin/env python3
"""Audit deploy package for SmartFactory-root-only command/path references."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TEXT_SUFFIXES = {".md", ".py", ".sh", ".txt", ".yml", ".yaml", ".json", ".env", ".example"}
FORBIDDEN = [
    re.compile(r"services/ai-server"),
    re.compile(r"docker-compose\.ai-server\.yml"),
    re.compile(r"/app/services/ai-server"),
    re.compile(r"/home/codelab/yolo_test"),
    re.compile(r"\.omx"),
    re.compile(r"omx_wiki"),
]
ALLOW = {
    "docs/deploy-inventory.md",  # source inventory intentionally names historical source paths
    "scripts/validate/self_containment_audit.py",  # this audit declares the forbidden patterns
}


def is_text_file(path: Path) -> bool:
    if path.name in {
        ".env.example",
        ".gitignore",
        ".pre-commit-config.yaml",
        ".markdownlint-cli2.yaml",
    }:
        return True
    return path.suffix in TEXT_SUFFIXES


def main() -> None:
    failures: list[str] = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file() or any(
            part.startswith(".venv") for part in path.relative_to(ROOT).parts
        ):
            continue
        rel = path.relative_to(ROOT).as_posix()
        if rel in ALLOW or not is_text_file(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in FORBIDDEN:
            if pattern.search(text):
                failures.append(f"{rel}: forbidden pattern {pattern.pattern}")
    if failures:
        raise SystemExit("Self-containment audit failed:\n" + "\n".join(failures))
    print("Self-containment audit passed.")


if __name__ == "__main__":
    main()
