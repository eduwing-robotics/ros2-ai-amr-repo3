from __future__ import annotations

import json
import io
import os
import re
import subprocess
import tarfile
import zipfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
GATE = ROOT / "scripts/check_docs.sh"
CASES = json.loads(
    (ROOT / "tests/docs/fixtures/conformance-v1/cases.json").read_text(encoding="utf-8")
)["cases"]


def _matrix() -> dict:
    return {
        "schema_version": "1.0",
        "conformance_version": "1",
        "rules": [
            {
                "rule_id": "index",
                "document_type": "index",
                "subject": "docs",
                "path_globs": ["docs/README.md"],
                "allowed_index_names": ["README.md"],
                "requires_index": False,
                "required_markdown_metadata": ["h1"],
                "review_only_content_rule": "routing",
            },
            {
                "rule_id": "ops",
                "document_type": "operations",
                "subject": "docs",
                "path_globs": ["docs/operations/*.md"],
                "allowed_index_names": ["README.md"],
                "requires_index": True,
                "required_markdown_metadata": ["h1"],
                "review_only_content_rule": "procedures",
            },
        ],
        "ignored_generated_globs": [".omx/**", ".pytest_cache/**"],
    }


def _run_case(tmp_path: Path, case: dict) -> set[str]:
    repo = tmp_path / case["name"]
    (repo / "docs").mkdir(parents=True)
    (repo / "docs/documentation-path-matrix.json").write_text(
        json.dumps(_matrix()), encoding="utf-8"
    )
    for rel, content in case["files"].items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    proc = subprocess.run(
        [str(GATE), "--repo-root", str(repo)], text=True, capture_output=True
    )
    return set(re.findall(r"\[docs\] ([A-Z_]+):", proc.stderr))


def test_versioned_conformance_cases(tmp_path: Path) -> None:
    for case in CASES:
        assert _run_case(tmp_path, case) == set(case["expected_codes"]), case["name"]


def test_gate_rejects_overlapping_rules(tmp_path: Path) -> None:
    repo = tmp_path / "overlap"
    (repo / "docs").mkdir(parents=True)
    matrix = _matrix()
    duplicate = dict(matrix["rules"][0])
    duplicate["rule_id"] = "duplicate-index"
    matrix["rules"].append(duplicate)
    (repo / "docs/documentation-path-matrix.json").write_text(
        json.dumps(matrix), encoding="utf-8"
    )
    (repo / "docs/README.md").write_text("# Docs\n", encoding="utf-8")
    proc = subprocess.run(
        [str(GATE), "--repo-root", str(repo)], text=True, capture_output=True
    )
    assert proc.returncode == 1
    assert "OVERLAPPING_RULES" in proc.stderr


def test_gate_rejects_invalid_inventory(tmp_path: Path) -> None:
    repo = tmp_path / "inventory"
    (repo / "docs").mkdir(parents=True)
    (repo / ".omx/specs").mkdir(parents=True)
    (repo / "docs/documentation-path-matrix.json").write_text(
        json.dumps(_matrix()), encoding="utf-8"
    )
    (repo / "docs/README.md").write_text("# Docs\n", encoding="utf-8")
    (repo / ".omx/specs/documentation-migration-inventory.json").write_text(
        json.dumps({"schema_version": "1.0", "conformance_version": "1", "entries": [{"action": "split"}]}),
        encoding="utf-8",
    )
    proc = subprocess.run(
        [str(GATE), "--repo-root", str(repo)], text=True, capture_output=True
    )
    assert proc.returncode == 1
    assert "INVALID_INVENTORY" in proc.stderr


