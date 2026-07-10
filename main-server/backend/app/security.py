"""Authentication helpers for the Main control plane (stdlib only).

Only mutation routers opt into these dependencies; health and read-only discovery stay
explicitly unauthenticated for probes and browser stream discovery.
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
import threading
import time
from collections.abc import Callable
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status

HEADER_TIMESTAMP = "X-SF-Timestamp"
HEADER_NONCE = "X-SF-Nonce"
HEADER_SIGNATURE = "X-SF-Signature"


def canonical_path(url_or_path: str) -> str:
    parsed = urlsplit(url_or_path)
    path = parsed.path or "/"
    return f"{path}?{parsed.query}" if parsed.query else path


def signing_payload(method: str, path: str, timestamp: str, nonce: str, body: bytes) -> bytes:
    return "\n".join((method.upper(), canonical_path(path), timestamp, nonce, hashlib.sha256(body).hexdigest())).encode()


def sign_headers(secret: str, method: str, url_or_path: str, body: bytes, *, timestamp: int | None = None, nonce: str | None = None) -> dict[str, str]:
    timestamp_text = str(int(time.time()) if timestamp is None else int(timestamp))
    nonce = nonce or secrets.token_urlsafe(24)
    signature = hmac.new(secret.encode(), signing_payload(method, url_or_path, timestamp_text, nonce, body), hashlib.sha256).hexdigest()
    return {HEADER_TIMESTAMP: timestamp_text, HEADER_NONCE: nonce, HEADER_SIGNATURE: signature}


class ReplayCache:
    def __init__(self) -> None:
        self._seen: dict[str, float] = {}
        self._lock = threading.Lock()

    def claim(self, key: str, ttl_sec: float) -> bool:
        now = time.time()
        with self._lock:
            self._seen = {item: expiry for item, expiry in self._seen.items() if expiry > now}
            if key in self._seen:
                return False
            self._seen[key] = now + ttl_sec
            return True


def verify_headers(secret: str, method: str, path: str, body: bytes, headers, *, skew_sec: float, replay_cache: ReplayCache) -> tuple[bool, int, str]:
    if not secret:
        return False, 503, "service HMAC secret is not configured"
    timestamp = headers.get(HEADER_TIMESTAMP)
    nonce = headers.get(HEADER_NONCE)
    signature = headers.get(HEADER_SIGNATURE)
    if not timestamp or not nonce or not signature:
        return False, 401, "missing service signature headers"
    try:
        if abs(time.time() - int(timestamp)) > skew_sec:
            return False, 401, "stale service signature timestamp"
    except ValueError:
        return False, 401, "invalid service signature timestamp"
    expected = hmac.new(secret.encode(), signing_payload(method, path, timestamp, nonce, body), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return False, 403, "invalid service signature"
    if not replay_cache.claim(f"{nonce}:{signature}", skew_sec):
        return False, 401, "replayed service signature"
    return True, 200, "ok"


def _bearer_token(request: Request) -> str | None:
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    return token if scheme.lower() == "bearer" and token else None


def require_role(role: str) -> Callable[[Request], None]:
    """Require an explicitly configured operator/admin bearer credential."""
    def dependency(request: Request) -> None:
        from app.core.config import settings

        configured = settings.admin_token if role == "admin" else settings.operator_token
        token = _bearer_token(request)
        if not configured:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="control-plane credentials are not configured")
        if not token or not hmac.compare_digest(configured, token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid or missing bearer token", headers={"WWW-Authenticate": "Bearer"})
    return dependency


require_operator = require_role("operator")
require_admin = require_role("admin")
