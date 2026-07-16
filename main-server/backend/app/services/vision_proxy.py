"""Vision/AI 서버 image/metadata 프록시 경계.

실시간 영상은 AI 서버(`settings.vision_api_base_url`) 또는 stream bridge
(`settings.vision_stream_base_url`)가 source별 latest frame/overlay를 내보낸다.
Main이 이를 중계(proxy)해서, AI/stream 서버를 외부에 노출하거나 CORS를
열지 않고도 LAN의 브라우저가 Main 단일 origin으로 영상을 볼 수 있게 한다.

이미지 bytes는 DB에 저장하지 않는다(문서 "image pull" 원칙). Main은 통과만 시킨다.

base 주소는 canonical 호스트명(.local) 하나만 사용한다. 영상 전송 방식의
WebRTC→MJPEG 전환과 서비스 endpoint 우회는 서로 다른 개념이며, endpoint
IP 폴백은 서비스 정체성을 나누므로 제공하지 않는다.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from app.core.config import settings
from app.security import sign_headers
from app.services.api_logs import begin_call, finish_call


class VisionUpstreamError(RuntimeError):
    """Vision/AI 서버 도달 실패(연결/타임아웃). HTTP 상태 코드를 함께 전달한다."""

    def __init__(self, message: str, status_code: int = 502):
        super().__init__(message)
        self.status_code = status_code


def _api_bases() -> list[str]:
    """Return the single canonical AI service endpoint."""
    return [settings.vision_api_base_url] if settings.vision_api_base_url else []


def _stream_bases() -> list[str]:
    """Return the single canonical stream-bridge endpoint."""
    return [settings.vision_stream_base_url] if settings.vision_stream_base_url else []


def fetch_image(kind: str, source: str) -> tuple[bytes, str]:
    """AI 서버에서 source의 latest frame/overlay image를 가져온다.

    kind: "frame" 또는 "overlay".
    반환: (image_bytes, content_type).
    upstream 4xx(unknown source/no frame)는 그대로 status_code를 담아 raise한다.
    """
    path = f"/api/v1/vision/{kind}/latest/image"
    return _get_binary(path, {"source": source}, _api_bases())


def fetch_overlay_meta(source: str) -> tuple[bytes, str]:
    """overlay 메타데이터 JSON(staleness/visual_state)을 통과시킨다."""
    return _get_binary("/api/v1/vision/overlay/latest", {"source": source}, _api_bases())


def fetch_bridge_status() -> tuple[bytes, str]:
    """stream bridge 상태 JSON을 통과시킨다."""
    return _get_binary("/api/v1/vision/bridge/status", {}, _stream_bases(), service="camera")


def _health_timeout_sec() -> float:
    return settings.vision_timeout_sec


def _probe_bridge_health() -> dict[str, object]:
    """Stream bridge(:8090) /bridge/status 도달성."""
    bases = _stream_bases()
    last_error = "no vision stream base configured"
    last_url = ""
    for base in bases:
        url = _url(base, "/api/v1/vision/bridge/status", {})
        last_url = url
        req = Request(url, method="GET", headers={"Accept": "application/json"})
        try:
            with urlopen(req, timeout=_health_timeout_sec()) as res:
                body = res.read()
                content_type = res.headers.get("Content-Type", "application/json")
            payload = json.loads(body.decode("utf-8")) if body else {}
            return {
                "ok": True,
                "base_url": base,
                "content_type": content_type,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "response": payload,
            }
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            return {
                "ok": False,
                "base_url": base,
                "error": f"HTTP {exc.code}: {detail}",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "url": url,
            }
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = str(getattr(exc, "reason", exc))
            continue
    return {
        "ok": False,
        "base_url": bases[0] if bases else "",
        "error": last_error,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "url": last_url,
    }


def _probe_ai_image_health(source: str) -> dict[str, object]:
    """AI 서버(:8100) overlay/latest 도달성 — image-pull 경로와 동일 base."""
    bases = _api_bases()
    last_error = "no vision api base configured"
    last_url = ""
    for base in bases:
        url = _url(base, "/api/v1/vision/overlay/latest", {"source": source})
        last_url = url
        req = Request(url, method="GET", headers={"Accept": "application/json"})
        try:
            with urlopen(req, timeout=_health_timeout_sec()) as res:
                res.read()
            return {
                "ok": True,
                "base_url": base,
                "source": source,
                "checked_at": datetime.now(timezone.utc).isoformat(),
            }
        except HTTPError as exc:
            if exc.code < 500:
                return {
                    "ok": True,
                    "base_url": base,
                    "source": source,
                    "checked_at": datetime.now(timezone.utc).isoformat(),
                    "note": f"upstream HTTP {exc.code}",
                }
            detail = exc.read().decode("utf-8", errors="replace")
            return {
                "ok": False,
                "base_url": base,
                "source": source,
                "error": f"HTTP {exc.code}: {detail}",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "url": url,
            }
        except (URLError, TimeoutError) as exc:
            last_error = str(getattr(exc, "reason", exc))
            continue
    return {
        "ok": False,
        "base_url": bases[0] if bases else "",
        "source": source,
        "error": last_error,
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "url": last_url,
    }


def fetch_camera_health(camera_sources: list[str] | None = None, *, force: bool = False) -> dict[str, object]:
    """카메라 헬스 — bridge(:8090) OR AI image-pull(:8100) 중 하나라도 ok면 연결."""
    from app.services.health_cache import get_cached_swr

    probe_source = (camera_sources or ["tb3_1_picam"])[0]

    def _compute() -> dict[str, object]:
        with ThreadPoolExecutor(max_workers=2) as pool:
            bridge_future = pool.submit(_probe_bridge_health)
            ai_future = pool.submit(_probe_ai_image_health, probe_source)
            bridge = bridge_future.result()
            ai = ai_future.result()
        bridge_ok = bool(bridge.get("ok"))
        ai_ok = bool(ai.get("ok"))
        ok = bridge_ok or ai_ok
        if ai_ok:
            source = "ai_image"
            base_url = str(ai.get("base_url") or "")
        elif bridge_ok:
            source = "bridge"
            base_url = str(bridge.get("base_url") or "")
        else:
            source = "none"
            base_url = str(ai.get("base_url") or bridge.get("base_url") or "")
        error = None if ok else str(ai.get("error") or bridge.get("error") or "camera unreachable")
        return {
            "ok": ok,
            "source": source,
            "base_url": base_url,
            "error": error,
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "bridge": bridge,
            "ai_image": ai,
        }

    return get_cached_swr("camera_health", _compute, force=force)


def fetch_bridge_health() -> dict[str, object]:
    """Vision stream bridge 연결 상태를 /status 헤더 표시용으로 조회한다."""
    bases = _stream_bases()
    last_error = "no vision stream base configured"
    last_url = ""
    for base in bases:
        url = _url(base, "/api/v1/vision/bridge/status", {})
        last_url = url
        req = Request(url, method="GET", headers={"Accept": "application/json"})
        try:
            with urlopen(req, timeout=_health_timeout_sec()) as res:
                body = res.read()
                content_type = res.headers.get("Content-Type", "application/json")
            payload = json.loads(body.decode("utf-8")) if body else {}
            return {
                "ok": True,
                "base_url": base,
                "content_type": content_type,
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "response": payload,
            }
        except HTTPError as exc:
            # 이름해석 성공(upstream이 상태를 줌) → 폴백하지 않는다.
            detail = exc.read().decode("utf-8", errors="replace")
            return {"ok": False, "base_url": base, "error": f"HTTP {exc.code}: {detail}", "checked_at": datetime.now(timezone.utc).isoformat(), "url": url}
        except (URLError, TimeoutError, json.JSONDecodeError) as exc:
            last_error = str(getattr(exc, "reason", exc))
            continue
    return {"ok": False, "base_url": bases[0] if bases else "", "error": last_error, "checked_at": datetime.now(timezone.utc).isoformat(), "url": last_url}


def open_mjpeg_stream(kind: str, source: str, max_fps: int, view: str = "full") -> tuple[Iterator[bytes], str]:
    """stream bridge의 MJPEG 응답을 chunk 단위로 그대로 흘려보낸다."""
    path = f"/api/v1/vision/{kind}/stream"
    params: dict[str, str] = {"source": source, "max_fps": str(max_fps)}
    if view:
        params["view"] = view
    bases = _stream_bases()
    last_reason = "no vision stream base configured"
    for base in bases:
        url = _url(base, path, params)
        req = Request(url, method="GET", headers={"Accept": "multipart/x-mixed-replace,*/*"})
        ctx = begin_call("camera", f"{kind}_stream", "GET", url, source=source)
        try:
            res = urlopen(req, timeout=settings.vision_stream_timeout_sec)
            finish_call(ctx, True, 200, "stream opened")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            finish_call(ctx, False, exc.code, detail)
            raise VisionUpstreamError(f"vision stream upstream HTTP {exc.code}: {detail}", status_code=exc.code) from exc
        except (URLError, TimeoutError) as exc:
            last_reason = str(getattr(exc, "reason", exc))
            finish_call(ctx, False, "unreachable", last_reason)
            continue

        content_type = res.headers.get("Content-Type", "multipart/x-mixed-replace")

        def chunks() -> Iterator[bytes]:
            try:
                while True:
                    chunk = res.read1(65536)
                    if not chunk:
                        break
                    yield chunk
            finally:
                res.close()

        return chunks(), content_type

    raise VisionUpstreamError(f"vision stream upstream unreachable: {last_reason}", status_code=504)


def fetch_stream_transports(source: str, view: str = "full") -> tuple[bytes, str]:
    """AI 서버 stream transport 발견 JSON을 통과시킨다."""
    params: dict[str, str] = {"source": source}
    if view:
        params["view"] = view
    return _get_binary("/api/v1/vision/streams", params, _api_bases())


def post_webrtc_offer(source: str, view: str, offer_body: dict[str, object]) -> tuple[bytes, str]:
    """AI 서버 WebRTC offer/answer SDP 협상을 중계한다(미디어 전용)."""
    path = f"/api/v1/vision/streams/{source}/webrtc/offer"
    params: dict[str, str] = {"view": view} if view else {}
    payload = json.dumps(offer_body).encode("utf-8")
    return _post_binary(path, params, payload, _api_bases(), content_type="application/json", source=source)


def post_lift_load_evaluate(payload: dict[str, object]) -> dict:
    """AI 서버 lift-load evidence 평가를 호출한다."""
    return _post_json(
        "/api/v1/vision/evidence/lift-load/evaluate",
        payload,
        service="vision",
        kind="lift_load_evaluate",
    )


def _mutation_headers(method: str, url: str, body: bytes, content_type: str) -> dict[str, str]:
    if not settings.vision_hmac_secret:
        raise VisionUpstreamError("vision service authentication is not configured", status_code=503)
    return {"Accept": "application/json", "Content-Type": content_type, **sign_headers(settings.vision_hmac_secret, method, url, body)}


def _post_json(
    path: str,
    payload: dict[str, object],
    bases: list[str] | None = None,
    *,
    service: str = "vision",
    kind: str = "json_post",
) -> dict:
    """POST JSON to the configured service base and preserve HTTP errors."""
    bases = bases or _api_bases()
    body = json.dumps(payload).encode("utf-8")
    last_reason = "no vision base configured"
    for base in bases:
        url = _url(base, path, {})
        req = Request(
            url,
            data=body,
            method="POST",
            headers=_mutation_headers("POST", url, body, "application/json"),
        )
        ctx = begin_call(service, kind, "POST", url, source=str(payload.get("source") or ""))
        try:
            with urlopen(req, timeout=settings.vision_timeout_sec) as res:
                resp_body = res.read()
                finish_call(ctx, True, 200, "application/json")
                return json.loads(resp_body.decode("utf-8")) if resp_body else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            finish_call(ctx, False, exc.code, detail)
            raise VisionUpstreamError(f"vision upstream HTTP {exc.code}: {detail}", status_code=exc.code) from exc
        except (URLError, TimeoutError) as exc:
            last_reason = str(getattr(exc, "reason", exc))
            finish_call(ctx, False, "unreachable", last_reason)
            continue
        except json.JSONDecodeError as exc:
            raise VisionUpstreamError(f"vision upstream invalid JSON: {exc}", status_code=502) from exc
    raise VisionUpstreamError(f"vision upstream unreachable: {last_reason}", status_code=504)


def _get_binary(path: str, params: dict[str, str], bases: list[str], service: str = "vision") -> tuple[bytes, str]:
    last_reason = "no vision base configured"
    for base in bases:
        url = _url(base, path, params)
        req = Request(url, method="GET", headers={"Accept": "*/*"})
        ctx = begin_call(service, path.rsplit("/", 1)[-1] or path, "GET", url, source=params.get("source"))
        try:
            with urlopen(req, timeout=settings.vision_timeout_sec) as res:
                body = res.read()
                content_type = res.headers.get("Content-Type", "application/octet-stream")
                finish_call(ctx, True, 200, content_type)
                return body, content_type
        except HTTPError as exc:
            # upstream이 의미 있는 상태(400 unknown source, 404 no frame)를 주면 보존한다(폴백 안 함).
            detail = exc.read().decode("utf-8", errors="replace")
            finish_call(ctx, False, exc.code, detail)
            raise VisionUpstreamError(f"vision upstream HTTP {exc.code}: {detail}", status_code=exc.code) from exc
        except (URLError, TimeoutError) as exc:
            last_reason = str(getattr(exc, "reason", exc))
            finish_call(ctx, False, "unreachable", last_reason)
            continue
    raise VisionUpstreamError(f"vision upstream unreachable: {last_reason}", status_code=504)


def _post_binary(
    path: str,
    params: dict[str, str],
    body: bytes,
    bases: list[str],
    *,
    content_type: str = "application/json",
    service: str = "vision",
    source: str = "",
) -> tuple[bytes, str]:
    last_reason = "no vision base configured"
    for base in bases:
        url = _url(base, path, params)
        req = Request(
            url,
            data=body,
            method="POST",
            headers=_mutation_headers("POST", url, body, content_type),
        )
        ctx = begin_call(service, "webrtc_offer", "POST", url, source=source or params.get("source"))
        try:
            with urlopen(req, timeout=settings.vision_timeout_sec) as res:
                resp_body = res.read()
                resp_type = res.headers.get("Content-Type", "application/json")
                finish_call(ctx, True, 200, resp_type)
                return resp_body, resp_type
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            finish_call(ctx, False, exc.code, detail)
            raise VisionUpstreamError(f"vision upstream HTTP {exc.code}: {detail}", status_code=exc.code) from exc
        except (URLError, TimeoutError) as exc:
            last_reason = str(getattr(exc, "reason", exc))
            finish_call(ctx, False, "unreachable", last_reason)
            continue
    raise VisionUpstreamError(f"vision upstream unreachable: {last_reason}", status_code=504)


def _person_hazard_timeout_sec() -> float:
    return settings.person_hazard_timeout_sec


def _get_json(path: str, params: dict[str, str], bases: list[str] | None = None, *, service: str = "vision") -> dict:
    """GET JSON from the configured service base and preserve HTTP errors."""
    bases = bases or _api_bases()
    last_reason = "no vision base configured"
    for base in bases:
        url = _url(base, path, params)
        req = Request(url, method="GET", headers={"Accept": "application/json"})
        ctx = begin_call(service, path.rsplit("/", 1)[-1] or path, "GET", url, source=params.get("source") or params.get("robot_id"))
        try:
            with urlopen(req, timeout=_person_hazard_timeout_sec()) as res:
                body = res.read()
                finish_call(ctx, True, 200, "application/json")
                return json.loads(body.decode("utf-8")) if body else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            finish_call(ctx, False, exc.code, detail)
            raise VisionUpstreamError(f"vision upstream HTTP {exc.code}: {detail}", status_code=exc.code) from exc
        except (URLError, TimeoutError) as exc:
            last_reason = str(getattr(exc, "reason", exc))
            finish_call(ctx, False, "unreachable", last_reason)
            continue
        except json.JSONDecodeError as exc:
            raise VisionUpstreamError(f"vision upstream invalid JSON: {exc}", status_code=502) from exc
    raise VisionUpstreamError(f"vision upstream unreachable: {last_reason}", status_code=504)


def _put_json(path: str, payload: dict[str, object], bases: list[str] | None = None, *, service: str = "vision") -> dict:
    """PUT JSON to the configured service base."""
    bases = bases or _api_bases()
    body = json.dumps(payload).encode("utf-8")
    last_reason = "no vision base configured"
    for base in bases:
        url = _url(base, path, {})
        req = Request(
            url,
            data=body,
            method="PUT",
            headers=_mutation_headers("PUT", url, body, "application/json"),
        )
        ctx = begin_call(service, path.rsplit("/", 1)[-1] or path, "PUT", url, source=str(payload.get("source") or ""))
        try:
            with urlopen(req, timeout=_person_hazard_timeout_sec()) as res:
                resp_body = res.read()
                finish_call(ctx, True, 200, "application/json")
                return json.loads(resp_body.decode("utf-8")) if resp_body else {}
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            finish_call(ctx, False, exc.code, detail)
            raise VisionUpstreamError(f"vision upstream HTTP {exc.code}: {detail}", status_code=exc.code) from exc
        except (URLError, TimeoutError) as exc:
            last_reason = str(getattr(exc, "reason", exc))
            finish_call(ctx, False, "unreachable", last_reason)
            continue
        except json.JSONDecodeError as exc:
            raise VisionUpstreamError(f"vision upstream invalid JSON: {exc}", status_code=502) from exc
    raise VisionUpstreamError(f"vision upstream unreachable: {last_reason}", status_code=504)


def fetch_person_monitors() -> dict:
    return _get_json("/api/v1/vision/monitors", {})


def fetch_person_monitor_state(robot_id: str) -> dict:
    return _get_json("/api/v1/vision/monitors/person_drive/state", {"robot_id": robot_id})


def put_person_monitor_state(body: dict[str, object]) -> dict:
    return _put_json("/api/v1/vision/monitors/person_drive/state", body)


def fetch_person_hazard_latest(robot_id: str) -> dict:
    return _get_json("/api/v1/vision/hazards/person/latest", {"robot_id": robot_id})


def _url(base_url: str, path: str, params: dict[str, str]) -> str:
    query = urlencode(params)
    return f"{base_url}{path}" + (f"?{query}" if query else "")
