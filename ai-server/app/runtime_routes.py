from __future__ import annotations

from contextvars import ContextVar
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from .api.evidence import register_evidence_routes
from .api.health import register_health_routes
from .api.operator_runtime import register_operator_runtime_routes
from .api.vision import (
    _get_lift_roi_segmenter,
    _mjpeg_latest_overlay_generator,  # noqa: F401 - compatibility re-export
    _now_dt,  # noqa: F401 - compatibility re-export
    _overlay_publish_payload_preview_for_source,  # noqa: F401 - compatibility re-export
    _parse_vision_model_class_map,  # noqa: F401 - compatibility re-export
    _parse_vision_model_source_config,  # noqa: F401 - compatibility re-export
    _store_latest_frame_from_bytes,  # noqa: F401 - compatibility re-export
    register_vision_routes,
)
from .api.vision_read_models import _ros_ingest_readiness  # noqa: F401 - compatibility re-export
from .contracts import ContractValidationError
from .detectors import generate_synthetic_aruco_frame  # noqa: F401 - compatibility re-export
from .observability import structured_log
from .runtime_state import RuntimeContext, default_runtime_context
from .wms_client import emit_vision_events

_runtime_context_var: ContextVar[RuntimeContext] = ContextVar(
    "smartfactory_ai_server_runtime_context",
    default=default_runtime_context,
)


def _runtime_context() -> RuntimeContext:
    return _runtime_context_var.get()


def _app_runtime_context(app: Any) -> RuntimeContext:
    context = getattr(getattr(app, "state", object()), "runtime_context", None)
    return context if isinstance(context, RuntimeContext) else default_runtime_context


# Backward-compatible test/tool aliases. Runtime request handlers use
# `_runtime_context()` so injected app contexts can be isolated per app.
logger = default_runtime_context.logger
store = default_runtime_context.store
source_health = default_runtime_context.source_health
metrics = default_runtime_context.metrics
frame_store = default_runtime_context.frame_store
overlay_cache = default_runtime_context.overlay_cache
_overlay_images = default_runtime_context.overlay_images
_overlay_images_lock = default_runtime_context.overlay_images_lock


def _error_code_for_status(status_code: int) -> str:
    return {
        400: "BAD_REQUEST",
        404: "NOT_FOUND",
        409: "CONFLICT",
        422: "VALIDATION_ERROR",
        500: "INTERNAL_ERROR",
        503: "SERVICE_UNAVAILABLE",
    }.get(status_code, "HTTP_ERROR")


def _request_id(request: Request | None) -> str | None:
    if request is None:
        return None
    return getattr(request.state, "request_id", None)


def _api_error_response(
    *,
    request: Request | None,
    status_code: int,
    code: str,
    message: str,
    details: list[Any] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or [],
                "request_id": _request_id(request),
            }
        },
    )


async def request_observability_middleware(request: Request, call_next):
    # Multipart form parsing may consume Starlette's request stream before a
    # route dependency runs. Preserve the exact ingress bytes so HMAC checks
    # cover the body that FastAPI later parses.
    request.scope["smartfactory.raw_request_body"] = await request.body()
    token = _runtime_context_var.set(_app_runtime_context(request.app))
    request_id = request.headers.get("x-request-id") or str(uuid4())
    request.state.request_id = request_id
    started = perf_counter()
    status_code = 500
    try:
        try:
            response = await call_next(request)
            status_code = response.status_code
        except Exception:
            duration_ms = round((perf_counter() - started) * 1000.0, 3)
            _runtime_context().metrics.record_http_request(
                method=request.method,
                path=request.url.path,
                status_code=status_code,
                duration_ms=duration_ms,
            )
            structured_log(
                _runtime_context().logger,
                "http_request",
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=status_code,
                duration_ms=duration_ms,
                outcome="exception",
            )
            raise
        duration_ms = round((perf_counter() - started) * 1000.0, 3)
        response.headers["X-Request-ID"] = request_id
        _runtime_context().metrics.record_http_request(
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            duration_ms=duration_ms,
        )
        structured_log(
            _runtime_context().logger,
            "http_request",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=status_code,
            duration_ms=duration_ms,
            outcome="ok",
        )
        return response
    finally:
        _runtime_context_var.reset(token)


async def contract_validation_exception_handler(request: Request, exc: ContractValidationError):
    return _api_error_response(
        request=request, status_code=500, code="CONTRACT_VALIDATION_FAILED", message=str(exc)
    )


async def http_exception_handler(request: Request, exc: HTTPException):
    message = str(exc.detail) if exc.detail is not None else "HTTP error"
    return _api_error_response(
        request=request,
        status_code=exc.status_code,
        code=_error_code_for_status(exc.status_code),
        message=message,
        details=[],
    )


async def request_validation_exception_handler(request: Request, exc: RequestValidationError):
    return _api_error_response(
        request=request,
        status_code=422,
        code="VALIDATION_ERROR",
        message="Request validation failed",
        details=jsonable_encoder(exc.errors()),
    )


def register_routes(app, *, runtime_context: RuntimeContext | None = None) -> None:
    """Register SmartFactory AI Server runtime routes and handlers on app."""
    app.state.runtime_context = runtime_context or default_runtime_context
    app.middleware("http")(request_observability_middleware)
    app.exception_handler(ContractValidationError)(contract_validation_exception_handler)
    app.exception_handler(HTTPException)(http_exception_handler)
    app.exception_handler(RequestValidationError)(request_validation_exception_handler)
    register_health_routes(app, context_getter=_runtime_context)
    register_evidence_routes(app, context_getter=_runtime_context)
    register_operator_runtime_routes(app, context_getter=_runtime_context)
    register_vision_routes(
        app,
        context_getter=_runtime_context,
        emit_vision_events_getter=lambda: emit_vision_events,
        lift_roi_segmenter_getter=lambda: _get_lift_roi_segmenter,
    )
