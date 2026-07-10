"""Contract tests for the Nav service verification entry point."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path


SOURCE_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_all.sh"


def _copy_check_script(tmp_path: Path) -> Path:
    scripts_dir = tmp_path / "scripts"
    scripts_dir.mkdir()
    script = scripts_dir / "check_all.sh"
    shutil.copy2(SOURCE_SCRIPT, script)
    (scripts_dir / "sim_ops.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    return script


def _run(script: Path, *, python_bin: str | None = None) -> subprocess.CompletedProcess[str]:
    env = {"PATH": os.environ["PATH"]}
    if python_bin is not None:
        env["PYTHON_BIN"] = python_bin
    return subprocess.run(
        ["bash", str(script)],
        check=False,
        capture_output=True,
        text=True,
        env=env,
    )


def test_check_all_requires_service_venv_by_default(tmp_path: Path) -> None:
    result = _run(_copy_check_script(tmp_path))

    assert result.returncode == 1
    assert "Nav virtual environment is missing" in result.stderr
    assert ".venv/bin/python" in result.stderr


def test_check_all_honors_explicit_python_bin_override(tmp_path: Path) -> None:
    script = _copy_check_script(tmp_path)
    fake_python = tmp_path / "fake-python"
    fake_python.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    fake_python.chmod(fake_python.stat().st_mode | stat.S_IXUSR)

    result = _run(script, python_bin=str(fake_python))

    assert result.returncode == 0, result.stderr
    assert "[check_all] done" in result.stdout