@pytest.mark.parametrize(
    "mutation",
    [
        {"action": "move", "target_paths": [], "target_preconditions": {}},
        {"action": "keep", "target_paths": ["docs/new.md"], "target_preconditions": {"docs/new.md": "absent"}},
        {"action": "move", "target_paths": ["../escape.md"], "target_preconditions": {"../escape.md": "absent"}},
        {"action": "move", "target_paths": ["docs/new.txt"], "target_preconditions": {"docs/new.txt": "absent"}},
        {"action": "move", "target_paths": ["docs/new.md"], "target_preconditions": {}},
    ],
)
def test_gate_rejects_transaction_unsafe_inventory(tmp_path: Path, mutation: dict) -> None:
    import hashlib

    repo = tmp_path / "unsafe-inventory"
    (repo / "docs").mkdir(parents=True)
    (repo / ".omx/specs").mkdir(parents=True)
    (repo / "docs/documentation-path-matrix.json").write_text(json.dumps(_matrix()))
    source = repo / "docs/README.md"
    source.write_text("# Docs\n")
    entry = {
        "source_path": "docs/README.md",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "document_type": "index",
        "subject": "docs",
        "action": "keep",
        "target_paths": [],
        "target_preconditions": {},
        "canonical_owner": "index",
        "link_update_paths": [],
        "status": "planned",
    }
    entry.update(mutation)
    (repo / ".omx/specs/documentation-migration-inventory.json").write_text(
        json.dumps({"schema_version": "1.0", "conformance_version": "1", "entries": [entry]})
    )
    proc = subprocess.run([str(GATE), "--repo-root", str(repo)], text=True, capture_output=True)
    assert proc.returncode == 1
    assert "INVALID_INVENTORY" in proc.stderr


def test_gate_rejects_symlink_inventory_paths(tmp_path: Path) -> None:
    import hashlib

    repo = tmp_path / "symlink-inventory"
    (repo / "docs").mkdir(parents=True)
    (repo / ".omx/specs").mkdir(parents=True)
    (repo / "docs/documentation-path-matrix.json").write_text(json.dumps(_matrix()))
    source = repo / "docs/README.md"
    source.write_text("# Docs\n")
    outside = tmp_path / "outside.md"
    outside.write_text("# Outside\n")
    (repo / "docs/alias.md").symlink_to(outside)
    entry = {
        "source_path": "docs/README.md",
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "document_type": "index",
        "subject": "docs",
        "action": "move",
        "target_paths": ["docs/alias.md"],
        "target_preconditions": {"docs/alias.md": hashlib.sha256(outside.read_bytes()).hexdigest()},
        "canonical_owner": "index",
        "link_update_paths": [],
        "status": "planned",
    }
    (repo / ".omx/specs/documentation-migration-inventory.json").write_text(
        json.dumps({"schema_version": "1.0", "conformance_version": "1", "entries": [entry]})
    )
    proc = subprocess.run([str(GATE), "--repo-root", str(repo)], text=True, capture_output=True)
    assert proc.returncode == 1
    assert "symlink path is not allowed" in proc.stderr
    assert outside.read_text() == "# Outside\n"


def test_gate_is_independent_of_local_skill(tmp_path: Path) -> None:
    env_home = tmp_path / "empty-codex-home"
    env_home.mkdir()
    proc = subprocess.run(
        [str(GATE)], cwd=ROOT, env={"PATH": "/usr/bin:/bin", "CODEX_HOME": str(env_home)},
        text=True, capture_output=True
    )
    assert proc.returncode == 0, proc.stderr


def test_installed_engine_conformance_parity(tmp_path: Path) -> None:
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    engine = codex_home / "skills/docs-governance/scripts/docs_governance.py"
    if not engine.is_file():
        pytest.skip("external docs-governance skill is intentionally not a repo dependency")
    for case in CASES:
        repo = tmp_path / "parity" / case["name"]
        (repo / "docs").mkdir(parents=True)
        (repo / "docs/documentation-path-matrix.json").write_text(
            json.dumps(_matrix()), encoding="utf-8"
        )
        for rel, content in case["files"].items():
            path = repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        gate_codes = _run_case(tmp_path / "gate-parity", case)
        proc = subprocess.run(
            ["python3", str(engine), "--repo-root", str(repo), "audit"],
            text=True, capture_output=True,
        )
        engine_codes = {item["code"] for item in json.loads(proc.stdout)["diagnostics"]}
        assert gate_codes == engine_codes == set(case["expected_codes"]), case["name"]


def test_gate_fails_when_git_inventory_fails(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / ".git").mkdir()
    (repo / "docs/documentation-path-matrix.json").write_text(
        json.dumps(_matrix()), encoding="utf-8"
    )
    (repo / "docs/README.md").write_text("# Docs\n", encoding="utf-8")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_git = fake_bin / "git"
    fake_git.write_text("#!/usr/bin/env bash\nexit 23\n", encoding="utf-8")
    fake_git.chmod(0o755)

    proc = subprocess.run(
        [str(GATE), "--repo-root", str(repo)],
        env={"PATH": f"{fake_bin}:/usr/bin:/bin"},
        text=True,
        capture_output=True,
    )

    assert proc.returncode == 1
    assert "GIT_INVENTORY_FAILED" in proc.stderr


