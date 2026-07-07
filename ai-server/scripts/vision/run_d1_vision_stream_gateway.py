#!/usr/bin/env python3
"""Single-port HTTP Vision Stream Gateway for Main/HTML.

This process is intentionally ROS-free. It multiplexes source-based HTTP/MJPEG
requests to per-domain internal stream bridges and exposes a single public
base URL such as http://<vision-pc>:8090.
"""

from __future__ import annotations

import html
import ipaddress
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

BOUNDARY = "frame"
DEFAULT_SOURCES = {
    "global_cam_01": "http://127.0.0.1:8100",
    "tb3_1_picam": "http://127.0.0.1:18090",
    "tb3_2_picam": "http://127.0.0.1:18091",
}


def _allow_non_loopback_upstreams() -> bool:
    return os.environ.get("VISION_STREAM_ALLOW_NON_LOOPBACK_UPSTREAMS", "false").lower() == "true"


def _is_loopback_upstream(url: str) -> bool:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.lower()
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def _env_source_upstreams() -> dict[str, str]:
    text = os.environ.get("VISION_STREAM_SOURCE_UPSTREAMS_JSON", "").strip()
    if not text:
        return dict(DEFAULT_SOURCES)
    parsed = json.loads(text)
    if not isinstance(parsed, dict):
        raise ValueError("VISION_STREAM_SOURCE_UPSTREAMS_JSON must be a JSON object")
    upstreams: dict[str, str] = {}
    for key, value in parsed.items():
        source = str(key).strip()
        url = str(value).strip().rstrip("/")
        if not source or not _is_loopback_upstream(url):
            if (
                not source
                or not _allow_non_loopback_upstreams()
                or not url.startswith(("http://", "https://"))
            ):
                raise ValueError(f"invalid source upstream mapping: {key!r} -> {value!r}")
        upstreams[source] = url
    return upstreams


def _clamp_fps(value: str | None) -> float:
    try:
        fps = float(value or "30")
    except ValueError:
        fps = 30.0
    return max(1.0, min(30.0, fps))


def _csv_set(value: str) -> set[str]:
    return {item.strip() for item in value.split(",") if item.strip()}


def _env_ai_mjpeg_sources() -> set[str]:
    explicit = os.environ.get("VISION_STREAM_AI_MJPEG_SOURCES")
    if explicit is not None and explicit.strip():
        return _csv_set(explicit)
    global_source = (
        os.environ.get("VISION_GLOBAL_SOURCE_ID", "global_cam_01").strip() or "global_cam_01"
    )
    return {global_source}


def _validate_ai_mjpeg_sources(
    ai_mjpeg_sources: set[str],
    upstreams: dict[str, str],
    *,
    ai_server_url: str,
) -> None:
    unknown = sorted(ai_mjpeg_sources.difference(upstreams))
    if unknown:
        raise ValueError(
            "VISION_STREAM_AI_MJPEG_SOURCES contains source(s) not present in "
            f"VISION_STREAM_SOURCE_UPSTREAMS_JSON: {', '.join(unknown)}"
        )
    mismatched = sorted(
        source
        for source in ai_mjpeg_sources
        if upstreams[source].rstrip("/") != ai_server_url.rstrip("/")
    )
    if mismatched:
        raise ValueError(
            "VISION_STREAM_AI_MJPEG_SOURCES source(s) must use AI_SERVER_URL as upstream: "
            f"{', '.join(mismatched)}"
        )


