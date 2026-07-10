from __future__ import annotations

import importlib.util
from pathlib import Path

AUDIT_PATH = Path(__file__).resolve().parents[1] / "scripts/validate/self_containment_audit.py"
SPEC = importlib.util.spec_from_file_location("self_containment_audit", AUDIT_PATH)
assert SPEC and SPEC.loader
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def test_markdownlint_omx_ignore_is_allowed(tmp_path):
    omx_ignore = "." + "omx/**"
    (tmp_path / ".markdownlint-cli2.yaml").write_text(
        f'ignores:\n  - "{omx_ignore}"\n', encoding="utf-8"
    )

    assert audit.find_failures(tmp_path) == []


def test_omx_runtime_reference_still_fails_containment_audit(tmp_path):
    leaked_reference = "." + "omx/runtime/state.json"
    (tmp_path / "runtime.yaml").write_text(f"state: {leaked_reference}\n", encoding="utf-8")

    assert audit.find_failures(tmp_path) == [
        "runtime.yaml: forbidden pattern \\." + "omx",
    ]
