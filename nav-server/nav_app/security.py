"""Main-authenticated Nav mutation boundary (HMAC-SHA256, stdlib only).

GET routes are public only for read-only Nav diagnostics. Every state-changing
POST, PUT, PATCH, or DELETE route must use ``require_main_signature``.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import threading
import time
import secrets
from urllib.parse import urlsplit

from fastapi import HTTPException, Request

HEADER_TIMESTAMP = "X-SF-Timestamp"
HEADER_NONCE = "X-SF-Nonce"
HEADER_SIGNATURE = "X-SF-Signature"
GET_DIAGNOSTICS_AUTH_POLICY = "public-read-only-diagnostics"
_seen: dict[str, float] = {}
_lock = threading.Lock()


def _canonical_path(value: str) -> str:
    parsed = urlsplit(value)
    return f"{parsed.path or '/'}?{parsed.query}" if parsed.query else (parsed.path or "/")


def _payload(method: str, path: str, timestamp: str, nonce: str, body: bytes) -> bytes:
    return "\n".join((method.upper(), _canonical_path(path), timestamp, nonce, hashlib.sha256(body).hexdigest())).encode()


def sign_headers(secret: str, method: str, url_or_path: str, body: bytes) -> dict[str, str]:
    timestamp = str(int(time.time()))
    nonce = secrets.token_urlsafe(24)
    signature = hmac.new(secret.encode(), _payload(method, url_or_path, timestamp, nonce, body), hashlib.sha256).hexdigest()
    return {HEADER_TIMESTAMP: timestamp, HEADER_NONCE: nonce, HEADER_SIGNATURE: signature}


def _secret() -> str:
    return os.getenv("NAV_MAIN_HMAC_SECRET", os.getenv("LMS_MOVEMENT_HMAC_SECRET", "")).strip()


def _skew() -> float:
    return float(os.getenv("NAV_MAIN_HMAC_CLOCK_SKEW_SEC", os.getenv("LMS_MOVEMENT_HMAC_CLOCK_SKEW_SEC", "60")))


async def require_main_signature(request: Request) -> None:
    """Fail closed for all Nav state-changing routes; GET health/status remain public diagnostics."""
    secret = _secret()
    if not secret:
        raise HTTPException(status_code=503, detail="Main↔Nav HMAC secret is not configured")
    timestamp = request.headers.get(HEADER_TIMESTAMP)
    nonce = request.headers.get(HEADER_NONCE)
    signature = request.headers.get(HEADER_SIGNATURE)
    if not timestamp or not nonce or not signature:
        raise HTTPException(status_code=401, detail="missing Main signature headers")
    try:
        skew = _skew()
        if abs(time.time() - int(timestamp)) > skew:
            raise HTTPException(status_code=401, detail="stale Main signature timestamp")
    except ValueError:
        raise HTTPException(status_code=401, detail="invalid Main signature timestamp")
    body = await request.body()
    expected = hmac.new(secret.encode(), _payload(request.method, request.url.path + (f"?{request.url.query}" if request.url.query else ""), timestamp, nonce, body), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=403, detail="invalid Main signature")
    now = time.time()
    key = f"{nonce}:{signature}"
    with _lock:
        expired = [item for item, until in _seen.items() if until <= now]
        for item in expired:
            del _seen[item]
        if key in _seen:
            raise HTTPException(status_code=401, detail="replayed Main signature")
        _seen[key] = now + skew
