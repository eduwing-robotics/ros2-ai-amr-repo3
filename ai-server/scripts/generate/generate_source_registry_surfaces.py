#!/usr/bin/env python3
"""Generate source-registry-derived contract surfaces.

This keeps Lane A's source registry as the source of truth for schema enums,
OpenAPI source enum hints, and a machine-readable fixture/snapshot consumed by
GUI/Main/ROS integration work.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SERVICE_DIR = ROOT
CONTRACT_DIR = ROOT / "docs" / "contracts"
GENERATED_DIR = CONTRACT_DIR / "generated"
FIXTURE_DIR = CONTRACT_DIR / "fixtures"

VENV_PYTHON = SERVICE_DIR / ".venv" / "bin" / "python"
VENV_DIR = SERVICE_DIR / ".venv"
if VENV_PYTHON.exists() and Path(sys.prefix).resolve() != VENV_DIR.resolve():
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), __file__, *sys.argv[1:]])

sys.path.insert(0, str(SERVICE_DIR))

from app.config import get_settings  # noqa: E402
from app.factory import create_app  # noqa: E402


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8"
    )


def _update_source_enum(path: Path, source_ids: list[str]) -> None:
    schema = _load_json(path)
    properties = schema.setdefault("properties", {})
    source = properties.setdefault("source", {"type": "string"})
    source["type"] = "string"
    source["enum"] = source_ids
    _write_json(path, schema)


def main() -> int:
    settings = get_settings()
    registry = settings.source_registry
    source_ids = registry.source_ids

    _update_source_enum(CONTRACT_DIR / "vision-event.schema.json", source_ids)
    _update_source_enum(CONTRACT_DIR / "lift-roi-evidence.schema.json", source_ids)

    snapshot = registry.as_snapshot()
    _write_json(GENERATED_DIR / "source-registry.snapshot.json", snapshot)
    _write_json(FIXTURE_DIR / "source-registry.valid.json", snapshot)

    app = create_app()
    _write_json(CONTRACT_DIR / "ai-server-openapi.json", app.openapi())

    print("Generated source registry surfaces:")
    print(f"- {CONTRACT_DIR / 'vision-event.schema.json'}")
    print(f"- {CONTRACT_DIR / 'lift-roi-evidence.schema.json'}")
    print(f"- {GENERATED_DIR / 'source-registry.snapshot.json'}")
    print(f"- {FIXTURE_DIR / 'source-registry.valid.json'}")
    print(f"- {CONTRACT_DIR / 'ai-server-openapi.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
