"""Shared helpers for API routers."""

from __future__ import annotations

from fastapi import Request

from app.core.config import settings
from app.core.http_security import validate_service_base_url


def callback_base_url(request: Request, override: str | None = None) -> str:
    """Resolve Movement callback base URL from request or explicit override."""
    if override:
        trimmed = validate_service_base_url(override)
        if trimmed.endswith(settings.api_prefix):
            return trimmed
        return f"{trimmed}{settings.api_prefix}"
    request_base = validate_service_base_url(str(request.base_url).rstrip("/"))
    return validate_service_base_url(settings.api_callback_base_url(request_base))


def with_callback(payload: dict, request: Request) -> dict:
    """Inject callback_base_url into a command payload when omitted."""
    if not payload.get("callback_base_url"):
        payload["callback_base_url"] = callback_base_url(request)
    return payload
