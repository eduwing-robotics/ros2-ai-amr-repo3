"""HTTP runtime smoke — health/status and basic API shape."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

try:
    from fastapi.testclient import TestClient
except ImportError:
    TestClient = None  # type: ignore[misc, assignment]

from app.main import app


@unittest.skipUnless(TestClient is not None, "httpx not installed — pip install -r requirements-dev.txt")
class ApiRuntimeSmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        self._patches = [
            patch("app.db.connection.require_database_url"),
            patch("app.db.connection.init_db"),
            patch("app.main.asyncio.create_task", return_value=MagicMock()),
        ]
        for p in self._patches:
            p.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        for p in reversed(self._patches):
            p.stop()

    def test_health_ok(self) -> None:
        res = self.client.get("/health")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        self.assertTrue(body.get("ok"))

    @patch("app.api.routers.system.fetch_camera_health", return_value={})
    @patch("app.api.routers.system.get_movement_health", return_value={})
    @patch("app.api.routers.system.task_repo")
    @patch("app.api.routers.system.event_repo")
    @patch("app.api.routers.system.movement_repo")
    @patch("app.api.routers.system.camera_repo")
    @patch("app.api.routers.system.robot_repo")
    @patch("app.api.routers.system.transaction")
    def test_status_snapshot_keys(
        self,
        transaction_ctx,
        robot_repo_fn,
        camera_repo_fn,
        movement_repo_fn,
        event_repo_fn,
        task_repo_fn,
        *_mocks,
    ) -> None:
        conn = MagicMock()
        transaction_ctx.return_value.__enter__.return_value = conn
        robot_repo_fn.list.return_value = []
        camera_repo_fn.list.return_value = []
        movement_repo_fn.list.return_value = []
        event_repo_fn.list.return_value = []
        task_repo_fn.list.return_value = []

        res = self.client.get("/api/v1/status")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        for key in ("system", "robots", "camera_sources", "movement_commands", "events", "tasks"):
            self.assertIn(key, body)


if __name__ == "__main__":
    unittest.main()