def _overlay_upstream_url(
    *,
    upstream_base_url: str,
    ai_mjpeg_sources: set[str],
    source: str,
    view: str,
    max_fps: float,
) -> str:
    """Build the correct internal URL behind the public overlay stream route.

    The public gateway has a stable Main-facing contract:
      /api/v1/vision/overlay/stream?source=<id>&view=<view>&max_fps=<fps>

    Internally, GoPro/global-style sources in VISION_STREAM_AI_MJPEG_SOURCES
    are served by source/view-aware MJPEG endpoints, while TurtleBot PiCam
    sources are served by per-domain overlay bridge sidecars.  The bridge
    sidecars do not expose /api/v1/vision/stream/{source}.mjpeg, so routing
    every source through the AI Server path causes robot camera 404s and
    prevents WebRTC publishers from becoming ready.
    """
    upstream_base = upstream_base_url.rstrip("/")
    fps_text = f"{max_fps:g}"
    if source in ai_mjpeg_sources:
        return (
            f"{upstream_base}/api/v1/vision/stream/{urllib.parse.quote(source, safe='')}.mjpeg?"
            + urllib.parse.urlencode({"view": view, "max_fps": fps_text})
        )
    return f"{upstream_base}/api/v1/vision/overlay/stream?" + urllib.parse.urlencode(
        {"source": source, "max_fps": fps_text}
    )


def _json_get(url: str, *, timeout: float = 2.0) -> tuple[int, dict[str, Any] | None, str | None]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - local/LAN configured upstreams
            body = response.read()
            return response.status, json.loads(body.decode("utf-8")), None
    except Exception as exc:  # noqa: BLE001 - status endpoint should aggregate failures
        return 0, None, f"{exc.__class__.__name__}: {exc}"


