#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCOPE=""
while (($#)); do
  case "$1" in
    --repo-root) ROOT="$(cd "$2" && pwd)"; shift 2 ;;
    --scope) SCOPE="${2%/}"; shift 2 ;;
    *) echo "usage: $0 [--repo-root PATH] [--scope PATH]" >&2; exit 2 ;;
  esac
done

python3 - "$ROOT" "$SCOPE" <<'PY'
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

root = Path(sys.argv[1]).resolve()
scope = sys.argv[2]
matrix_path = root / "docs/documentation-path-matrix.json"
inventory_path = root / ".omx/specs/documentation-migration-inventory.json"
diagnostics: list[tuple[str, str, str]] = []


def emit(code: str, path: str, detail: str) -> None:
    diagnostics.append((code, path, detail))


def glob_regex(pattern: str) -> re.Pattern[str]:
    """Compile a repository glob where * never crosses a path segment."""
    result = "^"
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                index += 2
                if index < len(pattern) and pattern[index] == "/":
                    result += "(?:[^/]+/)*"
                    index += 1
                else:
                    result += ".*"
                continue
            result += "[^/]*"
        elif char == "?":
            result += "[^/]"
        else:
            result += re.escape(char)
        index += 1
    return re.compile(result + "$")


def matches(path: str, patterns: list[str]) -> bool:
    return any(glob_regex(pattern).fullmatch(path) for pattern in patterns)


required_rule_fields = {
    "rule_id", "document_type", "subject", "path_globs", "allowed_index_names",
    "requires_index", "required_markdown_metadata", "review_only_content_rule",
}
try:
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    if set(matrix) != {"schema_version", "conformance_version", "rules", "ignored_generated_globs"}:
        raise ValueError("unexpected top-level keys")
    if matrix["schema_version"] != "1.0" or not isinstance(matrix["conformance_version"], str):
        raise ValueError("unsupported schema or conformance version")
    rules = matrix["rules"]
    ignored = matrix["ignored_generated_globs"]
    if not isinstance(rules, list) or not rules or not isinstance(ignored, list):
        raise ValueError("rules and ignored_generated_globs must be non-empty lists")
    rule_ids: set[str] = set()
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict) or set(rule) != required_rule_fields:
            raise ValueError(f"rule {index} fields")
        if not all(isinstance(rule[name], str) and rule[name] for name in ("rule_id", "document_type", "subject", "review_only_content_rule")):
            raise ValueError(f"rule {index} string values")
        if rule["rule_id"] in rule_ids:
            raise ValueError(f"duplicate rule_id {rule['rule_id']}")
        rule_ids.add(rule["rule_id"])
        if not isinstance(rule["requires_index"], bool):
            raise ValueError(f"rule {index} requires_index")
        for name in ("path_globs", "allowed_index_names", "required_markdown_metadata"):
            if not isinstance(rule[name], list) or not rule[name] or not all(isinstance(value, str) and value for value in rule[name]):
                raise ValueError(f"rule {index} {name}")
        for pattern in rule["path_globs"]:
            glob_regex(pattern)
except Exception as exc:
    print(f"[docs] INVALID_MATRIX: {matrix_path}: {exc}", file=sys.stderr)
    raise SystemExit(1)

