from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .runtime_state import RuntimeContext, default_runtime_context
from .service_metadata import SERVICE_VERSION


def create_app(runtime_context: RuntimeContext | None = None) -> FastAPI:
    """Create the SmartFactory AI Server FastAPI application.

    Route registration is owned by the factory so contract/OpenAPI generation
    and `app.main:app` runtime startup use the same construction path without a
    generator-only bridge back into `app.main`. The mutable runtime state is an
    explicit injectable context; the default entrypoint uses the shared default
    context for backward-compatible single-process operation.
    """

    app = FastAPI(
        title="SmartFactory AI Server",
        version=SERVICE_VERSION,
        description="API-first MVP1 AI Server. Emits evidence only; WMS owns decisions.",
    )
    settings = get_settings()
    origins = _cors_origins(settings.ai_server_cors_allow_origins, settings.main_server_url)
    if origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "OPTIONS"],
            allow_headers=["*"],
        )

    from .runtime_routes import register_routes

    register_routes(app, runtime_context=runtime_context or default_runtime_context)
    return app


def _cors_origins(raw_origins: str, main_server_url: str) -> list[str]:
    """Return explicit browser origins allowed to call the Vision API.

    Main dashboard is expected to run at smartfactory-main.local:8088. Keep this
    explicit rather than wildcarding the robot/Vision network surface.
    """

    origins: list[str] = []
    for value in (*raw_origins.split(","), main_server_url):
        origin = value.strip().rstrip("/")
        if origin and origin not in origins:
            origins.append(origin)
    return origins


__all__ = ["create_app"]
