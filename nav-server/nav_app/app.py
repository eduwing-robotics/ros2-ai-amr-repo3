import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nav_app.config import MAIN_PUBLIC_BASE_URL
from nav_app.server_core import lifespan, register_app


def _cors_origins() -> list[str]:
    configured = os.getenv("NAV_CORS_ALLOWED_ORIGINS", MAIN_PUBLIC_BASE_URL)
    return [origin.rstrip("/") for origin in configured.split(",") if origin.strip()]


def create_app() -> FastAPI:
    app = FastAPI(title="Logistics Nav Server API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_app(app)
    return app


app = create_app()
