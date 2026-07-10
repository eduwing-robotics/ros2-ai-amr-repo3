#!/usr/bin/env python3
"""TCP contract smoke for the dedicated, signed vision-frame gateway ingress."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import secrets
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen


# A valid one-pixel PPM; OpenCV decodes it before the API stores the frame.
IMAGE = b"P6\n1 1\n255\n\x00\x00\x00"
PATH = "/api/v1/vision/frame"


def _multipart_body(boundary: str) -> bytes:
    return (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="source"\r\n\r\n'
        "tb3_1_picam\r\n"
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="image"; filename="frame.ppm"\r\n'
        "Content-Type: image/x-portable-pixmap\r\n\r\n"
    ).encode() + IMAGE + f"\r\n--{boundary}--\r\n".encode()


def _headers(secret: str, body: bytes, nonce: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    payload = "\n".join(("POST", PATH, timestamp, nonce, hashlib.sha256(body).hexdigest())).encode()
    return {
        "X-SF-Timestamp": timestamp,
        "X-SF-Nonce": nonce,
        "X-SF-Gateway-Signature": hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest(),
    }


def _post(base: str, body: bytes, headers: dict[str, str]) -> tuple[int, bytes]:
    request = Request(f"{base.rstrip('/')}{PATH}", data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=5) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True)
    parser.add_argument("--secret", required=True)
    args = parser.parse_args()
    boundary = f"nohardware-gateway-{secrets.token_hex(8)}"
    body = _multipart_body(boundary)
    content_type = {"Content-Type": f"multipart/form-data; boundary={boundary}"}

    unsigned_status, _ = _post(args.base, body, content_type)
    if unsigned_status != 401:
        raise SystemExit(f"unsigned gateway frame expected HTTP 401, got {unsigned_status}")

    signed_status, signed_body = _post(
        args.base,
        body,
        {**content_type, **_headers(args.secret, body, secrets.token_urlsafe(24))},
    )
    if signed_status != 200:
        raise SystemExit(f"signed gateway frame expected HTTP 200, got {signed_status}: {signed_body[:500]!r}")
    if json.loads(signed_body).get("source") != "tb3_1_picam":
        raise SystemExit("signed gateway frame response did not confirm the expected source")
    print("signed gateway frame ingress contract passed")


if __name__ == "__main__":
    main()
