from __future__ import annotations

from dataclasses import dataclass
import html
import json
import re
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlparse

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage

from .qos_profiles import build_bounded_image_qos_profile as build_qos_profile

VALID_SOURCE_IDS = {"global_cam_01", "tb3_1_picam", "tb3_2_picam"}
DEFAULT_OVERLAY_TOPICS = {
    "global_cam_01": "/sf/vision/sources/global_cam_01/overlay/compressed",
    "tb3_1_picam": "/sf/vision/sources/tb3_1_picam/overlay/compressed",
    "tb3_2_picam": "/sf/vision/sources/tb3_2_picam/overlay/compressed",
}
FORBIDDEN_TOPIC_FRAGMENTS = (
    "/cmd_vel",
    "cmd_vel",
    "/nav2",
    "nav2",
    "/navigate_to_pose",
    "/follow_path",
    "/controller_server",
    "/bt_navigator",
    "/waypoint_follower",
    "/parameter_events",
    "/rosout",
)
SAFE_VISION_PREFIX = "/sf/vision/"
BOUNDARY = "smartfactory-overlay-frame"
SOURCE_PATH_RE = re.compile(r"^/(?:stream|view)/([A-Za-z0-9_-]+)(?:\.mjpeg)?$")


@dataclass(frozen=True)
class FrameSnapshot:
    source: str
    sequence_id: int
    received_monotonic_s: float
    stamp_sec: int
    stamp_nanosec: int
    frame_id: str
    format: str
    content_type: str
    data: bytes


def parse_source_list(value: Any) -> list[str]:
    """Parse a comma/list source parameter and enforce the read-only allowlist."""

    if isinstance(value, (list, tuple)):
        raw_items = [str(item).strip() for item in value]
    else:
        raw_items = [item.strip() for item in str(value or "").split(",")]
    sources: list[str] = []
    for item in raw_items:
        if not item:
            continue
        if item not in VALID_SOURCE_IDS:
            raise ValueError(
                f"source {item!r} is not allowed; expected one of {sorted(VALID_SOURCE_IDS)}"
            )
        if item not in sources:
            sources.append(item)
    if not sources:
        raise ValueError("at least one overlay stream source must be enabled")
    return sources


def normalize_overlay_topic(source: str, topic: str | None = None) -> str:
    """Return the safe `/sf/vision/.../overlay/compressed` topic for a source."""

    if source not in VALID_SOURCE_IDS:
        raise ValueError(
            f"source {source!r} is not allowed; expected one of {sorted(VALID_SOURCE_IDS)}"
        )
    normalized = (topic or DEFAULT_OVERLAY_TOPICS[source]).strip()
    if not normalized.startswith("/"):
        raise ValueError("overlay topic must be absolute")
    if not normalized.startswith(SAFE_VISION_PREFIX):
        raise ValueError(
            f"overlay topic must stay under {SAFE_VISION_PREFIX!r}: {normalized}"
        )
    if any(fragment in normalized for fragment in FORBIDDEN_TOPIC_FRAGMENTS):
        raise ValueError(f"unsafe overlay topic is forbidden: {normalized}")
    expected_suffix = f"/sources/{source}/overlay/compressed"
    if not normalized.endswith(expected_suffix):
        raise ValueError(
            f"overlay topic must be source-scoped and compressed; expected suffix "
            f"{expected_suffix!r}, got {normalized!r}"
        )
    return normalized


def parse_overlay_topics_json(value: str | None, sources: list[str]) -> dict[str, str]:
    """Parse optional topic overrides while keeping all topics source-scoped."""

    overrides: dict[str, Any] = {}
    text = (value or "").strip()
    if text:
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"overlay_topics_json must be valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("overlay_topics_json must be a JSON object")
        overrides = parsed
    return {
        source: normalize_overlay_topic(source, overrides.get(source))
        for source in sources
    }


def clamp_max_fps(value: Any, *, default: float = 15.0, maximum: float = 30.0) -> float:
    try:
        fps = float(value)
    except (TypeError, ValueError):
        fps = default
    if fps <= 0:
        fps = default
    return max(1.0, min(fps, maximum))


def content_type_for_compressed_format(format_value: str) -> str:
    normalized = (format_value or "").strip().lower()
    if "png" in normalized:
        return "image/png"
    return "image/jpeg"


def format_mjpeg_part(frame: FrameSnapshot) -> bytes:
    headers = (
        f"--{BOUNDARY}\r\n"
        f"Content-Type: {frame.content_type}\r\n"
        f"Content-Length: {len(frame.data)}\r\n"
        f"X-Source: {frame.source}\r\n"
        f"X-Frame-Seq: {frame.sequence_id}\r\n"
        "\r\n"
    ).encode("ascii")
    return headers + frame.data + b"\r\n"


