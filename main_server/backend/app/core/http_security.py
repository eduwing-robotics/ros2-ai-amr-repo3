"""Security boundaries shared by configured outbound HTTP clients."""

from __future__ import annotations

from typing import BinaryIO
from urllib.parse import urlsplit

MAX_JSON_RESPONSE_BYTES = 2 * 1024 * 1024
MAX_BINARY_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_ERROR_RESPONSE_BYTES = 16 * 1024


class UpstreamResponseTooLarge(ValueError):
    pass


def validate_service_base_url(value: str) -> str:
    """Allow configured LAN HTTP(S) origins while rejecting ambiguous URL forms."""

    cleaned = value.strip().rstrip("/")
    parsed = urlsplit(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("service base URL must use http or https with a hostname")
    if parsed.username or parsed.password:
        raise ValueError("service base URL must not contain credentials")
    if parsed.query or parsed.fragment:
        raise ValueError("service base URL must not contain query or fragment")
    return cleaned


def read_limited(stream: BinaryIO, *, max_bytes: int) -> bytes:
    body = stream.read(max_bytes + 1)
    if len(body) > max_bytes:
        raise UpstreamResponseTooLarge(f"upstream response exceeds {max_bytes} bytes")
    return body


def read_error_detail(stream: BinaryIO) -> str:
    """Read a bounded upstream error body for internal diagnostics only."""

    try:
        body = read_limited(stream, max_bytes=MAX_ERROR_RESPONSE_BYTES)
    except UpstreamResponseTooLarge:
        return "upstream error body exceeded limit"
    return body.decode("utf-8", errors="replace")
