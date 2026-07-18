# 기능 책임: 필수 공개 API route 등록을 검증한다. 비책임: 실장비의 물리 동작.
"""API route registration smoke tests (no httpx/TestClient)."""

from __future__ import annotations

import unittest

from app.main import app


class ApiRouteRegistrationTests(unittest.TestCase):
    def test_required_routes_registered(self) -> None:
        routes = set(app.openapi()["paths"].keys())
        for path in (
            "/api/v1/tasks",
            "/api/v1/tasks/{task_id}/assign",
            "/api/v1/tasks/{task_id}/cancel",
            "/api/v1/comm/logs",
            "/api/v1/comm/probe/movement",
            "/api/v1/robot-poses",
        ):
            self.assertIn(path, routes)

        self.assertNotIn("/api/v1/tasks/{task_id}/complete", routes)
        self.assertNotIn("/api/v1/robot-poses/report", routes)
        self.assertNotIn("/api/v1/movement/missions/{command_id}/pose", routes)


if __name__ == "__main__":
    unittest.main()
