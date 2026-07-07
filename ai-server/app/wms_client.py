from __future__ import annotations

from typing import Any

import httpx

from .config import Settings, get_settings

SUCCESS_STATUS_CODES = {200, 202}


def build_wms_ingest_url(settings: Settings | None = None) -> str:
    """Build the Main/WMS single-event ingest URL from runtime settings."""

    settings = settings or get_settings()
    base_url = settings.main_server_url.rstrip("/")
    path = settings.wms_vision_events_path.strip() or "/api/v1/vision/events"
    return f"{base_url}/{path.lstrip('/')}"


def _empty_result(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": event.get("event_id"),
        "attempted": True,
        "ok": False,
        "status_code": None,
        "error": None,
        "response": None,
    }


def _json_or_none(response: httpx.Response) -> Any | None:
    try:
        return response.json()
    except ValueError:
        return None


async def emit_vision_event(
    event: dict[str, Any],
    *,
    settings: Settings | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """Best-effort POST of one VisionEvent to Main/WMS ingest.

    This function never raises for WMS transport/status failures. It returns a
    structured result so API routes can preserve local detection success while
    reporting downstream ingest status.
    """

    settings = settings or get_settings()
    url = build_wms_ingest_url(settings)
    attempts = max(0, settings.wms_emit_retries) + 1
    timeout = httpx.Timeout(settings.wms_emit_timeout_s)

    async def _post(active_client: httpx.AsyncClient) -> dict[str, Any]:
        result = _empty_result(event)
        last_error: str | None = None

        for _ in range(attempts):
            try:
                response = await active_client.post(url, json=event)
            except httpx.TimeoutException:
                last_error = "WMS ingest timed out"
                continue
            except httpx.RequestError as exc:
                last_error = f"WMS ingest request failed: {exc.__class__.__name__}"
                continue

            status_code = response.status_code
            ok = status_code in SUCCESS_STATUS_CODES
            result.update(
                {
                    "ok": ok,
                    "status_code": status_code,
                    "error": (None if ok else f"WMS ingest returned HTTP {status_code}"),
                    "response": _json_or_none(response) if ok else None,
                }
            )
            return result

        result["error"] = last_error or "WMS ingest failed"
        return result

    if client is not None:
        return await _post(client)

    async with httpx.AsyncClient(timeout=timeout) as owned_client:
        return await _post(owned_client)


async def emit_vision_events(
    events: list[dict[str, Any]],
    *,
    settings: Settings | None = None,
) -> list[dict[str, Any]]:
    """Best-effort emit for a list of events, preserving event order."""

    settings = settings or get_settings()
    timeout = httpx.Timeout(settings.wms_emit_timeout_s)
    async with httpx.AsyncClient(timeout=timeout) as client:
        return [
            await emit_vision_event(event, settings=settings, client=client) for event in events
        ]
