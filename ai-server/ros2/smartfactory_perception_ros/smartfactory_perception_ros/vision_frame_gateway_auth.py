"""ROS-free canonical request signing for the vision frame gateway."""
from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from urllib.parse import urlsplit

HEADER_TIMESTAMP = "X-SF-Timestamp"
HEADER_NONCE = "X-SF-Nonce"
HEADER_GATEWAY_SIGNATURE = "X-SF-Gateway-Signature"


def _canonical_path(url_or_path: str) -> str:
    parsed = urlsplit(url_or_path)
    return f"{parsed.path or '/'}?{parsed.query}" if parsed.query else (parsed.path or "/")


def build_gateway_auth_headers(
    *,
    secret: str,
    method: str,
    url: str,
    body: bytes,
    timestamp: str | None = None,
    nonce: str | None = None,
) -> dict[str, str]:
    """Sign the exact prepared HTTP body with the scoped gateway credential."""
    if not secret:
        raise ValueError("vision gateway HMAC secret is required")
    timestamp = timestamp or str(int(time.time()))
    nonce = nonce or secrets.token_urlsafe(24)
    payload = "\n".join(
        (method.upper(), _canonical_path(url), timestamp, nonce, hashlib.sha256(body).hexdigest())
    ).encode()
    return {
        HEADER_TIMESTAMP: timestamp,
        HEADER_NONCE: nonce,
        HEADER_GATEWAY_SIGNATURE: hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest(),
    }
