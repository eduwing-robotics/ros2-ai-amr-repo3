from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nav_app.bootstrap import ensure_import_paths

ensure_import_paths()

from nav_app.server_core import lifespan, register_app  # noqa: E402


def create_app() -> FastAPI:
    app = FastAPI(title="Logistics Nav Server API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://192.168.30.9:8088",
            "http://smartfactory-main.local:8088",
            "http://smartfactory-main:8088",
            "http://localhost:8088",
            "http://127.0.0.1:8088",
        ],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_app(app)
    return app


app = create_app()
