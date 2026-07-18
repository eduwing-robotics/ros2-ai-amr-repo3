# 기능 책임: LAN upstream URL·응답 크기 제한을 검증한다. 비책임: 실장비의 물리 동작.
from __future__ import annotations

from io import BytesIO

import pytest

from app.core.http_security import UpstreamResponseTooLarge, read_limited, validate_service_base_url


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://user:pass@nav.local:8001",
        "http://nav.local:8001?target=other",
        "http://nav.local:8001#fragment",
        "//nav.local:8001",
    ],
)
def test_rejects_unsafe_service_base_urls(url: str) -> None:
    with pytest.raises(ValueError):
        validate_service_base_url(url)


def test_allows_configured_lan_http_url_with_path() -> None:
    assert (
        validate_service_base_url("http://192.168.10.54:8001/movement-api/v1/")
        == "http://192.168.10.54:8001/movement-api/v1"
    )


def test_read_limited_rejects_oversized_body() -> None:
    with pytest.raises(UpstreamResponseTooLarge):
        read_limited(BytesIO(b"12345"), max_bytes=4)
