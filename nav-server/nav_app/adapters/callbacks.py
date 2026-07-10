"""Pinned Main callback adapter; rejects command-supplied destinations."""

import ipaddress
import json
import os
import re
import socket
from typing import Any, Dict
from urllib import error, request
from urllib.parse import urlsplit, urlunsplit

from nav_app.config import MAIN_API_BASE
from nav_app.settings import CALLBACK_TIMEOUT_SEC, MAIN_CALLBACK_HMAC_SECRET
from nav_app.security import sign_headers

_ALLOWED_PATHS = re.compile(r"^/movement/(?:command-events|results|robots/[A-Za-z0-9_-]+/status)$")


class _NoRedirect(request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: N802
        return None


def _canonical_url(value: str) -> str | None:
    try:
        parsed = urlsplit(value.strip())
        port = parsed.port
    except ValueError:
        return None
    if parsed.scheme.lower() not in {"https", "http"} or not parsed.hostname:
        return None
    if parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        return None
    path = parsed.path.rstrip("/")
    if any(segment in {".", ".."} for segment in path.split("/")) or "//" in path:
        return None
    host = parsed.hostname.rstrip(".").lower()
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return None
    netloc = f"[{host}]" if ":" in host else host
    if port is not None and port != {"https": 443, "http": 80}[parsed.scheme.lower()]:
        netloc = f"{netloc}:{port}"
    return urlunsplit((parsed.scheme.lower(), netloc, path, "", ""))


def _is_public_host(host: str, port: int) -> bool:
    try:
        addresses = {str(ipaddress.ip_address(host))}
    except ValueError:
        try:
            addresses = {item[4][0] for item in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)}
        except socket.gaierror:
            return False
    return bool(addresses) and all(ipaddress.ip_address(address).is_global for address in addresses)


def _configured_callback_url(url: str) -> str | None:
    candidate = _canonical_url(url)
    base = _canonical_url(MAIN_API_BASE)
    if not candidate or not base:
        return None
    parsed_base = urlsplit(base)
    nohardware_origins = {
        _canonical_url(item).rstrip("/")
        for item in os.getenv("NAV_NOHARDWARE_CALLBACK_ALLOWLIST", "").split(",")
        if _canonical_url(item)
    }
    base_origin = urlunsplit((parsed_base.scheme, parsed_base.netloc, "", "", ""))
    nohardware_allowed = (
        os.getenv("NAV_NOHARDWARE", "").strip().lower() in {"1", "true", "yes", "on"}
        and base_origin in nohardware_origins
    )
    if parsed_base.scheme != "https" and not (nohardware_allowed and parsed_base.scheme == "http"):
        return None
    expected_base = f"{base.rstrip('/')}/movement"
    # The candidate has to be a configured Main endpoint, not merely an allowed host.
    if not candidate.startswith(expected_base + "/"):
        return None
    candidate_path = urlsplit(candidate).path
    base_path = parsed_base.path.rstrip("/")
    relative_path = candidate_path[len(base_path):] if candidate_path.startswith(base_path) else ""
    if not _ALLOWED_PATHS.fullmatch(relative_path):
        return None
    parsed = urlsplit(candidate)
    if parsed.scheme != parsed_base.scheme or parsed.netloc != parsed_base.netloc:
        return None
    if not nohardware_allowed and not _is_public_host(
        parsed.hostname or "", parsed.port or (443 if parsed.scheme == "https" else 80)
    ):
        return None
    return candidate


def post_json_callback(url: str, payload: Dict[str, Any], label: str = "Callback") -> bool:
    canonical_url = _configured_callback_url(url)
    if not canonical_url:
        print(f"[{label} 경고] configured Main callback URL required: {url}")
        return False
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    if not MAIN_CALLBACK_HMAC_SECRET:
        print(f"[{label} 경고] Main callback HMAC secret is not configured")
        return False
    headers = {"Content-Type": "application/json"}
    headers.update(sign_headers(MAIN_CALLBACK_HMAC_SECRET, "POST", canonical_url, body))
    req = request.Request(canonical_url, data=body, headers=headers, method="POST")
    opener = request.build_opener(_NoRedirect())
    try:
        with opener.open(req, timeout=CALLBACK_TIMEOUT_SEC) as response:
            if 200 <= response.status < 300:
                return True
            print(f"[{label} 경고] {canonical_url} HTTP {response.status}")
    except (error.HTTPError, error.URLError, TimeoutError) as exc:
        print(f"[{label} 경고] {canonical_url} 전송 실패: {exc}")
    return False


def post_main_callback(path: str, payload: Dict[str, Any]) -> bool:
    """Report only a fixed, configured Main API callback endpoint."""
    if not MAIN_API_BASE:
        return True
    if not path.startswith("/"):
        return False
    return post_json_callback(f"{MAIN_API_BASE.rstrip('/')}{path}", payload, label="MainCallback")
