from __future__ import annotations

import asyncio

import httpx

from app.config import Settings
from app.wms_client import build_wms_ingest_url, emit_vision_event


def _event() -> dict:
    return {
        "event_id": "11111111-1111-4111-8111-111111111111",
        "schema_version": "vision-event.v1",
    }


def _settings(**overrides) -> Settings:
    values = {
        "main_server_url": "http://wms.local/base/",
        "wms_vision_events_path": "/api/v1/vision/events",
        "wms_emit_timeout_s": 0.1,
        "wms_emit_retries": 0,
    }
    values.update(overrides)
    return Settings(**values)


def test_default_main_server_url_matches_current_main_handoff(monkeypatch):
    monkeypatch.delenv("MAIN_SERVER_URL", raising=False)
    settings = Settings(_env_file=None)

    assert settings.main_server_url == "http://smartfactory-main.local:8088"
    assert build_wms_ingest_url(settings) == (
        "http://smartfactory-main.local:8088/api/v1/vision/events"
    )


def test_build_wms_ingest_url_joins_base_and_path():
    settings = _settings(
        main_server_url="http://wms.local",
        wms_vision_events_path="api/v1/vision/events",
    )

    assert build_wms_ingest_url(settings) == "http://wms.local/api/v1/vision/events"


def test_emit_vision_event_treats_202_as_success():
    seen: list[dict] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        seen.append(
            {
                "url": str(request.url),
                "body": request.read(),
            }
        )
        return httpx.Response(
            202,
            json={
                "accepted": True,
                "duplicate": False,
                "wms_processing_status": "queued",
            },
        )

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await emit_vision_event(_event(), settings=_settings(), client=client)

    result = asyncio.run(run())

    assert seen[0]["url"] == "http://wms.local/base/api/v1/vision/events"
    assert result["attempted"] is True
    assert result["ok"] is True
    assert result["status_code"] == 202
    assert result["response"]["accepted"] is True


def test_emit_vision_event_treats_200_duplicate_as_success():
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "accepted": True,
                "duplicate": True,
                "wms_processing_status": "already_seen",
            },
        )

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await emit_vision_event(_event(), settings=_settings(), client=client)

    result = asyncio.run(run())

    assert result["ok"] is True
    assert result["status_code"] == 200
    assert result["response"]["duplicate"] is True


def test_emit_vision_event_reports_non_2xx_without_raising():
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await emit_vision_event(_event(), settings=_settings(), client=client)

    result = asyncio.run(run())

    assert result["ok"] is False
    assert result["status_code"] == 503
    assert result["response"] is None
    assert result["error"] == "WMS ingest returned HTTP 503"


def test_emit_vision_event_reports_timeout_without_raising():
    async def handler(_: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("slow WMS")

    async def run():
        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as client:
            return await emit_vision_event(_event(), settings=_settings(), client=client)

    result = asyncio.run(run())

    assert result["ok"] is False
    assert result["status_code"] is None
    assert result["response"] is None
    assert result["error"] == "WMS ingest timed out"
