"""Fail-closed Main→AI HMAC authentication for mutation endpoints."""
from __future__ import annotations

import hashlib
import hmac
import threading
import time
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, status

HEADER_TIMESTAMP = "X-SF-Timestamp"
HEADER_NONCE = "X-SF-Nonce"
HEADER_SIGNATURE = "X-SF-Signature"
HEADER_GATEWAY_SIGNATURE = "X-SF-Gateway-Signature"


def _canonical_path(url_or_path: str) -> str:
    parsed = urlsplit(url_or_path)
    return f"{parsed.path or '/'}?{parsed.query}" if parsed.query else (parsed.path or "/")


def _payload(method: str, path: str, timestamp: str, nonce: str, body: bytes) -> bytes:
    return "\n".join((method.upper(), _canonical_path(path), timestamp, nonce, hashlib.sha256(body).hexdigest())).encode()


class _ReplayCache:
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


_replay_cache = _ReplayCache()


async def _require_hmac(
    request: Request, *, secret: str, signature_header: str, credential_name: str, replay_scope: str
) -> None:
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{credential_name} authentication is not configured",
        )
    timestamp = request.headers.get(HEADER_TIMESTAMP)
    nonce = request.headers.get(HEADER_NONCE)
    signature = request.headers.get(signature_header)
    if not timestamp or not nonce or not signature:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"missing {credential_name} signature")
    if len(nonce) > 256 or len(signature) != hashlib.sha256().digest_size * 2:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"invalid {credential_name} signature")
    try:
        from .config import get_settings

        clock_skew_sec = get_settings().main_hmac_clock_skew_sec
        if abs(time.time() - int(timestamp)) > clock_skew_sec:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"stale {credential_name} signature")
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"invalid {credential_name} signature") from exc
    body = request.scope.get("smartfactory.raw_request_body")
    if not isinstance(body, bytes):
        body = await request.body()
    expected = hmac.new(
        secret.encode(),
        _payload(request.method, str(request.url), timestamp, nonce, body),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"invalid {credential_name} signature")
    if not _replay_cache.claim(f"{replay_scope}:{nonce}", clock_skew_sec):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=f"replayed {credential_name} signature")


async def require_main_hmac(request: Request) -> None:
    """Accept only a fresh, signed Main service mutation; never reveal secrets."""
    from .config import get_settings

    await _require_hmac(
        request,
        secret=get_settings().main_hmac_secret,
        signature_header=HEADER_SIGNATURE,
        credential_name="Main service",
        replay_scope="main",
    )


async def require_vision_gateway_hmac(request: Request) -> None:
    """Accept only the scoped ROS gateway credential for frame cache ingress."""
    from .config import get_settings

    settings = get_settings()
    if settings.ai_debug_mutations_enabled:
        return
    await _require_hmac(
        request,
        secret=settings.vision_gateway_hmac_secret,
        signature_header=HEADER_GATEWAY_SIGNATURE,
        credential_name="vision gateway",
        replay_scope="vision-gateway",
    )


async def require_protected_debug_mutation(request: Request) -> None:
    """Protect debug ingress unless an explicitly isolated debug mode is enabled.

    Debug frame sources share the latest-frame cache with production evidence
    evaluation. They must therefore never be publicly writable in production.
    """
    from .config import get_settings

    if get_settings().ai_debug_mutations_enabled:
        return
    await require_main_hmac(request)
