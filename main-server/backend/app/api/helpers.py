"""Shared helpers for API routers."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

from fastapi import HTTPException, Request

from app.core.config import settings

_COMMAND_EVENTS_PATH = "/movement/command-events"


def _fail(detail: str) -> None:
    raise HTTPException(status_code=503, detail=f"callback configuration invalid: {detail}")


def _canonical_url(value: str) -> str:
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        _fail("invalid URL")
    if parsed.scheme.lower() not in {"https", "http"} or not parsed.hostname:
        _fail("URL must be absolute http(s)")
    if parsed.username is not None or parsed.password is not None:
        _fail("URL credentials are forbidden")
    if parsed.query or parsed.fragment:
        _fail("URL query and fragment are forbidden")
    path = parsed.path.rstrip("/")
    if any(segment in {".", ".."} for segment in path.split("/")) or "//" in path:
        _fail("URL path is not canonical")
    host = parsed.hostname.rstrip(".").lower()
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        _fail("invalid hostname")
    is_ipv6 = ":" in host
    netloc = f"[{host}]" if is_ipv6 else host
    if port is not None and port != {"https": 443, "http": 80}[parsed.scheme.lower()]:
        netloc = f"{netloc}:{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, path, "", ""))


def _origin(url: str) -> str:
    parsed = urlsplit(url)
    return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))


def _is_private_address(address: str) -> bool:
    ip = ipaddress.ip_address(address)
    return not ip.is_global


def _validate_public_host(host: str, port: int) -> None:
    try:
        ip = ipaddress.ip_address(host)
        addresses = {str(ip)}
    except ValueError:
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
        except socket.gaierror:
            _fail("callback hostname cannot be resolved")
    if not addresses or any(_is_private_address(address) for address in addresses):
        _fail("callback host resolves to non-public address")


def _allowed_origins() -> set[str]:
    configured = settings.callback_allowlist or ((settings.callback_base_url or settings.public_base_url),)
    return {_origin(_canonical_url(value)) for value in configured if value}


def _nohardware_origins() -> set[str]:
    return {_origin(_canonical_url(value)) for value in settings.nohardware_callback_allowlist if value}


def _configured_callback_base() -> str:
    base = _canonical_url(settings.api_callback_base_url()) if settings.api_callback_base_url() else ""
    if not base:
        _fail("LMS_CALLBACK_BASE_URL is required")
    parsed = urlsplit(base)
    if parsed.scheme == "http" and not settings.callback_allow_http:
        _fail("HTTP callbacks are disabled")
    expected_path = settings.api_prefix.rstrip("/")
    if parsed.path not in {"", expected_path}:
        _fail("callback base must not contain an arbitrary path")
    base = urlunsplit((parsed.scheme, parsed.netloc, expected_path, "", ""))
    origin = _origin(base)
    nohardware_allowed = settings.nohardware_mode and origin in _nohardware_origins()
    if not nohardware_allowed:
        if origin not in _allowed_origins():
            _fail("callback base is not allowlisted")
        _validate_public_host(parsed.hostname or "", parsed.port or (443 if parsed.scheme == "https" else 80))
    return base


def command_events_callback_url() -> str:
    """Return the one server-configured callback endpoint Nav may call."""
    return f"{_configured_callback_base()}{_COMMAND_EVENTS_PATH}"


def callback_base_url(request: Request | None = None, override: str | None = None) -> str:
    """Resolve only the configured Main callback base; request/user overrides are ignored."""
    del request, override
    return _configured_callback_base()


def with_callback(payload: dict, request: Request | None = None) -> dict:
    """Inject the server-owned callback base into a mission payload."""
    del request
    payload["callback_base_url"] = callback_base_url()
    return payload
