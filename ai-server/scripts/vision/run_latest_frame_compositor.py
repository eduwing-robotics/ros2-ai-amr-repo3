#!/usr/bin/env python3
"""Publish an AI Server latest-frame source as burned-overlay RTSP/H264.

This is used for TurtleBot Pi cameras without adding work to the Raspberry Pi:
ROS camera bringup and the existing Vision PC gateway continue to feed AI
Server, while this Vision-PC process reads the latest frame/result and pushes a
browser-facing WebRTC source into MediaMTX.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[2]
AI_SERVER_DIR = ROOT_DIR
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(AI_SERVER_DIR))

from scripts.vision.burned_overlay_compositor import (  # noqa: E402
    CompositorMetrics,
    MetricsWriter,
    RawVideoRtspPublisher,
    render_burned_overlay_bgr,
)
from scripts.vision.stream_event_state import successful_events  # noqa: E402


@dataclass(frozen=True)
class FrameSample:
    image: np.ndarray
    identity: str
    frame_seq: int | None
    frame_timestamp: str | None


def path_id(source: str, view: str) -> str:
    return f"{source}_{view}".replace("/", "_").replace("-", "_")


def read_json(url: str, *, timeout: float) -> tuple[int | None, dict[str, Any] | None, str | None]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - operator-configured local/LAN URL
            return response.status, json.loads(response.read().decode("utf-8")), None
    except Exception as exc:  # noqa: BLE001 - keep live compositor running across transient failures
        return None, None, f"{exc.__class__.__name__}: {exc}"


def read_image(url: str, *, timeout: float) -> FrameSample | None:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310 - operator-configured local/LAN URL
            payload = response.read()
            raw_frame_seq = response.headers.get("X-SF-Frame-Seq")
            frame_timestamp = response.headers.get("X-SF-Frame-Timestamp")
    except Exception:
        return None
    image_array = np.frombuffer(payload, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if image is None:
        return None
    try:
        frame_seq = int(raw_frame_seq) if raw_frame_seq is not None else None
    except ValueError:
        frame_seq = None
    identity = (
        f"seq:{frame_seq}"
        if frame_seq is not None
        else f"sha256:{hashlib.sha256(payload).hexdigest()}"
    )
    return FrameSample(
        image=image,
        identity=identity,
        frame_seq=frame_seq,
        frame_timestamp=frame_timestamp,
    )


def build_url(base: str, path: str, query: dict[str, str | int]) -> str:
    return base.rstrip("/") + path + "?" + urllib.parse.urlencode(query)


def _int_field(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return int(value)


def event_frame_seq(event: dict[str, Any]) -> int | None:
    metadata = event.get("metadata")
    if not isinstance(metadata, dict):
        return None
    return _int_field(metadata.get("frame_seq"))


def overlay_bound_events(
    status: int | None,
    body: Any,
    error: str | None,
    *,
    source: str,
    view: str,
) -> list[dict[str, Any]] | None:
    """Return events that are proven to belong to the latest overlay frame.

    ``/api/v1/detections/latest`` is a source-scoped history list, not a
    current-frame overlay contract.  The live PiCam compositor must not burn
    that history into every video frame, otherwise boxes from old frames linger.
    The diagnostic overlay metadata endpoint already exposes frame-bound events;
    accept only those events whose ``metadata.frame_seq`` matches the endpoint's
    latest overlay frame.
    """

    events = successful_events(status, body, error)
    if events is None or not isinstance(body, dict):
        return None

    requested_source = body.get("requested_source")
    if isinstance(requested_source, str) and requested_source != source:
        return None
    requested_view = body.get("requested_view")
    if isinstance(requested_view, str) and requested_view != view:
        return None

    overlay = body.get("overlay")
    if not isinstance(overlay, dict):
        # Refuse unbound history payloads by default.  A custom --events-url that
        # points back at /detections/latest would otherwise reintroduce ghost
        # boxes.
        return None
    overlay_frame_seq = _int_field(overlay.get("frame_seq"))
    if overlay_frame_seq is None:
        return None

    return [event for event in events if event_frame_seq(event) == overlay_frame_seq]


def overlay_payload_frame_seq(body: Any) -> int | None:
    if not isinstance(body, dict):
        return None
    overlay = body.get("overlay")
    if not isinstance(overlay, dict):
        return None
    return _int_field(overlay.get("frame_seq"))


def events_for_render(
    events: list[dict[str, Any]],
    *,
    last_event_update_s: float,
    now_s: float,
    stale_overlay_after_ms: float,
) -> tuple[list[dict[str, Any]], bool]:
    stale = (
        last_event_update_s <= 0 or (now_s - last_event_update_s) * 1000.0 > stale_overlay_after_ms
    )
    if stale:
        return [], True
    return events, False


def run(args: argparse.Namespace) -> int:
    pid = path_id(args.source, args.view)
    rtsp_url = args.rtsp_url or f"rtsp://127.0.0.1:{args.mediamtx_rtsp_port}/{pid}"
    metrics = CompositorMetrics(
        source=args.source,
        view=args.view,
        path_id=pid,
        target_fps=args.target_fps,
        ai_fps=args.ai_fps,
    )
    metrics_writer = MetricsWriter(Path(args.metrics_dir) / f"{pid}.json")
    frame_url = args.frame_url or build_url(
        args.ai_server_url,
        "/api/v1/vision/frame/latest/image",
        {"source": args.source, "view": args.view},
    )
    events_url = args.events_url or build_url(
        args.ai_server_url,
        "/api/v1/vision/overlay/metadata",
        {"source": args.source, "view": args.view, "limit": args.events_limit},
    )
    publisher: RawVideoRtspPublisher | None = None
    events: list[dict[str, Any]] = []
    last_event_poll_s = 0.0
    last_event_update_s = 0.0
    last_overlay_frame_seq: int | None = None
    last_frame_identity: str | None = None
    last_rendered_overlay: np.ndarray | None = None
    frame_seq = 0
    interval_s = 1.0 / max(1.0, args.target_fps)
    ai_interval_s = 1.0 / max(0.1, args.ai_fps)

    print(
        "latest-frame compositor running: "
        f"source={args.source}, view={args.view}, frame_url={frame_url}, "
        f"events_url={events_url}, rtsp={rtsp_url}, target_fps={args.target_fps}",
        flush=True,
    )

    try:
        while args.max_frames <= 0 or frame_seq < args.max_frames:
            loop_start = time.monotonic()
            now = time.monotonic()
            if now - last_event_poll_s >= ai_interval_s:
                status, payload, error = read_json(events_url, timeout=args.timeout)
                updated_events = overlay_bound_events(
                    status,
                    payload,
                    error,
                    source=args.source,
                    view=args.view,
                )
                overlay_frame_seq = overlay_payload_frame_seq(payload)
                if (
                    updated_events is not None
                    and overlay_frame_seq is not None
                    and overlay_frame_seq != last_overlay_frame_seq
                ):
                    events = updated_events
                    last_event_update_s = now
                    last_overlay_frame_seq = overlay_frame_seq
                last_event_poll_s = now

            sample = read_image(frame_url, timeout=args.timeout)
            if sample is None:
                metrics.stale_frames += 1
                metrics.last_error = "latest_frame_unavailable"
                metrics_writer.write(metrics)
                time.sleep(min(0.25, interval_s))
                continue

            frame_seq += 1
            frame = sample.image
            shape = (int(frame.shape[1]), int(frame.shape[0]))
            try:
                if sample.identity != last_frame_identity or last_rendered_overlay is None:
                    draw_events, stale = events_for_render(
                        events,
                        last_event_update_s=last_event_update_s,
                        now_s=time.monotonic(),
                        stale_overlay_after_ms=args.stale_overlay_after_ms,
                    )
                    overlay = render_burned_overlay_bgr(
                        frame,
                        source=args.source,
                        view=args.view,
                        frame_seq=sample.frame_seq or frame_seq,
                        frame_timestamp=sample.frame_timestamp,
                        events=draw_events,
                        stale=stale,
                    )
                    last_frame_identity = sample.identity
                    last_rendered_overlay = overlay
                else:
                    overlay = last_rendered_overlay
                    metrics.repeated_frames += 1
                if publisher is not None and (
                    publisher.width != shape[0] or publisher.height != shape[1]
                ):
                    publisher.close()
                    publisher = None
                if publisher is None:
                    publisher = RawVideoRtspPublisher(
                        rtsp_url=rtsp_url,
                        width=shape[0],
                        height=shape[1],
                        fps=args.target_fps,
                        bitrate=args.bitrate,
                        bufsize=args.bufsize,
                        gop=args.gop,
                        encoder=args.encoder,
                        preset=args.preset,
                        ffmpeg_bin=args.ffmpeg_bin,
                    )
                publisher.write(overlay)
                metrics.output_frames += 1
                metrics.input_frames += 1
                metrics.last_error = None
            except Exception as exc:  # noqa: BLE001
                metrics.last_error = f"{exc.__class__.__name__}: {exc}"
                metrics.ffmpeg_restarts += 1
                print(f"WARN: latest-frame compositor publish failed: {exc}", file=sys.stderr)
                time.sleep(0.2)
            metrics_writer.write(metrics)
            elapsed = time.monotonic() - loop_start
            if elapsed < interval_s:
                time.sleep(interval_s - elapsed)
    finally:
        if publisher is not None:
            publisher.close()
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--view", default=os.environ.get("PICAM_WEBRTC_VIEW", "full"))
    parser.add_argument(
        "--ai-server-url", default=os.environ.get("AI_SERVER_URL", "http://127.0.0.1:8100")
    )
    parser.add_argument("--frame-url", default="")
    parser.add_argument("--events-url", default="")
    parser.add_argument("--events-limit", type=int, default=20)
    parser.add_argument("--rtsp-url", default="")
    parser.add_argument(
        "--mediamtx-rtsp-port", default=os.environ.get("MEDIAMTX_RTSP_PORT", "18554")
    )
    parser.add_argument(
        "--target-fps", type=float, default=float(os.environ.get("PICAM_WEBRTC_TARGET_FPS", "30"))
    )
    parser.add_argument(
        "--ai-fps", type=float, default=float(os.environ.get("PICAM_WEBRTC_AI_FPS", "5"))
    )
    parser.add_argument(
        "--metrics-dir",
        default=os.environ.get(
            "VISION_WEBRTC_COMPOSITOR_METRICS_DIR", ".run/vision/compositor-metrics"
        ),
    )
    parser.add_argument(
        "--timeout", type=float, default=float(os.environ.get("PICAM_WEBRTC_HTTP_TIMEOUT_S", "0.5"))
    )
    parser.add_argument(
        "--stale-overlay-after-ms",
        type=float,
        default=float(os.environ.get("PICAM_WEBRTC_STALE_OVERLAY_AFTER_MS", "1500")),
    )
    parser.add_argument(
        "--bitrate",
        default=os.environ.get(
            "PICAM_WEBRTC_BITRATE", os.environ.get("WEBRTC_SIDECAR_BITRATE", "1800k")
        ),
    )
    parser.add_argument(
        "--bufsize",
        default=os.environ.get(
            "PICAM_WEBRTC_BUFSIZE", os.environ.get("WEBRTC_SIDECAR_BUFSIZE", "500k")
        ),
    )
    parser.add_argument(
        "--gop",
        type=int,
        default=int(os.environ.get("PICAM_WEBRTC_GOP", os.environ.get("WEBRTC_SIDECAR_GOP", "15"))),
    )
    parser.add_argument(
        "--encoder",
        default=os.environ.get(
            "PICAM_WEBRTC_ENCODER", os.environ.get("WEBRTC_SIDECAR_ENCODER", "libx264")
        ),
    )
    parser.add_argument(
        "--preset",
        default=os.environ.get(
            "PICAM_WEBRTC_PRESET", os.environ.get("WEBRTC_SIDECAR_X264_PRESET", "ultrafast")
        ),
    )
    parser.add_argument("--ffmpeg-bin", default=os.environ.get("FFMPEG_BIN", "ffmpeg"))
    parser.add_argument("--max-frames", type=int, default=0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv or sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
