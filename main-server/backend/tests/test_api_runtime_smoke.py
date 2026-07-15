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
            patch("app.db.pg_connection.require_database_url"),
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

    def test_app_is_same_origin_only(self) -> None:
        same_origin = self.client.get("/health", headers={"Origin": "http://testserver"})
        self.assertEqual(same_origin.status_code, 200)

        preflight = self.client.options(
            "/api/v1/status",
            headers={
                "Origin": "https://evil.example",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertNotIn("access-control-allow-origin", preflight.headers)

    @patch("app.api.routers.movement.callbacks.estop_all_robots", return_value=[])
    @patch("app.api.routers.movement.transaction")
    def test_cross_site_browser_mutations_are_rejected_before_handler(
        self,
        transaction_ctx,
        estop_all_robots,
    ) -> None:
        attempts = (
            {"Origin": "https://evil.example"},
            {"Sec-Fetch-Site": "cross-site"},
            {"Origin": "http://testserver", "Sec-Fetch-Site": "same-site"},
            {"Origin": "https://evil.example", "Sec-Fetch-Site": "same-origin"},
            {
                "Host": "smartfactory-main.local:8088",
                "Origin": "http://localhost:8088",
                "Sec-Fetch-Site": "same-origin",
            },
            {"Host": "invalid host", "Origin": "null"},
        )

        for headers in attempts:
            with self.subTest(headers=headers):
                response = self.client.post("/api/v1/robot/estop", headers=headers)
                self.assertEqual(response.status_code, 403)
                transaction_ctx.assert_not_called()
                estop_all_robots.assert_not_called()

    @patch("app.api.routers.movement.callbacks.estop_all_robots", return_value=[])
    @patch("app.api.routers.movement.transaction")
    def test_same_origin_and_headerless_mutations_reach_handler(
        self,
        transaction_ctx,
        estop_all_robots,
    ) -> None:
        transaction_ctx.return_value.__enter__.return_value = MagicMock()
        attempts = (
            {},
            {
                "Host": "smartfactory-main.local:8088",
                "Origin": "http://smartfactory-main.local:8088",
                "Sec-Fetch-Site": "same-origin",
            },
            {
                "Host": "localhost:8088",
                "Origin": "http://localhost:8088",
                "Sec-Fetch-Site": "same-origin",
            },
        )

        for headers in attempts:
            with self.subTest(headers=headers):
                response = self.client.post("/api/v1/robot/estop", headers=headers)
                self.assertEqual(response.status_code, 200)

        self.assertEqual(transaction_ctx.call_count, len(attempts))
        self.assertEqual(estop_all_robots.call_count, len(attempts))

    def test_read_and_options_requests_are_not_blocked(self) -> None:
        headers = {"Origin": "https://evil.example", "Sec-Fetch-Site": "cross-site"}
        self.assertEqual(self.client.get("/health", headers=headers).status_code, 200)
        self.assertNotEqual(self.client.options("/api/v1/robot/estop", headers=headers).status_code, 403)

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
        robot_repo_fn.return_value.list.return_value = []
        camera_repo_fn.return_value.list.return_value = []
        movement_repo_fn.return_value.list.return_value = []
        event_repo_fn.return_value.list.return_value = []
        task_repo_fn.return_value.list.return_value = []

        res = self.client.get("/api/v1/status")
        self.assertEqual(res.status_code, 200)
        body = res.json()
        for key in ("system", "robots", "camera_sources", "movement_commands", "events", "tasks"):
            self.assertIn(key, body)


if __name__ == "__main__":
    unittest.main()
