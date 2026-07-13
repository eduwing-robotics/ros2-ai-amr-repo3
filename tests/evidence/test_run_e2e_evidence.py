from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "run-e2e-evidence.py"


def run_harness(tmp_path: Path, provenance: str, *command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--provenance",
            provenance,
            "--output-root",
            str(tmp_path),
            "--run-id",
            "test-run",
            "--",
            *command,
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_synthetic_hil_bundle_is_explicit_and_hash_bound(tmp_path: Path) -> None:
    result = run_harness(
        tmp_path,
        "synthetic-hil",
        sys.executable,
        "-c",
        "import sys; print('main-nav-ai-ros'); print('lift fixture', file=sys.stderr)",
    )
    assert result.returncode == 0, result.stderr
    bundle = tmp_path / "test-run"
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["provenance"] == "synthetic-hil"
    assert manifest["synthetic_hil"] is True
    assert manifest["physical_system_verified"] is False
    assert manifest["lift"] == {
        "evidence_attached": False,
        "physical_verified": False,
        "status": "PHYSICAL_LIFT_NOT_VERIFIED",
    }
    assert manifest["limitations"] == ["PHYSICAL_LIFT_NOT_VERIFIED"]
    assert set(manifest["repository"]) == {"commit", "dirty"}
    assert manifest["result"] == "PASS"
    for name in ("stdout.log", "stderr.log"):
        expected = hashlib.sha256((bundle / name).read_bytes()).hexdigest()
        assert manifest["artifacts"][name]["sha256"] == expected


def test_failed_command_still_emits_fail_evidence(tmp_path: Path) -> None:
    result = run_harness(tmp_path, "simulation", sys.executable, "-c", "raise SystemExit(7)")
    assert result.returncode == 7
    manifest = json.loads((tmp_path / "test-run" / "manifest.json").read_text())
    assert manifest["exit_code"] == 7
    assert manifest["result"] == "FAIL"
    assert manifest["lift"]["status"] == "PHYSICAL_LIFT_NOT_VERIFIED"


def test_nonphysical_run_rejects_physical_lift_evidence(tmp_path: Path) -> None:
    evidence = tmp_path / "lift.txt"
    evidence.write_text("operator evidence", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--provenance",
            "simulation",
            "--physical-lift-evidence",
            str(evidence),
            "--",
            "true",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 2
    assert "valid only with --provenance physical" in result.stderr


def test_manifest_redacts_sensitive_command_arguments(tmp_path: Path) -> None:
    result = run_harness(
        tmp_path,
        "physical",
        sys.executable,
        "-c",
        "pass",
        "--token",
        "do-not-record",
        "--api-key=also-secret",
    )
    assert result.returncode == 0, result.stderr
    manifest_text = (tmp_path / "test-run" / "manifest.json").read_text()
    assert "do-not-record" not in manifest_text
    assert "also-secret" not in manifest_text
    assert manifest_text.count("[REDACTED]") == 2
