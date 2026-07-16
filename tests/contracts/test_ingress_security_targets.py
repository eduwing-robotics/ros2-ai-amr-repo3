"""G003 ingress/security target contracts locked during G002.

These source-level contracts intentionally fail while the corresponding G003
production change is absent.  They use only the standard library so a failure
cannot be confused with an unavailable browser or service-runtime dependency.
"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAIN_APP = ROOT / "main-server" / "backend" / "app"
NAV_APP = ROOT / "nav-server" / "nav_app"
AI_APP = ROOT / "ai-server" / "app"
MUTATION_METHODS = {"post", "put", "patch", "delete"}


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _dependency_names(decorator: ast.Call) -> set[str]:
    names: set[str] = set()
    for keyword in decorator.keywords:
        if keyword.arg != "dependencies" or not isinstance(keyword.value, (ast.List, ast.Tuple)):
            continue
        for item in keyword.value.elts:
            if not isinstance(item, ast.Call) or not isinstance(item.func, ast.Name):
                continue
            if item.func.id != "Depends" or not item.args:
                continue
            dependency = item.args[0]
            if isinstance(dependency, ast.Name):
                names.add(dependency.id)
            elif isinstance(dependency, ast.Attribute):
                names.add(dependency.attr)
    return names


def _mutation_routes(path: Path) -> list[tuple[str, str, set[str]]]:
    routes: list[tuple[str, str, set[str]]] = []
    tree = ast.parse(_source(path), filename=str(path))
    for call in (node for node in ast.walk(tree) if isinstance(node, ast.Call)):
        if not isinstance(call.func, ast.Attribute):
            continue
        method = call.func.attr.lower()
        if method not in MUTATION_METHODS or not call.args:
            continue
        route_path = call.args[0]
        if isinstance(route_path, ast.Constant) and isinstance(route_path.value, str):
            routes.append((method.upper(), route_path.value, _dependency_names(call)))
    return routes


def test_retained_service_hmac_primitives_remain_available() -> None:
    main_security = _source(MAIN_APP / "security.py")
    main_movement = _source(MAIN_APP / "api" / "routers" / "movement.py")
    nav_security = _source(NAV_APP / "security.py")
    ai_security = _source(AI_APP / "security.py")

    assert "def sign_headers(" in main_security
    assert "def verify_headers(" in main_security
    assert "require_nav_callback_signature" in main_movement
    assert "verify_headers" in main_movement
    assert "async def require_main_signature(" in nav_security
    assert "async def require_main_hmac(" in ai_security


def test_main_human_mutations_drop_bearer_while_service_hmac_remains() -> None:
    routers = MAIN_APP / "api" / "routers"
    bearer_dependencies: list[str] = []
    for path in sorted(routers.glob("*.py")):
        for method, route_path, dependencies in _mutation_routes(path):
            forbidden = dependencies & {"require_operator", "require_admin"}
            if forbidden:
                bearer_dependencies.append(
                    f"{method} {route_path}: {', '.join(sorted(forbidden))}"
                )

    active_auth_source = "\n".join(
        (_source(MAIN_APP / "security.py"), _source(MAIN_APP / "core" / "config.py"))
    )
    obsolete_symbols = {
        symbol
        for symbol in (
            "LMS_OPERATOR_TOKEN",
            "LMS_ADMIN_TOKEN",
            "require_operator",
            "require_admin",
        )
        if symbol in active_auth_source
    }
    assert not bearer_dependencies and not obsolete_symbols, (
        "G003 target gap: human/UI mutation routes still depend on Bearer RBAC: "
        + "; ".join(bearer_dependencies)
        + f"; active symbols: {sorted(obsolete_symbols)!r}"
    )


def test_main_to_ai_webrtc_offer_uses_the_retained_hmac_boundary() -> None:
    main_proxy_source = _source(MAIN_APP / "services" / "vision_proxy.py")
    ai_routes = _mutation_routes(AI_APP / "api" / "vision.py")
    webrtc_routes = [
        dependencies
        for method, route_path, dependencies in ai_routes
        if method == "POST" and route_path == "/api/v1/vision/streams/{source}/webrtc/offer"
    ]

    assert "def _mutation_headers(" in main_proxy_source
    post_binary = main_proxy_source.split("def _post_binary(", 1)[1].split("\ndef ", 1)[0]
    assert "_mutation_headers(" in post_binary, (
        "G003 target gap: Main's WebRTC offer proxy does not sign the Main→AI request"
    )
    assert webrtc_routes == [{"require_main_hmac"}], (
        "G003 target gap: AI WebRTC offer ingress must have exactly the Main HMAC dependency"
    )


def test_nav_exposes_one_signed_estop_route_per_operation() -> None:
    route_files = sorted((NAV_APP / "routers").glob("*.py"))
    routes = [
        (path.name, method, route_path, dependencies)
        for path in route_files
        for method, route_path, dependencies in _mutation_routes(path)
    ]

    for route_path in ("/robot/estop", "/robot/clear_estop"):
        matches = [entry for entry in routes if entry[2] == route_path]
        assert matches == [
            ("movement_api.py", "POST", route_path, {"require_main_signature"})
        ], (
            "G003 target gap: remove unsigned Nav shadow route and retain only the signed "
            f"canonical route for {route_path}; found {matches!r}"
        )


def test_ai_debug_mutations_have_no_unauthenticated_bypass() -> None:
    config_source = _source(AI_APP / "config.py")
    security_source = _source(AI_APP / "security.py")
    vision_source = _source(AI_APP / "api" / "vision.py")
    evidence_source = _source(AI_APP / "api" / "evidence.py")

    active_references = {
        "config.py": "ai_debug_mutations_enabled" in config_source,
        "security.py": "ai_debug_mutations_enabled" in security_source,
        "api/vision.py": "require_protected_debug_mutation" in vision_source,
        "api/evidence.py": "require_protected_debug_mutation" in evidence_source,
    }
    assert not any(active_references.values()), (
        "G003 target gap: unauthenticated AI debug-mutation bypass remains active: "
        + ", ".join(name for name, present in active_references.items() if present)
    )