def _extract_source_from_path(path: str, query: dict[str, list[str]]) -> str | None:
    match = SOURCE_PATH_RE.match(path)
    if match:
        return match.group(1)
    if path in {
        "/api/v1/vision/overlay/stream",
        "/api/v1/vision/overlay/view",
        "/api/v1/vision/overlay/latest/stream",
    }:
        values = query.get("source") or []
        return values[0] if values else None
    return None


class LatestCompressedFrameStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sequence_by_source: dict[str, int] = {}
        self._frames: dict[str, FrameSnapshot] = {}

    def put(self, source: str, msg: CompressedImage) -> FrameSnapshot:
        payload = bytes(msg.data)
        if not payload:
            raise ValueError("compressed overlay payload is empty")
        with self._lock:
            sequence_id = self._sequence_by_source.get(source, 0) + 1
            self._sequence_by_source[source] = sequence_id
            frame = FrameSnapshot(
                source=source,
                sequence_id=sequence_id,
                received_monotonic_s=time.monotonic(),
                stamp_sec=int(getattr(msg.header.stamp, "sec", 0)),
                stamp_nanosec=int(getattr(msg.header.stamp, "nanosec", 0)),
                frame_id=str(getattr(msg.header, "frame_id", "") or ""),
                format=str(msg.format or "jpeg"),
                content_type=content_type_for_compressed_format(msg.format),
                data=payload,
            )
            self._frames[source] = frame
            return frame

    def latest(self, source: str) -> FrameSnapshot | None:
        with self._lock:
            return self._frames.get(source)

    def status_for(self, source: str, *, now: float | None = None) -> dict[str, Any]:
        now = time.monotonic() if now is None else now
        frame = self.latest(source)
        if frame is None:
            return {
                "has_frame": False,
                "latest_sequence_id": 0,
                "frame_age_s": None,
                "content_type": None,
                "frame_id": "",
            }
        return {
            "has_frame": True,
            "latest_sequence_id": frame.sequence_id,
            "frame_age_s": round(max(0.0, now - frame.received_monotonic_s), 3),
            "content_type": frame.content_type,
            "frame_id": frame.frame_id,
        }


class _ThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def _json_response(handler: BaseHTTPRequestHandler, status: HTTPStatus, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    handler.send_response(status.value)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    cors = getattr(handler.server, "cors_allow_origin", "")  # type: ignore[attr-defined]
    if cors:
        handler.send_header("Access-Control-Allow-Origin", cors)
    handler.end_headers()
    handler.wfile.write(body)


def _html_response(handler: BaseHTTPRequestHandler, body: str) -> None:
    payload = body.encode("utf-8")
    handler.send_response(HTTPStatus.OK.value)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(payload)))
    handler.send_header("Cache-Control", "no-store")
    cors = getattr(handler.server, "cors_allow_origin", "")  # type: ignore[attr-defined]
    if cors:
        handler.send_header("Access-Control-Allow-Origin", cors)
    handler.end_headers()
    handler.wfile.write(payload)


