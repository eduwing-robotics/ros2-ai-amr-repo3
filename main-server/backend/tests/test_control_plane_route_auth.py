"""Real FastAPI route coverage for Main control-plane authentication."""

from __future__ import annotations

import json
import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.api.routers.movement import require_nav_callback_signature
from app.core.config import settings as runtime_settings
from app.main import app
from app.security import require_admin, require_operator, sign_headers


class ControlPlaneRouteAuthTest(unittest.TestCase):
    """Exercise the assembled app, rather than isolated dependency stubs."""

    def setUp(self) -> None:
        configured = replace(
            runtime_settings,
            operator_token="route-operator",
            admin_token="route-admin",
            movement_hmac_secret="route-nav-secret",
        )
        self._patches = [
            patch("app.core.config.settings", configured),
            patch("app.api.routers.movement.settings", configured),
            patch("app.db.pg_connection.require_database_url"),
            patch("app.db.connection.init_db"),
            patch("app.main.asyncio.create_task", return_value=MagicMock()),
        ]
        for item in self._patches:
            item.start()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        for item in reversed(self._patches):
            item.stop()

    def test_all_assembled_mutation_routes_have_the_right_auth_boundary(self) -> None:
        """Route coverage follows the mounted FastAPI app, not a hand-kept list."""
        mutation_methods = {"POST", "PUT", "PATCH", "DELETE"}

        def walk(routes, prefix=""):
            for route in routes:
                if isinstance(route, APIRoute):
                    yield prefix + route.path, route
                elif hasattr(route, "original_router"):
                    yield from walk(
                        route.original_router.routes,
                        prefix + route.include_context.prefix,
                    )

        assembled = [
            (path, route) for path, route in walk(app.routes)
            if route.methods & mutation_methods
        ]
        documented = {
            (path, method.upper())
            for path, operations in app.openapi()["paths"].items()
            for method in operations
            if method.upper() in mutation_methods
        }
        self.assertTrue(assembled, "assembled app has no mutation routes")

        for path, route in assembled:
            dependencies = {dependency.call for dependency in route.dependant.dependencies}
            methods = route.methods & mutation_methods
            for method in methods:
                with self.subTest(method=method, path=path):
                    self.assertIn((path, method), documented)
                    if require_nav_callback_signature in dependencies:
                        self.assertNotIn(require_operator, dependencies)
                        self.assertNotIn(require_admin, dependencies)
                        response = self.client.request(method, path)
                        self.assertEqual(response.status_code, 401)
                    else:
                        self.assertTrue(
                            {require_operator, require_admin} & dependencies,
                            "non-callback mutation must require operator or admin",
                        )
                        response = self.client.request(method, path)
                        self.assertEqual(response.status_code, 401)

    def test_admin_routes_reject_operator_token(self) -> None:
        response = self.client.post("/api/v1/items", headers={"Authorization": "Bearer route-operator"})
        self.assertEqual(response.status_code, 401)

    def test_robot_command_rejects_external_callback_url_before_dispatch(self) -> None:
        response = self.client.post(
            "/api/v1/robot-commands",
            headers={"Authorization": "Bearer route-operator"},
            json={
                "robot_id": "tb3_1",
                "kind": "move_to_point",
                "params": {"map_id": "map", "x": 1, "y": 2},
                "callback_url": "https://attacker.example/movement/command-events",
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("callback_url", response.text)

    @patch("app.api.routers.robot_poses.transaction")
    @patch("app.api.routers.robot_poses.report_pose_for_robot")
    def test_pose_callback_is_hmac_authenticated_not_bearer_authenticated(self, report_pose, transaction_ctx) -> None:
        conn = MagicMock()
        transaction_ctx.return_value.__enter__.return_value = conn
        payload = {"robot_id": "tb3_1", "map_id": "map", "x": 1.0, "y": 2.0}
        body = json.dumps(payload, separators=(",", ":")).encode()
        path = "/api/v1/robot-poses/report"

        self.assertEqual(self.client.post(path, content=body, headers={"content-type": "application/json"}).status_code, 401)
        headers = {"content-type": "application/json", **sign_headers("route-nav-secret", "POST", path, body)}
        self.assertEqual(self.client.post(path, content=body, headers=headers).status_code, 200)
        report_pose.assert_called_once()
