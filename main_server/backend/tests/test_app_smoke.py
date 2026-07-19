# 기능 책임: 애플리케이션 route·DBML 기본 구조을 검증한다. 비책임: 실장비의 물리 동작.
"""Lightweight backend smoke tests without external test dependencies."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from fastapi import HTTPException

from app.domains.execution.poller import poll_task_progress_loop
from app.domains.safety.hazard_loop import person_hazard_loop
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
        self.assertIn("/ready", routes)
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

    def test_ready_rejects_three_consecutive_worker_failures_and_recovers(self) -> None:
        ready = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/ready")
        app.state.sweep_task = MagicMock(done=MagicMock(return_value=False))
        app.state.hazard_task = MagicMock(done=MagicMock(return_value=False))
        app.state.pose_tasks = []
        poll_task_progress_loop.consecutive_failures = 3
        person_hazard_loop.consecutive_failures = 0
        transaction = MagicMock()
        transaction.return_value.__enter__.return_value.execute.return_value.fetchone.return_value = {"ok": 1}
        try:
            with patch("app.main.transaction", transaction), self.assertRaises(HTTPException) as raised:
                ready()
            self.assertEqual(raised.exception.status_code, 503)
            self.assertIn("task progress poller", str(raised.exception.detail))

            poll_task_progress_loop.consecutive_failures = 0
            with patch("app.main.transaction", transaction):
                self.assertTrue(ready()["ok"])
        finally:
            poll_task_progress_loop.consecutive_failures = 0
            person_hazard_loop.consecutive_failures = 0

    def test_schema_pg_contains_dbml_tables(self) -> None:
        schema = Path(__file__).resolve().parents[2] / "database" / "schema_pg.sql"
        sql = schema.read_text(encoding="utf-8")
        for table in DBML_TABLES:
            self.assertIn(f"CREATE TABLE IF NOT EXISTS {table}", sql)


if __name__ == "__main__":
    unittest.main()
