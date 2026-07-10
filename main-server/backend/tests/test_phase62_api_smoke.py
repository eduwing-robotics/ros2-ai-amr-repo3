"""PHASE_62 API smoke — route registration (no httpx/TestClient)."""

from __future__ import annotations

import unittest

from app.main import app


class Phase62ApiSmokeTests(unittest.TestCase):
    def test_phase62_routes_registered(self) -> None:
        routes = set(app.openapi()["paths"].keys())
        for path in (
            "/api/v1/tasks",
            "/api/v1/tasks/{task_id}/assign",
            "/api/v1/tasks/{task_id}/complete",
            "/api/v1/tasks/{task_id}/cancel",
            "/api/v1/comm/logs",
            "/api/v1/comm/probe/movement",
            "/api/v1/robot-poses",
        ):
            self.assertIn(path, routes)


if __name__ == "__main__":
    unittest.main()
