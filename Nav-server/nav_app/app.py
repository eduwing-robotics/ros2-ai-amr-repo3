from fastapi import FastAPI, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from nav_app.bootstrap import ensure_import_paths

ensure_import_paths()

from nav_app.server_core import lifespan, register_app


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

    @app.exception_handler(RequestValidationError)
    async def scenario_validation_error(request: Request, exc: RequestValidationError):
        if request.url.path.startswith("/movement-api/v1/scenario-commands"):
            return JSONResponse(
                status_code=422,
                content={"detail": {"code": "schema_validation_failed", "message": "Scenario request schema validation failed.", "retryable": False}},
            )
        return await request_validation_exception_handler(request, exc)

    return app


app = create_app()
