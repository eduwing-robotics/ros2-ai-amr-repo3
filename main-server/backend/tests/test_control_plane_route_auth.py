"""Assembled mutation-ingress contract for trusted-site operation."""

from __future__ import annotations

import sys
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_ROOT))

from app.core.config import settings as runtime_settings
from app.main import app

MUTATION_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
HUMAN_BEARER_DEPENDENCIES = {"require_operator", "require_admin", "require_role"}
MACHINE_INGRESS_DEPENDENCIES = {"require_nav_callback_signature"}


def _assembled_mutation_routes():
    def walk(routes, prefix=""):
        for route in routes:
            if isinstance(route, APIRoute):
                yield prefix + route.path, route
            elif hasattr(route, "original_router"):
                yield from walk(
                    route.original_router.routes,
                    prefix + route.include_context.prefix,
                )

    yield from (
        (path, route)
        for path, route in walk(app.routes)
        if route.methods & MUTATION_METHODS
    )


def _human_bearer_boundaries(route: APIRoute) -> set[str]:
    boundaries: set[str] = set()
    for dependency in route.dependant.dependencies:
        call = dependency.call
        call_name = getattr(call, "__name__", "")
        call_qualname = getattr(call, "__qualname__", "")
        for boundary in HUMAN_BEARER_DEPENDENCIES:
            if call_name == boundary or call_qualname == boundary or call_qualname.startswith(
                f"{boundary}.<locals>."
            ):
                boundaries.add(boundary)
    return boundaries


def _exact_machine_boundaries(route: APIRoute) -> set[str]:
    dependency_names = {
        getattr(dependency.call, "__name__", "")
        for dependency in route.dependant.dependencies
    }
    return dependency_names & MACHINE_INGRESS_DEPENDENCIES


class ControlPlaneRouteAuthTest(unittest.TestCase):
    """Exercise the mounted app rather than isolated dependency stubs."""

    def setUp(self) -> None:
        configured = replace(runtime_settings, movement_hmac_secret="route-nav-secret")
        movement_transaction = patch("app.api.routers.movement.transaction")
        self._patches = [
            patch("app.core.config.settings", configured),
            patch("app.api.routers.movement.settings", configured),
            movement_transaction,
            patch(
                "app.api.routers.movement.callbacks.estop_all_robots",
                return_value=[{"robot_id": "tb3_1", "ok": True}],
            ),
            patch("app.db.connection.init_db"),
            patch("app.main.asyncio.create_task", return_value=MagicMock()),
        ]
        started = [item.start() for item in self._patches]
        started[self._patches.index(movement_transaction)].return_value.__enter__.return_value = MagicMock()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        for item in reversed(self._patches):
            item.stop()

    def test_all_mutations_have_one_trusted_human_or_machine_boundary(self) -> None:
        """Human writes are open on the trusted LAN; callbacks retain HMAC."""
        documented = {
            (path, method.upper())
            for path, operations in app.openapi()["paths"].items()
            for method in operations
            if method.upper() in MUTATION_METHODS
        }
        assembled = list(_assembled_mutation_routes())
        self.assertTrue(assembled, "assembled app has no mutation routes")

        for path, route in assembled:
            machine_boundaries = _exact_machine_boundaries(route)
            bearer_boundaries = _human_bearer_boundaries(route)
            for method in route.methods & MUTATION_METHODS:
                with self.subTest(method=method, path=path):
                    self.assertIn((path, method), documented)
                    self.assertLessEqual(
                        len(machine_boundaries),
                        1,
                        "a mutation must not have multiple machine-integrity owners",
                    )
                    self.assertFalse(
                        bearer_boundaries,
                        f"trusted-site human mutation still has Bearer dependencies: {bearer_boundaries}",
                    )
                    if machine_boundaries:
                        response = self.client.request(method, path)
                        self.assertEqual(response.status_code, 401)

    def test_representative_human_mutations_reach_domain_validation_without_auth(self) -> None:
        cases = (
            ("POST", "/api/v1/items", {}),
            ("POST", "/api/v1/work-orders", {}),
            ("POST", "/api/v1/robot/estop", None),
            ("POST", "/api/v1/maps", {}),
        )
        for method, path, payload in cases:
            with self.subTest(method=method, path=path):
                response = self.client.request(method, path, json=payload)
                self.assertNotIn(response.status_code, {401, 403, 503})

    def test_robot_command_rejects_external_callback_url_before_dispatch(self) -> None:
        response = self.client.post(
            "/api/v1/robot-commands",
            json={
                "robot_id": "tb3_1",
                "kind": "move_to_point",
                "params": {"map_id": "map", "x": 1, "y": 2},
                "callback_url": "https://attacker.example/movement/command-events",
            },
        )
        self.assertEqual(response.status_code, 422)
        self.assertIn("callback_url", response.text)

    def test_pose_has_one_signed_canonical_machine_ingress(self) -> None:
        canonical_path = "/api/v1/robots/{robot_id}/pose"
        legacy_paths = {
            "/api/v1/robot-poses/report",
            "/api/v1/movement/missions/{command_id}/pose",
        }
        post_routes = [
            (path, route)
            for path, route in _assembled_mutation_routes()
            if "POST" in route.methods
        ]

        canonical_routes = [route for path, route in post_routes if path == canonical_path]
        self.assertEqual(
            len(canonical_routes),
            1,
            "the assembled app must expose exactly one canonical pose ingress",
        )
        assembled_paths = {path for path, _route in post_routes}
        self.assertTrue(
            legacy_paths.isdisjoint(assembled_paths),
            f"legacy pose ingresses remain assembled: {legacy_paths & assembled_paths}",
        )

        self.assertEqual(
            _exact_machine_boundaries(canonical_routes[0]),
            {"require_nav_callback_signature"},
            "the canonical pose ingress must retain the Nav callback signature boundary",
        )
