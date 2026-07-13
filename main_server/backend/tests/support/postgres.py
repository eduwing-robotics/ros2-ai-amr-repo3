"""Test-only PostgreSQL fixture loader.

Demo data (BOX-A/BOX-B, demo locations/markers) lives only under tests/support/
and is applied exclusively by tests against a dedicated test DB.
"""

from __future__ import annotations

import os
from pathlib import Path

from app.core.config import settings
from app.db.connection import transaction

_FIXTURE_SQL = Path(__file__).resolve().parent / "demo_seed_pg.sql"


def apply_demo_fixture() -> None:
    url = settings.database_url
    if "LMS_ALLOW_MUTABLE_DB_TESTS" not in os.environ and "_test" not in url:
        raise RuntimeError(
            "Refusing to apply demo fixture to non-test DB. "
            "Use a database name containing '_test' or set LMS_ALLOW_MUTABLE_DB_TESTS=1."
        )
    with transaction() as conn:
        conn._conn.execute(_FIXTURE_SQL.read_text(encoding="utf-8"))
