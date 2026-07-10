"""PostgreSQL DDL smoke — DBML tables exist after init_db (PHASE_60-F)."""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

_PG_URL = os.getenv("LMS_DATABASE_URL", os.getenv("DATABASE_URL", "")).strip()
if _PG_URL:
    os.environ["LMS_DATABASE_URL"] = _PG_URL

from app.db.connection import init_db, transaction

DBML_TABLES = (
    "items",
    "robots",
    "locations",
    "inventory",
    "tasks",
    "commands",
    "evidence_events",
    "safety_stops",
    "item_change_logs",
    "task_logs",
)

INFRA_TABLES = ("cameras", "maps")


@unittest.skipUnless(_PG_URL, "LMS_DATABASE_URL required")
class PgDdlSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        init_db()

    def test_dbml_tables_exist(self) -> None:
        with transaction() as conn:
            for table in DBML_TABLES:
                row = conn.execute(
                    """
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = %s
                    """,
                    (table,),
                ).fetchone()
                self.assertIsNotNone(row, f"missing table: {table}")

    def test_infra_tables_exist(self) -> None:
        with transaction() as conn:
            for table in INFRA_TABLES:
                row = conn.execute(
                    """
                    SELECT 1 FROM information_schema.tables
                    WHERE table_schema = 'public' AND table_name = %s
                    """,
                    (table,),
                ).fetchone()
                self.assertIsNotNone(row, f"missing infra table: {table}")

    def test_schema_pg_matches_dbml_file(self) -> None:
        schema_path = BACKEND_ROOT.parent / "database" / "schema_pg.sql"
        sql = schema_path.read_text(encoding="utf-8")
        for table in DBML_TABLES:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", sql)


if __name__ == "__main__":
    unittest.main()
