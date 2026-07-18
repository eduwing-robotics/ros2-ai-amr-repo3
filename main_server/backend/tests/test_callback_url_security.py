# 기능 책임: Movement callback URL의 SSRF·prefix 보호을 검증한다. 비책임: 실장비의 물리 동작.
from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi import Request

from app.api.helpers import callback_base_url
from app.core.config import settings


def _request(base_url: str) -> Request:
    return Request({"type": "http", "scheme": base_url.split(":", 1)[0], "server": ("main.local", 8088), "path": "/", "headers": [(b"host", b"main.local:8088")]})


@pytest.mark.parametrize(
    "override",
    ["file:///etc/passwd", "http://user:pass@main.local:8088", "http://main.local:8088?next=evil"],
)
def test_callback_override_rejects_unsafe_url(override: str) -> None:
    with pytest.raises(ValueError):
        callback_base_url(_request("http://main.local:8088"), override)


def test_callback_override_keeps_api_prefix() -> None:
    assert callback_base_url(_request("http://main.local:8088"), "http://main.local:8088") == "http://main.local:8088/api/v1"


def test_configured_public_base_is_validated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "app.api.helpers.settings",
        replace(settings, public_base_url="http://user:pass@main.local:8088"),
    )

    with pytest.raises(ValueError):
        callback_base_url(_request("http://main.local:8088"))
