from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class HttpResult:
    ok: bool
    status_code: int | None
    error: str | None = None
    json_body: Any | None = None
    content: bytes | None = None
    content_type: str | None = None


def _response_json(response: requests.Response) -> Any | None:
    try:
        return response.json()
    except ValueError:
        return None


def post_frame(
    *,
    session: requests.Session,
    url: str,
    source_id: str,
    image_file: tuple[str, str, bytes],
    timeout: float,
) -> HttpResult:
    filename, content_type, image_bytes = image_file
    try:
        response = session.post(
            url,
            data={"source": source_id},
            files={"image": (filename, image_bytes, content_type)},
            timeout=timeout,
        )
    except requests.Timeout:
        return HttpResult(ok=False, status_code=None, error="AI Server frame POST timed out")
    except requests.RequestException as exc:
        return HttpResult(
            ok=False,
            status_code=None,
            error=f"AI Server frame POST failed: {exc.__class__.__name__}",
        )
    if 200 <= response.status_code < 300:
        return HttpResult(ok=True, status_code=response.status_code, json_body=_response_json(response))
    return HttpResult(
        ok=False,
        status_code=response.status_code,
        error=f"AI Server frame POST returned HTTP {response.status_code}",
        json_body=_response_json(response),
    )


def post_frame_process(
    *,
    session: requests.Session,
    url: str,
    source_id: str,
    image_file: tuple[str, str, bytes],
    timeout: float,
    force: bool = True,
    stale: bool = False,
) -> HttpResult:
    filename, content_type, image_bytes = image_file
    try:
        response = session.post(
            url,
            data={
                "source": source_id,
                "force": str(bool(force)).lower(),
                "stale": str(bool(stale)).lower(),
            },
            files={"image": (filename, image_bytes, content_type)},
            timeout=timeout,
        )
    except requests.Timeout:
        return HttpResult(ok=False, status_code=None, error="AI Server frame process timed out")
    except requests.RequestException as exc:
        return HttpResult(
            ok=False,
            status_code=None,
            error=f"AI Server frame process failed: {exc.__class__.__name__}",
        )
    if 200 <= response.status_code < 300:
        return HttpResult(ok=True, status_code=response.status_code, json_body=_response_json(response))
    return HttpResult(
        ok=False,
        status_code=response.status_code,
        error=f"AI Server frame process returned HTTP {response.status_code}",
        json_body=_response_json(response),
    )


def post_worker_tick(
    *,
    session: requests.Session,
    url: str,
    source_id: str,
    timeout: float,
    force: bool = False,
    stale: bool = False,
) -> HttpResult:
    try:
        response = session.post(
            url,
            json={"source": source_id, "force": force, "stale": stale},
            timeout=timeout,
        )
    except requests.Timeout:
        return HttpResult(ok=False, status_code=None, error="AI Server worker tick timed out")
    except requests.RequestException as exc:
        return HttpResult(
            ok=False,
            status_code=None,
            error=f"AI Server worker tick failed: {exc.__class__.__name__}",
        )
    if 200 <= response.status_code < 300:
        return HttpResult(ok=True, status_code=response.status_code, json_body=_response_json(response))
    return HttpResult(
        ok=False,
        status_code=response.status_code,
        error=f"AI Server worker tick returned HTTP {response.status_code}",
        json_body=_response_json(response),
    )


def get_json(
    *,
    session: requests.Session,
    url: str,
    source_id: str,
    timeout: float,
) -> HttpResult:
    try:
        response = session.get(url, params={"source": source_id}, timeout=timeout)
    except requests.Timeout:
        return HttpResult(ok=False, status_code=None, error="AI Server JSON GET timed out")
    except requests.RequestException as exc:
        return HttpResult(
            ok=False,
            status_code=None,
            error=f"AI Server JSON GET failed: {exc.__class__.__name__}",
        )
    if 200 <= response.status_code < 300:
        return HttpResult(ok=True, status_code=response.status_code, json_body=_response_json(response))
    return HttpResult(
        ok=False,
        status_code=response.status_code,
        error=f"AI Server JSON GET returned HTTP {response.status_code}",
        json_body=_response_json(response),
    )


def get_bytes(
    *,
    session: requests.Session,
    url: str,
    source_id: str,
    timeout: float,
) -> HttpResult:
    try:
        response = session.get(url, params={"source": source_id}, timeout=timeout)
    except requests.Timeout:
        return HttpResult(ok=False, status_code=None, error="AI Server bytes GET timed out")
    except requests.RequestException as exc:
        return HttpResult(
            ok=False,
            status_code=None,
            error=f"AI Server bytes GET failed: {exc.__class__.__name__}",
        )
    if 200 <= response.status_code < 300:
        return HttpResult(
            ok=True,
            status_code=response.status_code,
            content=bytes(response.content),
            content_type=response.headers.get("content-type"),
        )
    return HttpResult(
        ok=False,
        status_code=response.status_code,
        error=f"AI Server bytes GET returned HTTP {response.status_code}",
        json_body=_response_json(response),
    )
