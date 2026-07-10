"""Lightweight backend smoke tests without external test dependencies."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.main import app

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


class AppRouteSmokeTest(unittest.TestCase):
    def test_core_routes_are_registered(self) -> None:
        routes = set(app.openapi()["paths"].keys())
        self.assertIn("/health", routes)
        self.assertIn("/api/v1/status", routes)
        self.assertIn("/api/v1/task-logs", routes)
        self.assertIn("/api/v1/item-change-logs", routes)
        self.assertIn("/api/v1/evidence-events", routes)
        self.assertIn("/api/v1/work-orders", routes)
        self.assertIn("/api/v1/inventory", routes)
        self.assertIn("/api/v1/storage-slots", routes)
        self.assertIn("/api/v1/tasks", routes)
        self.assertIn("/api/v1/comm/logs", routes)
        self.assertIn("/api/v1/robot-poses", routes)
        self.assertIn("/api/v1/db/tables", routes)

    def test_schema_pg_contains_dbml_tables(self) -> None:
        schema = Path(__file__).resolve().parents[2] / "database" / "schema_pg.sql"
        sql = schema.read_text(encoding="utf-8")
        for table in DBML_TABLES:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", sql)


if __name__ == "__main__":
    unittest.main()
