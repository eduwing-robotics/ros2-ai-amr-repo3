"""Shared helpers for API routers."""

from __future__ import annotations

from fastapi import Request

from app.core.config import settings


def callback_base_url(request: Request, override: str | None = None) -> str:
    """Resolve Movement callback base URL from request or explicit override."""
    if override:
        trimmed = override.rstrip("/")
        if trimmed.endswith(settings.api_prefix):
            return trimmed
        return f"{trimmed}{settings.api_prefix}"
    return settings.api_callback_base_url(str(request.base_url).rstrip("/"))


def with_callback(payload: dict, request: Request) -> dict:
    """Inject callback_base_url into a mission payload when omitted."""
    if not payload.get("callback_base_url"):
        payload["callback_base_url"] = callback_base_url(request)
    return payload