def test_main_checkers_are_policy_free_shims() -> None:
    for relative_path in (
        "main-server/scripts/check_docs.sh",
        "main-server/scripts/tests/check_docs.sh",
    ):
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        assert "documentation-path-matrix" not in text
        assert text.rstrip().endswith(
            'exec "$ROOT/scripts/check_docs.sh" --scope main-server'
        )


def _git_paths(repo: Path) -> list[str]:
    raw = subprocess.check_output(
        ["git", "-C", str(repo), "ls-files", "--cached", "--others", "--exclude-standard", "-z"]
    )
    return [item.decode() for item in raw.split(b"\0") if item]


def _archive_members(data: bytes, name: str) -> list[str]:
    try:
        if name.endswith((".zip", ".whl")):
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                return archive.namelist()
        if name.endswith((".tar", ".tar.gz", ".tgz")):
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:*") as archive:
                return archive.getnames()
    except (tarfile.TarError, zipfile.BadZipFile):
        return []
    return []


def _skill_leaks(repo: Path, skill_dir: Path) -> list[str]:
    leaks = []
    skill_real = skill_dir.resolve()
    staged = subprocess.check_output(["git", "-C", str(repo), "ls-files", "--stage", "-z"])
    modes = {}
    for record in staged.split(b"\0"):
        if record:
            metadata, rel = record.decode().split("\t", 1)
            modes[rel] = metadata.split()[0]
    for rel in _git_paths(repo):
        parts = Path(rel).parts
        if "docs-governance" in parts:
            leaks.append(rel)
        path = repo / rel
        if path.is_symlink():
            try:
                path.resolve().relative_to(skill_real)
            except (ValueError, RuntimeError):
                pass
            else:
                leaks.append(f"symlink:{rel}")
        data = None
        if rel in modes:
            data = subprocess.check_output(["git", "-C", str(repo), "show", f":{rel}"])
            if modes[rel] == "120000":
                target = (path.parent / data.decode()).resolve()
                try:
                    target.relative_to(skill_real)
                except ValueError:
                    pass
                else:
                    leaks.append(f"staged-symlink:{rel}")
        elif path.is_file():
            data = path.read_bytes()
        if data is not None and any("docs-governance" in Path(member).parts for member in _archive_members(data, rel)):
            leaks.append(f"archive:{rel}")
    return sorted(set(leaks))


def test_no_skill_package_artifact_in_repository() -> None:
    codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
    skill_dir = codex_home / "skills/docs-governance"
    assert not _skill_leaks(ROOT, skill_dir)
    if not skill_dir.is_dir():
        pytest.skip("external docs-governance skill is intentionally not a repo dependency")
    manifest = json.loads((skill_dir / "package-manifest.json").read_text(encoding="utf-8"))
    for entry in manifest["files"]:
        path = skill_dir / entry["path"]
        assert path.is_file()
        import hashlib
        assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]


def test_skill_leak_proof_catches_index_symlink_and_archive(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    skill = tmp_path / "external/docs-governance"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text("# Skill\n", encoding="utf-8")

    (repo / "tracked-link").symlink_to(skill / "SKILL.md")
    subprocess.run(["git", "-C", str(repo), "add", "tracked-link"], check=True)
    with zipfile.ZipFile(repo / "payload.zip", "w") as archive:
        archive.writestr("docs-governance/SKILL.md", "# Skill\n")
    subprocess.run(["git", "-C", str(repo), "add", "payload.zip"], check=True)
    (repo / "payload.zip").unlink()  # prove archive inspection reads the staged blob
    (repo / "docs-governance").mkdir()
    (repo / "docs-governance/unstaged.md").write_text("# Leak\n", encoding="utf-8")

    assert _skill_leaks(repo, skill) == [
        "archive:payload.zip",
        "docs-governance/unstaged.md",
        "staged-symlink:tracked-link",
        "symlink:tracked-link",
    ]