try:
    raw = subprocess.check_output(
        ["git", "-C", str(root), "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        stderr=subprocess.DEVNULL,
    )
except subprocess.CalledProcessError as exc:
    if not (root / ".git").exists():
        paths = [path.relative_to(root).as_posix() for path in root.rglob("*") if path.is_file()]
    else:
        print(f"[docs] GIT_INVENTORY_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
except OSError as exc:
    print(f"[docs] GIT_INVENTORY_FAILED: {exc}", file=sys.stderr)
    raise SystemExit(1)
else:
    paths = [item.decode() for item in raw.split(b"\0") if item]

markdown = sorted(
    path for path in paths
    if path.endswith(".md")
    and not matches(path, ignored)
    and (not scope or path == scope or path.startswith(scope + "/"))
)
rule_for_path: dict[str, dict] = {}
for rel in markdown:
    matching = [rule for rule in rules if matches(rel, rule["path_globs"])]
    if not matching:
        emit("UNKNOWN_MARKDOWN_PATH", rel, "path is not registered")
        continue
    if len(matching) > 1:
        emit("OVERLAPPING_RULES", rel, ",".join(rule["rule_id"] for rule in matching))
        continue
    rule = matching[0]
    rule_for_path[rel] = rule
    text = (root / rel).read_text(encoding="utf-8", errors="replace")
    if "h1" in rule["required_markdown_metadata"] and not re.search(r"(?m)^#\s+\S", text):
        emit("MISSING_TITLE", rel, "first-level title required")
    for target in re.findall(r"\[[^\]]+\]\(([^)]+\.md(?:#[^)]+)?)\)", text):
        target = target.split("#", 1)[0]
        if re.match(r"^[a-z]+://", target):
            continue
        resolved = ((root / rel).parent / target).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            emit("BROKEN_LINK", rel, target)
            continue
        if not resolved.is_file():
            emit("BROKEN_LINK", rel, target)

for rule in rules:
    if not rule["requires_index"]:
        continue
    selected = [path for path, owner in rule_for_path.items() if owner["rule_id"] == rule["rule_id"]]
    for directory in sorted({str(Path(path).parent) for path in selected}):
        if not any((root / directory / name).is_file() for name in rule["allowed_index_names"]):
            emit("MISSING_INDEX", directory, ",".join(rule["allowed_index_names"]))


def validate_inventory() -> None:
    # Scoped compatibility shims validate their document subset only. The root
    # invocation owns the repository-wide migration inventory contract.
    if scope or not inventory_path.exists():
        return
    fields = {
        "source_path", "source_sha256", "document_type", "subject", "action",
        "target_paths", "target_preconditions", "canonical_owner",
        "link_update_paths", "status",
    }
    actions = {"keep", "move", "delete", "link"}
    statuses = {"planned", "completed"}

    def safe_rel(rel: object) -> Path:
        if not isinstance(rel, str) or not rel or Path(rel).is_absolute():
            raise ValueError(f"unsafe path: {rel}")
        path = Path(rel)
        if path.as_posix() != rel or any(part in {"", ".", ".."} for part in path.parts):
            raise ValueError(f"non-canonical path: {rel}")
        absolute = Path(os.path.abspath(root / path))
        try:
            absolute.relative_to(root)
        except ValueError as exc:
            raise ValueError(f"path traversal: {rel}") from exc
        current = root
        for part in absolute.relative_to(root).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError(f"symlink path is not allowed: {rel}")
        return absolute

    def expected_digest(value: object, rel: str) -> str | None:
        if value == "absent":
            return None
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
            raise ValueError(f"invalid precondition for {rel}")
        return value

    try:
        data = json.loads(inventory_path.read_text(encoding="utf-8"))
        if set(data) != {"schema_version", "conformance_version", "entries"} or not isinstance(data["entries"], list):
            raise ValueError("invalid top-level fields")
        if data["schema_version"] != "1.0" or data["conformance_version"] != matrix["conformance_version"]:
            raise ValueError("version mismatch")
        sources: set[str] = set()
        mutations: set[str] = set()
        represented: set[str] = set()
        for index, entry in enumerate(data["entries"]):
            if not isinstance(entry, dict) or set(entry) != fields:
                raise ValueError(f"entry {index} fields")
            if entry["action"] == "split":
                raise ValueError("unsupported action: split")
            if entry["action"] not in actions or entry["status"] not in statuses:
                raise ValueError(f"entry {index} action/status")
            if not all(isinstance(entry[name], str) and entry[name] for name in ("document_type", "subject", "canonical_owner")):
                raise ValueError(f"entry {index} metadata")
            if not isinstance(entry["target_paths"], list) or not isinstance(entry["link_update_paths"], list):
                raise ValueError(f"entry {index} path lists")
            if not isinstance(entry["target_preconditions"], dict):
                raise ValueError(f"entry {index} preconditions")
            source = entry["source_path"]
            source_path = safe_rel(source)
            if Path(source).suffix.lower() != ".md" or not re.fullmatch(r"[0-9a-f]{64}", entry["source_sha256"]):
                raise ValueError(f"entry {index} source/digest")
            if source in sources:
                raise ValueError(f"duplicate source: {source}")
            sources.add(source)
            targets = entry["target_paths"]
            links = entry["link_update_paths"]
            if entry["action"] in {"move", "link"} and len(targets) != 1:
                raise ValueError(f"entry {index} requires exactly one target")
            if entry["action"] in {"keep", "delete"} and targets:
                raise ValueError(f"entry {index} targets unsupported for {entry['action']}")
            if links and (entry["action"] not in {"move", "link"} or len(targets) != 1):
                raise ValueError(f"entry {index} invalid link updates")
            affected = [*targets, *links]
            if len(affected) != len(set(affected)) or source in affected:
                raise ValueError(f"entry {index} path collision")
            if set(entry["target_preconditions"]) != set(affected):
                raise ValueError(f"entry {index} incomplete preconditions")
            for rel in affected:
                path = safe_rel(rel)
                if Path(rel).suffix.lower() != ".md":
                    raise ValueError(f"entry {index} non-Markdown target")
                wanted = expected_digest(entry["target_preconditions"][rel], rel)
                if rel in mutations:
                    raise ValueError(f"cross-entry mutation collision: {rel}")
                mutations.add(rel)
                if entry["status"] == "planned":
                    actual = hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
                    if actual != wanted:
                        raise ValueError(f"entry {index} target precondition mismatch: {rel}")
                    if path.is_file():
                        represented.add(rel)
            if entry["status"] == "planned" or entry["action"] == "keep":
                if not source_path.is_file() or hashlib.sha256(source_path.read_bytes()).hexdigest() != entry["source_sha256"]:
                    raise ValueError(f"entry {index} stale source digest")
                represented.add(source)
            else:
                if source_path.exists() or source_path.is_symlink():
                    raise ValueError(f"entry {index} completed source still exists")
                if entry["action"] in {"move", "link"}:
                    canonical = safe_rel(targets[0])
                    if not canonical.is_file() or hashlib.sha256(canonical.read_bytes()).hexdigest() != entry["source_sha256"]:
                        raise ValueError(f"entry {index} completed target mismatch")
                    represented.update(targets)
                    represented.update(links)
        collision = sources & mutations
        if collision:
            raise ValueError(f"source/target collision across entries: {sorted(collision)[0]}")
        if represented != set(markdown):
            raise ValueError("inventory does not cover current Markdown inventory")
    except Exception as exc:
        emit("INVALID_INVENTORY", inventory_path.relative_to(root).as_posix(), str(exc))


validate_inventory()
for code, path, detail in sorted(set(diagnostics)):
    print(f"[docs] {code}: {path}: {detail}", file=sys.stderr)
if diagnostics:
    raise SystemExit(1)
print(f'[docs] OK ({len(markdown)} Markdown files, scope={scope or "repository"})')
PY