class VisionStreamGatewayHandler(BaseHTTPRequestHandler):
    server_version = "SmartFactoryVisionStreamGateway/0.1"

    @property
    def upstreams(self) -> dict[str, str]:
        return self.server.source_upstreams  # type: ignore[attr-defined]

    @property
    def ai_server_url(self) -> str:
        return self.server.ai_server_url  # type: ignore[attr-defined]

    @property
    def ai_mjpeg_sources(self) -> set[str]:
        return self.server.ai_mjpeg_sources  # type: ignore[attr-defined]

    def log_message(self, fmt: str, *args: Any) -> None:  # keep stdout concise
        if os.environ.get("VISION_STREAM_GATEWAY_ACCESS_LOG", "false").lower() == "true":
            super().log_message(fmt, *args)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(HTTPStatus.NO_CONTENT.value)
        self.send_header("Allow", "GET, OPTIONS")
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_PUT(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_PATCH(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def do_DELETE(self) -> None:  # noqa: N802
        self._method_not_allowed()

    def _method_not_allowed(self) -> None:
        self.send_response(HTTPStatus.METHOD_NOT_ALLOWED.value)
        self.send_header("Allow", "GET, OPTIONS")
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": False, "error": "read-only gateway"}).encode())

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        query = urllib.parse.parse_qs(parsed.query)
        if parsed.path == "/api/v1/vision/bridge/status":
            self._status()
            return
        if parsed.path == "/api/v1/vision/overlay/view":
            self._view(query, stream_kind="overlay")
            return
        if parsed.path == "/api/v1/vision/overlay/stream":
            self._proxy_overlay_stream(query)
            return
        if parsed.path == "/api/v1/vision/frame/stream":
            self._raw_frame_stream(query)
            return
        self._json_response(HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})

    def _source_from_query(self, query: dict[str, list[str]]) -> str | None:
        source = (query.get("source") or [""])[0].strip()
        if source not in self.upstreams:
            self._json_response(
                HTTPStatus.BAD_REQUEST,
                {
                    "ok": False,
                    "error": "unknown source",
                    "source": source,
                    "allowed_sources": sorted(self.upstreams),
                },
            )
            return None
        return source

    def _json_response(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        self.send_response(status.value)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _status(self) -> None:
        sources: list[dict[str, Any]] = []
        ok = True
        for source, base in self.upstreams.items():
            status_code, data, error = _json_get(f"{base}/api/v1/vision/bridge/status")
            source_entry: dict[str, Any] | None = None
            if data:
                for candidate in data.get("sources", []):
                    if candidate.get("source") == source or candidate.get("source_id") == source:
                        source_entry = candidate
                        break
            if source_entry is None:
                status_code, data, error = _json_get(
                    f"{base}/api/v1/vision/streams?" + urllib.parse.urlencode({"source": source})
                )
                if data:
                    for candidate in data.get("sources", []):
                        if (
                            candidate.get("source") == source
                            or candidate.get("source_id") == source
                        ):
                            source_entry = candidate
                            break
            if source_entry is None:
                ok = False
                sources.append(
                    {
                        "source_id": source,
                        "status": "offline",
                        "upstream": base,
                        "error": error or f"HTTP {status_code}",
                        "stream_path": f"/api/v1/vision/overlay/stream?source={source}",
                        "raw_stream_path": f"/api/v1/vision/frame/stream?source={source}",
                    }
                )
                continue
            has_frame = bool(source_entry.get("has_frame"))
            stale = bool(source_entry.get("stale"))
            state = "online" if has_frame and not stale else "stale" if has_frame else "no_frame"
            sources.append(
                {
                    "source_id": source,
                    "status": state,
                    "upstream": base,
                    "last_frame_age_s": source_entry.get("frame_age_s"),
                    "fps": data.get("max_fps", source_entry.get("fps")),
                    "content_type": source_entry.get("content_type"),
                    "latest_sequence_id": source_entry.get("latest_sequence_id"),
                    "overlay_topic": source_entry.get("overlay_topic"),
                    "stream_path": f"/api/v1/vision/overlay/stream?source={source}",
                    "raw_stream_path": f"/api/v1/vision/frame/stream?source={source}",
                }
            )
        self._json_response(
            HTTPStatus.OK,
            {
                "ok": ok,
                "service": "vision-stream-bridge",
                "read_only": True,
                "motion_command_allowed": False,
                "bind": {
                    "host": self.server.server_address[0],
                    "port": self.server.server_address[1],
                },  # type: ignore[attr-defined]
                "source_count": len(sources),
                "sources": sources,
            },
        )

    def _view(self, query: dict[str, list[str]], *, stream_kind: str) -> None:
        source = self._source_from_query(query)
        if source is None:
            return
        max_fps = html.escape((query.get("max_fps") or ["30"])[0])
        view = html.escape((query.get("view") or ["full"])[0].strip() or "full")
        stream_path = (
            f"/api/v1/vision/{stream_kind}/stream?"
            f"source={urllib.parse.quote(source)}&view={urllib.parse.quote(view)}&max_fps={max_fps}"
        )
        source_links = "".join(
            f'<li><a href="/api/v1/vision/overlay/view?source={html.escape(s)}&view={view}">{html.escape(s)}</a></li>'
            for s in sorted(self.upstreams)
        )
        body = f"""<!doctype html>
<html><head><title>SmartFactory Vision Stream Gateway</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 18px; }}
.clock {{ margin: 8px 0 14px; font-size: 18px; font-weight: 600; }}
.hint {{ color: #555; font-size: 13px; }}
</style></head>
<body>
<h1>SmartFactory Vision Stream Gateway</h1>
<p>source={html.escape(source)} view={view} kind={html.escape(stream_kind)}</p>
<img src="{stream_path}" style="max-width: 100%; height: auto; border: 1px solid #ccc" />
<div class="clock">Local realtime: <span id="live-clock">--:--:--</span></div>
<div class="hint">Overlay image time updates on each received frame; this page clock keeps ticking even if frames pause.</div>
<h2>Sources</h2><ul>{source_links}</ul>
<script>
function updateClock() {{
  const now = new Date();
  document.getElementById("live-clock").textContent = now.toLocaleTimeString();
}}
updateClock();
setInterval(updateClock, 250);
</script>
</body></html>""".encode("utf-8")
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _proxy_overlay_stream(self, query: dict[str, list[str]]) -> None:
        source = self._source_from_query(query)
        if source is None:
            return
        max_fps = _clamp_fps((query.get("max_fps") or ["30"])[0])
        view = (query.get("view") or ["full"])[0].strip() or "full"
        upstream_url = _overlay_upstream_url(
            upstream_base_url=self.upstreams[source],
            ai_mjpeg_sources=self.ai_mjpeg_sources,
            source=source,
            view=view,
            max_fps=max_fps,
        )
        self._proxy_mjpeg_response(upstream_url)

    def _proxy_mjpeg_response(self, upstream_url: str) -> None:
        try:
            response = urllib.request.urlopen(upstream_url, timeout=5)  # noqa: S310 - configured local upstream
        except urllib.error.HTTPError as exc:
            self._json_response(
                HTTPStatus(exc.code), {"ok": False, "error": f"upstream HTTP {exc.code}"}
            )
            return
        except Exception as exc:  # noqa: BLE001
            self._json_response(HTTPStatus.BAD_GATEWAY, {"ok": False, "error": str(exc)})
            return
        with response:
            self.send_response(HTTPStatus.OK.value)
            self.send_header(
                "Content-Type",
                response.headers.get(
                    "Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}"
                ),
            )
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            while True:
                chunk = response.read(8192)
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break

    def _raw_frame_stream(self, query: dict[str, list[str]]) -> None:
        source = self._source_from_query(query)
        if source is None:
            return
        max_fps = _clamp_fps((query.get("max_fps") or ["30"])[0])
        min_interval_s = 1.0 / max_fps
        self.send_response(HTTPStatus.OK.value)
        self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
        self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Accel-Buffering", "no")
        self.end_headers()
        last_frame_seq: int | None = None
        while True:
            status, meta, _ = _json_get(
                f"{self.ai_server_url}/api/v1/vision/frame/latest?"
                + urllib.parse.urlencode({"source": source}),
                timeout=1.0,
            )
            frame = (meta or {}).get("frame") if status == 200 else None
            frame_seq = frame.get("frame_seq") if isinstance(frame, dict) else None
            if frame_seq is None or frame_seq == last_frame_seq:
                time.sleep(min_interval_s)
                continue
            try:
                image_response = urllib.request.urlopen(  # noqa: S310 - configured local upstream
                    f"{self.ai_server_url}/api/v1/vision/frame/latest/image?"
                    + urllib.parse.urlencode({"source": source}),
                    timeout=1.0,
                )
                with image_response:
                    image = image_response.read()
                    content_type = image_response.headers.get("Content-Type", "image/jpeg")
            except Exception:
                time.sleep(min_interval_s)
                continue
            part = (
                b"--"
                + BOUNDARY.encode("ascii")
                + b"\r\n"
                + f"Content-Type: {content_type}\r\n".encode("ascii")
                + f"X-Frame-Seq: {frame_seq}\r\n".encode("ascii")
                + b"\r\n"
                + image
                + b"\r\n"
            )
            try:
                self.wfile.write(part)
                self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, OSError):
                break
            last_frame_seq = int(frame_seq)
            time.sleep(min_interval_s)


class VisionStreamGatewayServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self, server_address: tuple[str, int], handler_cls: type[BaseHTTPRequestHandler]
    ) -> None:
        super().__init__(server_address, handler_cls)
        self.source_upstreams = _env_source_upstreams()
        self.ai_server_url = os.environ.get("AI_SERVER_URL", "http://127.0.0.1:8100").rstrip("/")
        self.ai_mjpeg_sources = _env_ai_mjpeg_sources()
        _validate_ai_mjpeg_sources(
            self.ai_mjpeg_sources,
            self.source_upstreams,
            ai_server_url=self.ai_server_url,
        )


def main() -> None:
    host = os.environ.get("VISION_STREAM_GATEWAY_HOST", "0.0.0.0")
    port = int(os.environ.get("VISION_STREAM_GATEWAY_PORT", "8090"))
    server = VisionStreamGatewayServer((host, port), VisionStreamGatewayHandler)
    print(
        "SmartFactory Vision Stream Gateway ready: "
        f"http={host}:{port}, sources={server.source_upstreams}, "
        f"ai_mjpeg_sources={sorted(server.ai_mjpeg_sources)}, "
        "read_only=True, motion_command_allowed=False",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