def make_handler(node: "VisionOverlayStreamBridge") -> type[BaseHTTPRequestHandler]:
    class VisionOverlayStreamHandler(BaseHTTPRequestHandler):
        server_version = "SmartFactoryVisionOverlayStreamBridge/0.1"
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt: str, *args: Any) -> None:
            node.get_logger().debug("vision overlay stream http: " + (fmt % args))

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler API
            _json_response(
                self,
                HTTPStatus.METHOD_NOT_ALLOWED,
                {
                    "detail": "read-only bridge: mutation methods are disabled",
                    "read_only": True,
                    "motion_command_allowed": False,
                },
            )

        do_PUT = do_PATCH = do_DELETE = do_POST

        def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler API
            self.send_response(HTTPStatus.NO_CONTENT.value)
            self.send_header("Allow", "GET, OPTIONS")
            cors = getattr(self.server, "cors_allow_origin", "")  # type: ignore[attr-defined]
            if cors:
                self.send_header("Access-Control-Allow-Origin", cors)
                self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
                self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Content-Length", "0")
            self.end_headers()

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler API
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            if parsed.path in {"/", "/api/v1/vision/overlay/view"}:
                source = _extract_source_from_path(parsed.path, query) or node.default_source
                self._send_view(source, query)
                return
            if parsed.path == "/api/v1/vision/bridge/status":
                _json_response(self, HTTPStatus.OK, node.status_payload())
                return

            source = _extract_source_from_path(parsed.path, query)
            if parsed.path.startswith("/view/"):
                self._send_view(source, query)
                return
            if parsed.path.startswith("/stream/") or parsed.path in {
                "/api/v1/vision/overlay/stream",
                "/api/v1/vision/overlay/latest/stream",
            }:
                self._stream_source(source, query)
                return
            _json_response(
                self,
                HTTPStatus.NOT_FOUND,
                {"detail": "unknown endpoint", "read_only": True},
            )

        def _validate_source(self, source: str | None) -> str | None:
            if not source:
                _json_response(
                    self,
                    HTTPStatus.BAD_REQUEST,
                    {"detail": "source is required", "allowed_sources": node.sources},
                )
                return None
            if source not in node.sources:
                _json_response(
                    self,
                    HTTPStatus.NOT_FOUND,
                    {"detail": f"source {source!r} is not enabled", "allowed_sources": node.sources},
                )
                return None
            return source

        def _send_view(self, source: str | None, query: dict[str, list[str]]) -> None:
            source = self._validate_source(source)
            if source is None:
                return
            fps = clamp_max_fps((query.get("max_fps") or [node.max_fps])[0], default=node.max_fps)
            escaped_source = html.escape(source)
            stream_url = (
                f"/api/v1/vision/overlay/stream?source={escaped_source}&max_fps={fps:g}"
            )
            source_links = "\n".join(
                f'<li><a href="/api/v1/vision/overlay/view?source={html.escape(item)}">{html.escape(item)}</a></li>'
                for item in node.sources
            )
            _html_response(
                self,
                f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>SmartFactory Vision Overlay Stream - {escaped_source}</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 24px; background: #111827; color: #f9fafb; }}
    img {{ max-width: 100%; border: 1px solid #374151; background: #030712; }}
    code, a {{ color: #93c5fd; }}
    .muted {{ color: #9ca3af; }}
  </style>
</head>
<body>
  <h1>SmartFactory Vision Overlay Stream</h1>
  <p class="muted">Read-only ROS overlay topic → MJPEG browser view. No motion/control APIs.</p>
  <p>source=<code>{escaped_source}</code>, max_fps=<code>{fps:g}</code></p>
  <img src="{stream_url}" alt="vision overlay stream for {escaped_source}" />
  <h2>Endpoints</h2>
  <ul>
    <li>Status: <a href="/api/v1/vision/bridge/status">/api/v1/vision/bridge/status</a></li>
    <li>Stream: <a href="{stream_url}">{stream_url}</a></li>
  </ul>
  <h2>Enabled sources</h2>
  <ul>{source_links}</ul>
</body>
</html>""",
            )

        def _stream_source(self, source: str | None, query: dict[str, list[str]]) -> None:
            source = self._validate_source(source)
            if source is None:
                return
            fps = clamp_max_fps((query.get("max_fps") or [node.max_fps])[0], default=node.max_fps)
            min_interval = 1.0 / fps
            self.send_response(HTTPStatus.OK.value)
            self.send_header("Content-Type", f"multipart/x-mixed-replace; boundary={BOUNDARY}")
            self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
            self.send_header("Pragma", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("X-Content-Type-Options", "nosniff")
            cors = getattr(self.server, "cors_allow_origin", "")  # type: ignore[attr-defined]
            if cors:
                self.send_header("Access-Control-Allow-Origin", cors)
            self.end_headers()

            last_sequence_id = 0
            last_send = 0.0
            while not node.shutdown_event.is_set():
                frame = node.frame_store.latest(source)
                if frame is None or frame.sequence_id == last_sequence_id:
                    time.sleep(0.01)
                    continue
                now = time.monotonic()
                delay = min_interval - (now - last_send)
                if delay > 0:
                    time.sleep(delay)
                try:
                    self.wfile.write(format_mjpeg_part(frame))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError, OSError):
                    break
                last_sequence_id = frame.sequence_id
                last_send = time.monotonic()

    return VisionOverlayStreamHandler


class VisionOverlayStreamBridge(Node):
    """Read-only browser bridge for AI overlay `CompressedImage` ROS topics."""

    def __init__(self, *, start_http_server: bool = True) -> None:
        super().__init__("vision_overlay_stream_bridge")
        self.declare_parameter("host", "0.0.0.0")
        self.declare_parameter("port", 8090)
        self.declare_parameter("sources", "tb3_1_picam")
        self.declare_parameter("overlay_topics_json", "")
        self.declare_parameter("max_fps", 15.0)
        self.declare_parameter("stale_after_sec", 2.0)
        self.declare_parameter("cors_allow_origin", "")
        self.declare_parameter("overlay_sub_qos_reliability", "reliable")
        self.declare_parameter("overlay_sub_qos_depth", 1)

        self.host = str(self.get_parameter("host").value)
        self.port = int(self.get_parameter("port").value)
        self.sources = parse_source_list(self.get_parameter("sources").value)
        self.default_source = self.sources[0]
        self.overlay_topics = parse_overlay_topics_json(
            str(self.get_parameter("overlay_topics_json").value),
            self.sources,
        )
        self.max_fps = clamp_max_fps(self.get_parameter("max_fps").value)
        self.stale_after_sec = max(0.1, float(self.get_parameter("stale_after_sec").value))
        self.cors_allow_origin = str(self.get_parameter("cors_allow_origin").value).strip()
        self.overlay_sub_qos_reliability = str(
            self.get_parameter("overlay_sub_qos_reliability").value
        )
        self.overlay_sub_qos_depth = max(1, int(self.get_parameter("overlay_sub_qos_depth").value))
        overlay_sub_qos = build_qos_profile(
            self.overlay_sub_qos_reliability,
            depth=self.overlay_sub_qos_depth,
            role="overlay subscribe",
        )

        self.frame_store = LatestCompressedFrameStore()
        self.shutdown_event = threading.Event()
        self._http_server: _ThreadingHTTPServer | None = None
        self._http_thread: threading.Thread | None = None
        self._received_frames_by_source = {source: 0 for source in self.sources}

        for source, topic in self.overlay_topics.items():
            self.create_subscription(
                CompressedImage,
                topic,
                lambda msg, source=source: self._on_overlay_image(source, msg),
                overlay_sub_qos,
            )

        if start_http_server:
            self._start_http_server()

        self.get_logger().info(
            "SmartFactory read-only vision overlay stream bridge ready: "
            f"http={self.host}:{self.port}, sources={self.sources}, "
            f"overlay_topics={self.overlay_topics}, max_fps={self.max_fps:g}, "
            f"overlay_sub_qos={self.overlay_sub_qos_reliability}, "
            "motion_command_allowed=False"
        )

    @property
    def diagnostics(self) -> dict[str, Any]:
        return {
            "host": self.host,
            "port": self.port,
            "sources": list(self.sources),
            "overlay_topics": dict(self.overlay_topics),
            "max_fps": self.max_fps,
            "overlay_sub_qos_reliability": self.overlay_sub_qos_reliability,
            "read_only": True,
            "motion_command_allowed": False,
            "received_frames_by_source": dict(self._received_frames_by_source),
        }

    def _start_http_server(self) -> None:
        handler = make_handler(self)
        server = _ThreadingHTTPServer((self.host, self.port), handler)
        server.cors_allow_origin = self.cors_allow_origin  # type: ignore[attr-defined]
        self._http_server = server
        self.host, self.port = server.server_address[:2]
        self._http_thread = threading.Thread(
            target=server.serve_forever,
            name="smartfactory-vision-overlay-stream-http",
            daemon=True,
        )
        self._http_thread.start()

    def _on_overlay_image(self, source: str, msg: CompressedImage) -> None:
        try:
            self.frame_store.put(source, msg)
        except ValueError as exc:
            self.get_logger().warning(f"Skipping invalid overlay frame for {source}: {exc}")
            return
        self._received_frames_by_source[source] = self._received_frames_by_source.get(source, 0) + 1

    def status_payload(self) -> dict[str, Any]:
        now = time.monotonic()
        sources = []
        for source in self.sources:
            status = self.frame_store.status_for(source, now=now)
            frame_age_s = status.get("frame_age_s")
            status.update(
                {
                    "source": source,
                    "overlay_topic": self.overlay_topics[source],
                    "stale": frame_age_s is None or float(frame_age_s) > self.stale_after_sec,
                    "view_path": f"/api/v1/vision/overlay/view?source={source}",
                    "stream_path": f"/api/v1/vision/overlay/stream?source={source}",
                    "alias_view_path": f"/view/{source}",
                    "alias_stream_path": f"/stream/{source}.mjpeg",
                }
            )
            sources.append(status)
        return {
            "service": "smartfactory-vision-overlay-stream-bridge",
            "version": "0.1.0",
            "read_only": True,
            "motion_command_allowed": False,
            "mutation_methods_allowed": [],
            "transport": "ros2-subscribe-compressed-image-to-mjpeg",
            "host": self.host,
            "port": self.port,
            "max_fps": self.max_fps,
            "stale_after_sec": self.stale_after_sec,
            "overlay_sub_qos_reliability": self.overlay_sub_qos_reliability,
            "sources": sources,
            "forbidden_topics": list(FORBIDDEN_TOPIC_FRAGMENTS),
        }

    def stop_http_server(self) -> None:
        self.shutdown_event.set()
        if self._http_server is not None:
            self._http_server.shutdown()
            self._http_server.server_close()
            self._http_server = None
        if self._http_thread is not None:
            self._http_thread.join(timeout=2.0)
            self._http_thread = None

    def destroy_node(self) -> bool:
        self.stop_http_server()
        return super().destroy_node()


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = VisionOverlayStreamBridge()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
