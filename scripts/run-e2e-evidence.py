#!/usr/bin/env python3
"""Run an E2E command and emit a provenance-bound evidence bundle."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import uuid


PROVENANCE_KINDS = ("physical", "simulation", "synthetic-hil")
NOT_VERIFIED = "PHYSICAL_LIFT_NOT_VERIFIED"
SENSITIVE_ARGUMENT_MARKERS = ("secret", "token", "password", "api-key", "apikey")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_provenance() -> dict[str, object]:
    def git(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["git", *args], text=True, capture_output=True, check=False
        )

    revision = git("rev-parse", "HEAD")
    status = git("status", "--porcelain", "--untracked-files=normal")
    return {
        "commit": revision.stdout.strip() if revision.returncode == 0 else None,
        "dirty": bool(status.stdout.strip()) if status.returncode == 0 else None,
    }


def redacted_command(command: list[str]) -> list[str]:
    redacted: list[str] = []
    redact_next = False
    for argument in command:
        if redact_next:
            redacted.append("[REDACTED]")
            redact_next = False
            continue
        lowered = argument.lower()
        if argument.startswith("-") and any(marker in lowered for marker in SENSITIVE_ARGUMENT_MARKERS):
            if "=" in argument:
                redacted.append(argument.split("=", 1)[0] + "=[REDACTED]")
            else:
                redacted.append(argument)
                redact_next = True
            continue
        redacted.append(argument)
    return redacted


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Capture repeatable E2E logs without upgrading simulated evidence to physical evidence."
    )
    parser.add_argument("--provenance", required=True, choices=PROVENANCE_KINDS)
    parser.add_argument("--output-root", type=Path, default=Path("e2e-evidence"))
    parser.add_argument("--run-id", help="Stable caller-provided identifier (default: UUID).")
    parser.add_argument(
        "--physical-lift-evidence",
        type=Path,
        help="Physical-only lift evidence artifact. Its content hash is bound into the manifest.",
    )
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args()
    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("a command is required after --")
    if args.physical_lift_evidence and args.provenance != "physical":
        parser.error("--physical-lift-evidence is valid only with --provenance physical")
    if args.physical_lift_evidence and not args.physical_lift_evidence.is_file():
        parser.error("--physical-lift-evidence must name a readable file")
    return args


def main() -> int:
    args = parse_args()
    run_id = args.run_id or str(uuid.uuid4())
    if Path(run_id).name != run_id or run_id in {"", ".", ".."}:
        raise SystemExit("--run-id must be a single safe path component")

    bundle = args.output_root.resolve() / run_id
    bundle.mkdir(parents=True, exist_ok=False)
    stdout_path = bundle / "stdout.log"
    stderr_path = bundle / "stderr.log"
    started = dt.datetime.now(dt.timezone.utc)
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        completed = subprocess.run(args.command, stdout=stdout, stderr=stderr, check=False)
    finished = dt.datetime.now(dt.timezone.utc)

    lift = {"status": NOT_VERIFIED, "physical_verified": False, "evidence_attached": False}
    if args.physical_lift_evidence:
        evidence = args.physical_lift_evidence.resolve()
        lift.update(
            evidence_attached=True,
            evidence_path=str(evidence),
            evidence_sha256=sha256(evidence),
        )

    manifest = {
        "schema_version": 1,
        "run_id": run_id,
        "provenance": args.provenance,
        "synthetic_hil": args.provenance == "synthetic-hil",
        "physical_system_verified": False,
        "lift": lift,
        "limitations": [NOT_VERIFIED],
        "repository": git_provenance(),
        "command": redacted_command(args.command),
        "cwd": os.getcwd(),
        "started_at": started.isoformat(),
        "finished_at": finished.isoformat(),
        "duration_seconds": round((finished - started).total_seconds(), 6),
        "exit_code": completed.returncode,
        "result": "PASS" if completed.returncode == 0 else "FAIL",
        "artifacts": {
            "stdout.log": {"sha256": sha256(stdout_path)},
            "stderr.log": {"sha256": sha256(stderr_path)},
        },
    }
    manifest_path = bundle / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(manifest_path)
    return completed.returncode


if __name__ == "__main__":
    sys.exit(main())
