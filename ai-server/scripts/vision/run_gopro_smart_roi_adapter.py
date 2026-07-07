#!/usr/bin/env python3
"""GoPro/global-camera smart ROI ingest adapter for the AI Server.

The adapter is intentionally ROS-free:
  1. read frames from an OpenCV-compatible source (GoPro webcam stream, UVC,
     RTSP/UDP/file),
  2. POST the full frame to /api/v1/vision/frame/process as global_cam_01,
  3. select a crop-first ROI locally and optionally POST that crop to the
     LiftRoiEvidence image endpoint for model-backed lift/load checks.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

ROOT_DIR = Path(__file__).resolve().parents[2]
AI_SERVER_DIR = ROOT_DIR
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(AI_SERVER_DIR))

try:
    import cv2
except ImportError as exc:  # pragma: no cover - environment diagnostic
    raise SystemExit("OpenCV is required. Install the AI Server env first.") from exc

from app.smart_roi import (  # noqa: E402
    crop_smart_roi,
    parse_normalized_bbox,
    select_smart_roi,
)
from scripts.vision.burned_overlay_compositor import (  # noqa: E402
    CompositorMetrics,
    MetricsWriter,
    RawVideoRtspPublisher,
    crop_frame,
    events_for_crop,
    letterbox_frame_and_events_bgr,
    letterbox_frame_bgr,
    render_burned_overlay_bgr,
)
from scripts.vision.stream_event_state import successful_events  # noqa: E402


def _opencv_source(value: str) -> int | str:
    stripped = value.strip()
    if stripped.isdigit():
        return int(stripped)
    return stripped


def _normalize_video_capture_url(value: str) -> str:
    stripped = value.strip()
    if stripped.startswith("udp://") and "?" not in stripped:
        # OpenGoPro TS webcam streams need FFMPEG overrun tolerance for stable
        # long-running reads. This mirrors OpenGoPro's own CV2 demo reader.
        return stripped + "?overrun_nonfatal=1&fifo_size=50000000"
    if stripped.startswith("rtsp://") and "rtsp_transport=" not in stripped:
        separator = "&" if "?" in stripped else "?"
        return stripped + f"{separator}rtsp_transport=tcp"
    return stripped


def _open_video_capture(value: str):
    source = _opencv_source(value)
    if isinstance(source, int):
        capture = cv2.VideoCapture(source)
        _configure_low_latency_capture(capture)
        return capture
    source = _normalize_video_capture_url(source)
    if source.startswith(("udp://", "rtsp://", "http://", "https://")):
        capture = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
        _configure_low_latency_capture(capture)
        return capture
    capture = cv2.VideoCapture(source)
    _configure_low_latency_capture(capture)
    return capture


def _configure_low_latency_capture(capture) -> None:
    try:
        capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    except Exception:  # noqa: BLE001 - OpenCV backends vary
        return


class LatestFrameCapture:
    """Background capture that always exposes the newest frame only.

    The GoPro/OpenGoPro path is a 30 FPS stream, while model-backed ROI
    evaluation may intentionally run at 3-10 FPS. Keeping only the latest frame
    avoids delayed AI decisions caused by OpenCV/FFMPEG queue buildup.
    """

    def __init__(self, input_value: str):
        self.input_value = input_value
        self.capture = _open_video_capture(input_value)
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._sequence = 0
        self._frame = None
        self._timestamp = 0.0
        self._failed_reads = 0

    def is_opened(self) -> bool:
        return bool(self.capture.isOpened())

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._capture_loop,
            name="gopro_latest_frame_capture",
            daemon=True,
        )
        self._thread.start()

    def latest(self):
        with self._lock:
            if self._frame is None:
                return None
            return self._sequence, self._timestamp, self._frame.copy()

    def diagnostics(self) -> dict[str, Any]:
        with self._lock:
            return {"capture_seq": self._sequence, "capture_failed_reads": self._failed_reads}

    def release(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        self.capture.release()

    def _capture_loop(self) -> None:
        while self._running:
            ok, frame = self.capture.read()
            if ok and frame is not None:
                timestamp = time.monotonic()
                with self._lock:
                    self._sequence += 1
                    self._timestamp = timestamp
                    self._frame = frame
            else:
                with self._lock:
                    self._failed_reads += 1
                time.sleep(0.02)


class SharedDetectionState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.events: list[dict[str, Any]] = []
        self.selection = None
        self.updated_at = 0.0

    def update(self, *, events: list[dict[str, Any]], selection: Any) -> None:
        with self._lock:
            self.events = [dict(event) for event in events]
            self.selection = selection
            self.updated_at = time.monotonic()

    def update_selection(self, *, selection: Any) -> None:
        """Track the current ROI selection without refreshing AI-result freshness."""

        with self._lock:
            self.selection = selection

    def snapshot(self) -> tuple[list[dict[str, Any]], Any, float]:
        with self._lock:
            return [dict(event) for event in self.events], self.selection, self.updated_at


def _path_id(source: str, view: str) -> str:
    return f"{source}_{view}".replace("/", "_").replace("-", "_")


class GoProWebRtcCompositor:
    """Publish GoPro burned-overlay streams to MediaMTX.

    ``--publish-webrtc`` controls whether the public full stream is emitted.
    ``--publish-roi-webrtc`` is intentionally independent so low-load lab
    profiles can keep the Main-facing full stream while avoiding the extra ROI
    crop/encode/RTSP publisher work.
    """

    def __init__(
        self,
        *,
        latest_capture: LatestFrameCapture,
        detection_state: SharedDetectionState,
        args: argparse.Namespace,
        roi_hint: tuple[float, float, float, float] | None,
    ) -> None:
        self.latest_capture = latest_capture
        self.detection_state = detection_state
        self.args = args
        self.roi_hint = roi_hint
        self.publish_roi = bool(args.publish_roi_webrtc)
        self._running = False
        self._thread: threading.Thread | None = None
        self._full_publisher: RawVideoRtspPublisher | None = None
        self._roi_publisher: RawVideoRtspPublisher | None = None
        metrics_dir = Path(args.webrtc_metrics_dir)
        self._full_metrics = CompositorMetrics(
            source=args.source,
            view="full",
            path_id=_path_id(args.source, "full"),
            target_fps=args.stream_target_fps,
            ai_fps=args.target_fps,
        )
        self._roi_metrics = (
            CompositorMetrics(
                source=args.source,
                view=args.roi_view,
                path_id=_path_id(args.source, args.roi_view),
                target_fps=args.stream_target_fps,
                ai_fps=args.target_fps,
            )
            if self.publish_roi
            else None
        )
        self._full_metrics_writer = MetricsWriter(
            metrics_dir / f"{self._full_metrics.path_id}.json"
        )
        self._roi_metrics_writer = (
            MetricsWriter(metrics_dir / f"{self._roi_metrics.path_id}.json")
            if self._roi_metrics is not None
            else None
        )

    def start(self) -> None:
        self._running = True
        self._thread = threading.Thread(
            target=self._loop,
            name="gopro_burned_overlay_webrtc_compositor",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        for publisher in (self._full_publisher, self._roi_publisher):
            if publisher is not None:
                publisher.close()

    def _metrics(self) -> tuple[CompositorMetrics, ...]:
        if self._roi_metrics is None:
            return (self._full_metrics,)
        return (self._full_metrics, self._roi_metrics)

    def _publisher(
        self,
        current: RawVideoRtspPublisher | None,
        *,
        rtsp_url: str,
        frame,
    ) -> RawVideoRtspPublisher:
        height, width = frame.shape[:2]
        if current is not None and (current.width != width or current.height != height):
            current.close()
            current = None
        if current is None:
            current = RawVideoRtspPublisher(
                rtsp_url=rtsp_url,
                width=width,
                height=height,
                fps=self.args.stream_target_fps,
                bitrate=self.args.webrtc_bitrate,
                bufsize=self.args.webrtc_bufsize,
                gop=self.args.webrtc_gop,
                encoder=self.args.webrtc_encoder,
                preset=self.args.webrtc_preset,
                ffmpeg_bin=self.args.ffmpeg_bin,
            )
        return current

    def _loop(self) -> None:
        interval_s = 1.0 / max(1.0, self.args.stream_target_fps)
        last_seq: int | None = None
        while self._running:
            loop_start = time.monotonic()
            sample = self.latest_capture.latest()
            if sample is None:
                for metrics in self._metrics():
                    metrics.stale_frames += 1
                self._write_metrics()
                time.sleep(0.05)
                continue
            capture_seq, _capture_timestamp, frame = sample
            repeated = capture_seq == last_seq
            last_seq = capture_seq
            events, selection, updated_at = self.detection_state.snapshot()
            stale = (
                updated_at <= 0
                or (time.monotonic() - updated_at) * 1000.0
                > self.args.webrtc_stale_overlay_after_ms
            )
            if self.publish_roi and selection is None:
                selection = select_smart_roi(
                    frame,
                    view_id=self.args.roi_view,
                    roi_hint_normalized=self.roi_hint,
                    model_input_size_px=(self.args.model_input_size, self.args.model_input_size),
                )
            try:
                full_frame, full_events = letterbox_frame_and_events_bgr(
                    frame,
                    events,
                    width=self.args.webrtc_full_output_width,
                    height=self.args.webrtc_full_output_height,
                )
                full_overlay = render_burned_overlay_bgr(
                    full_frame,
                    source=self.args.source,
                    view="full",
                    frame_seq=capture_seq,
                    events=full_events,
                    stale=stale,
                )
                self._full_publisher = self._publisher(
                    self._full_publisher,
                    rtsp_url=self.args.webrtc_full_rtsp_url,
                    frame=full_overlay,
                )
                self._full_publisher.write(full_overlay)

                if self.publish_roi:
                    assert selection is not None
                    roi_crop = crop_frame(frame, selection.bbox_xyxy)
                    roi_overlay = render_burned_overlay_bgr(
                        roi_crop,
                        source=self.args.source,
                        view=self.args.roi_view,
                        frame_seq=capture_seq,
                        events=events_for_crop(events, selection.bbox_xyxy),
                        stale=stale,
                    )
                    roi_overlay = letterbox_frame_bgr(
                        roi_overlay,
                        width=self.args.webrtc_roi_output_width,
                        height=self.args.webrtc_roi_output_height,
                    )
                    self._roi_publisher = self._publisher(
                        self._roi_publisher,
                        rtsp_url=self.args.webrtc_roi_rtsp_url,
                        frame=roi_overlay,
                    )
                    self._roi_publisher.write(roi_overlay)

                for metrics in self._metrics():
                    metrics.output_frames += 1
                    metrics.input_frames += 1
                    if stale:
                        metrics.stale_frames += 1
                    if repeated:
                        metrics.repeated_frames += 1
                    metrics.last_error = None
            except Exception as exc:  # noqa: BLE001 - keep live adapter running
                for metrics in self._metrics():
                    metrics.last_error = f"{exc.__class__.__name__}: {exc}"
                    if (
                        "ffmpeg" in metrics.last_error.lower()
                        or "publisher" in metrics.last_error.lower()
                    ):
                        metrics.ffmpeg_restarts += 1
                print(f"WARN: WebRTC compositor publish failed: {exc}", file=sys.stderr)
                time.sleep(0.2)
            self._write_metrics()
            elapsed = time.monotonic() - loop_start
            if elapsed < interval_s:
                time.sleep(interval_s - elapsed)

    def _write_metrics(self) -> None:
        self._full_metrics_writer.write(self._full_metrics)
        if self._roi_metrics is not None and self._roi_metrics_writer is not None:
            self._roi_metrics_writer.write(self._roi_metrics)


def _encode_jpeg(frame, *, quality: int) -> bytes:
    ok, buffer = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
    if not ok:
        raise RuntimeError("failed to encode frame as JPEG")
    return buffer.tobytes()


def _multipart_form(
    fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]
) -> tuple[bytes, str]:
    boundary = f"smartfactory-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode(),
                b"\r\n",
            ]
        )
    for name, (filename, content, content_type) in files.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'
                ).encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                content,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def _post_multipart(
    url: str,
    *,
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
    timeout: float,
) -> tuple[int, dict[str, Any] | None, str | None]:
    body, content_type = _multipart_form(fields, files)
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": content_type, "Content-Length": str(len(body))},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-configured local/LAN URL
            payload = response.read()
            parsed = json.loads(payload.decode("utf-8")) if payload else None
            return response.status, parsed, None
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        return exc.code, None, detail
    except Exception as exc:  # noqa: BLE001 - adapter should keep running across transient failures
        return 0, None, f"{exc.__class__.__name__}: {exc}"


def _run_check() -> int:
    print(f"repo_root={ROOT_DIR}")
    print(f"python={sys.executable}")
    print(f"opencv={cv2.__version__}")
    try:
        import app.smart_roi as smart_roi  # noqa: PLC0415

        print(f"smart_roi={smart_roi.__file__}")
    except Exception as exc:  # noqa: BLE001
        print(f"smart_roi=ERROR {exc}")
        return 1

    lsusb = shutil_which("lsusb")
    if lsusb:
        output = subprocess.run([lsusb], check=False, capture_output=True, text=True).stdout
        gopro_lines = [line for line in output.splitlines() if "GoPro" in line or "2672:" in line]
        print("gopro_usb=" + ("; ".join(gopro_lines) if gopro_lines else "not detected"))
    else:
        print("gopro_usb=lsusb not found")
    return 0


def shutil_which(name: str) -> str | None:
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        path = Path(directory) / name
        if path.exists() and os.access(path, os.X_OK):
            return str(path)
    return None


def _safe_filename_label(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in value).strip("_")


def _evidence_filename(args: argparse.Namespace, frame_number: int, view: str) -> str:
    label = args.evidence_label or args.task_id or args.operation.lower()
    safe_label = _safe_filename_label(label) or "evidence"
    return f"{frame_number:06d}-{safe_label}-{view}.jpg"


def run(args: argparse.Namespace) -> int:
    if args.check:
        return _run_check()

    roi_hint = parse_normalized_bbox(args.roi_hint_normalized)
    capture = None
    latest_capture: LatestFrameCapture | None = None
    detection_state = SharedDetectionState()
    webrtc_compositor: GoProWebRtcCompositor | None = None
    mediamtx_rtsp_port = os.environ.get("MEDIAMTX_RTSP_PORT", "18554")
    if not args.webrtc_full_rtsp_url:
        args.webrtc_full_rtsp_url = (
            f"rtsp://127.0.0.1:{mediamtx_rtsp_port}/{_path_id(args.source, 'full')}"
        )
    if not args.webrtc_roi_rtsp_url:
        args.webrtc_roi_rtsp_url = (
            f"rtsp://127.0.0.1:{mediamtx_rtsp_port}/{_path_id(args.source, args.roi_view)}"
        )
    if args.bufferless:
        latest_capture = LatestFrameCapture(args.input)
        if not latest_capture.is_opened():
            print(f"ERROR: cannot open input: {args.input}", file=sys.stderr)
            latest_capture.release()
            return 2
        latest_capture.start()
        if args.capture_warmup_sec > 0:
            time.sleep(args.capture_warmup_sec)
    else:
        if args.publish_webrtc:
            print(
                "ERROR: --publish-webrtc requires --bufferless latest-frame capture",
                file=sys.stderr,
            )
            return 2
        capture = _open_video_capture(args.input)
        if not capture.isOpened():
            print(f"ERROR: cannot open input: {args.input}", file=sys.stderr)
            return 2

    full_endpoint = f"{args.ai_server_url.rstrip('/')}/api/v1/vision/frame/process"
    interval_s = 1.0 / max(0.1, args.target_fps)
    processed = 0
    last_post_s = 0.0
    last_capture_seq = -1
    last_new_capture_s = time.monotonic()
    save_dir = Path(args.save_roi_dir) if args.save_roi_dir else None
    if save_dir is not None:
        save_dir.mkdir(parents=True, exist_ok=True)
    save_full_dir = Path(args.save_full_dir) if args.save_full_dir else None
    if save_full_dir is not None:
        save_full_dir.mkdir(parents=True, exist_ok=True)

    print(
        "GoPro smart ROI adapter running: "
        f"input={args.input!r}, source={args.source}, roi_view={args.roi_view}, "
        f"full_endpoint={full_endpoint}, target_fps={args.target_fps}, "
        f"bufferless={args.bufferless}, publish_webrtc={args.publish_webrtc}, "
        f"stream_target_fps={args.stream_target_fps}",
        flush=True,
    )
    if args.publish_webrtc:
        assert latest_capture is not None
        webrtc_compositor = GoProWebRtcCompositor(
            latest_capture=latest_capture,
            detection_state=detection_state,
            args=args,
            roi_hint=roi_hint,
        )
        webrtc_compositor.start()
        print(
            "GoPro WebRTC compositor publishing: "
            f"full={args.webrtc_full_rtsp_url}, "
            f"roi={args.webrtc_roi_rtsp_url if args.publish_roi_webrtc else 'disabled'}, "
            f"metrics_dir={args.webrtc_metrics_dir}",
            flush=True,
        )

    try:
        while args.max_frames <= 0 or processed < args.max_frames:
            now = time.monotonic()
            if now - last_post_s < interval_s:
                time.sleep(max(0.0, interval_s - (now - last_post_s)))

            capture_seq: int | None = None
            capture_timestamp = time.monotonic()
            if latest_capture is not None:
                sample = latest_capture.latest()
                if sample is None:
                    print("WARN: waiting for first frame", file=sys.stderr)
                    time.sleep(0.05)
                    continue
                capture_seq, capture_timestamp, frame = sample
                if capture_seq == last_capture_seq:
                    if (
                        args.read_stall_timeout_sec > 0
                        and time.monotonic() - last_new_capture_s > args.read_stall_timeout_sec
                    ):
                        print(
                            "WARN: no new capture frame before read-stall timeout",
                            file=sys.stderr,
                        )
                        if args.max_frames > 0:
                            break
                        last_new_capture_s = time.monotonic()
                    time.sleep(0.005)
                    continue
                last_capture_seq = capture_seq
                last_new_capture_s = time.monotonic()
            else:
                assert capture is not None
                ok, frame = capture.read()
                if not ok or frame is None:
                    print("WARN: failed to read frame; retrying", file=sys.stderr)
                    time.sleep(0.2)
                    continue

            last_post_s = time.monotonic()

            selection = select_smart_roi(
                frame,
                view_id=args.roi_view,
                roi_hint_normalized=roi_hint,
                model_input_size_px=(args.model_input_size, args.model_input_size),
            )
            roi_crop = crop_smart_roi(frame, selection)
            full_jpeg = _encode_jpeg(frame, quality=args.jpeg_quality)
            roi_jpeg = _encode_jpeg(roi_crop, quality=args.jpeg_quality)

            status, body, error = _post_multipart(
                full_endpoint,
                fields={"source": args.source, "force": "true", "stale": "false"},
                files={"image": ("gopro-full.jpg", full_jpeg, "image/jpeg")},
                timeout=args.timeout,
            )
            processed += 1
            summary = {
                "frame": processed,
                "full_status": status,
                "roi": selection.metadata(),
                "full_event_count": (body or {}).get("event_count"),
                "capture_age_ms": round((time.monotonic() - capture_timestamp) * 1000.0, 1),
            }
            if capture_seq is not None:
                summary["capture_seq"] = capture_seq
            if latest_capture is not None:
                summary.update(latest_capture.diagnostics())
            if error:
                summary["full_error"] = error[:240]
            events = successful_events(status, body, error)
            if events is not None:
                detection_state.update(events=events, selection=selection)
                summary["full_event_state"] = "updated"
            else:
                detection_state.update_selection(selection=selection)
                summary["full_event_state"] = "preserved_previous_until_stale"

            if save_full_dir is not None and (processed % max(1, args.save_full_every) == 0):
                target = save_full_dir / _evidence_filename(args, processed, "full")
                target.write_bytes(full_jpeg)
                summary["saved_full"] = str(target)

            if save_dir is not None and (processed % max(1, args.save_every) == 0):
                target = save_dir / _evidence_filename(args, processed, args.roi_view)
                target.write_bytes(roi_jpeg)
                summary["saved_roi"] = str(target)

            print(json.dumps(summary, ensure_ascii=False, sort_keys=True), flush=True)
    finally:
        if webrtc_compositor is not None:
            webrtc_compositor.stop()
        if latest_capture is not None:
            latest_capture.release()
        if capture is not None:
            capture.release()
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="validate local Python/USB prerequisites and exit"
    )
    parser.add_argument(
        "--input",
        default=os.environ.get("GOPRO_VIDEO_INPUT", "0"),
        help="OpenCV input: /dev/video0, udp://0.0.0.0:8554, RTSP URL, file, or camera index",
    )
    parser.add_argument(
        "--ai-server-url", default=os.environ.get("AI_SERVER_URL", "http://127.0.0.1:8100")
    )
    parser.add_argument("--source", default=os.environ.get("GOPRO_VISION_SOURCE", "global_cam_01"))
    parser.add_argument("--roi-view", default=os.environ.get("GOPRO_ROI_VIEW", "lift_roi"))
    parser.add_argument(
        "--roi-hint-normalized",
        default=os.environ.get("GOPRO_ROI_HINT_NORMALIZED", ""),
        help="optional x1,y1,x2,y2 normalized map/mount hint",
    )
    parser.add_argument(
        "--target-fps",
        type=float,
        default=float(
            os.environ.get("GOPRO_AI_MONITOR_FPS", os.environ.get("GOPRO_TARGET_FPS", "5"))
        ),
    )
    parser.add_argument(
        "--stream-target-fps",
        type=float,
        default=float(os.environ.get("GOPRO_STREAM_TARGET_FPS", "30")),
        help="WebRTC compositor output FPS; AI processing still uses --target-fps",
    )
    parser.add_argument(
        "--bufferless",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("GOPRO_BUFFERLESS", "true").lower() not in {"0", "false", "no"},
        help="capture in a background thread and process only the latest frame",
    )
    parser.add_argument(
        "--capture-warmup-sec",
        type=float,
        default=float(os.environ.get("GOPRO_CAPTURE_WARMUP_SEC", "1.0")),
        help="discard early auto-exposure/stream startup frames before processing",
    )
    parser.add_argument(
        "--read-stall-timeout-sec",
        type=float,
        default=float(os.environ.get("GOPRO_READ_STALL_TIMEOUT_SEC", "5.0")),
        help="when --bufferless and --max-frames is set, stop if no new frame arrives before this timeout",
    )
    parser.add_argument(
        "--jpeg-quality", type=int, default=int(os.environ.get("GOPRO_JPEG_QUALITY", "85"))
    )
    parser.add_argument(
        "--model-input-size",
        type=int,
        default=int(
            os.environ.get("GOPRO_AI_MONITOR_IMGSZ", os.environ.get("VISION_MODEL_IMGSZ", "640"))
        ),
    )
    parser.add_argument("--timeout", type=float, default=2.0)
    parser.add_argument("--max-frames", type=int, default=0, help="0 means run until interrupted")
    parser.add_argument("--save-roi-dir", default=os.environ.get("GOPRO_ROI_SAVE_DIR", ""))
    parser.add_argument("--save-every", type=int, default=30)
    parser.add_argument("--save-full-dir", default=os.environ.get("GOPRO_FULL_SAVE_DIR", ""))
    parser.add_argument("--save-full-every", type=int, default=30)
    parser.add_argument("--evidence-label", default=os.environ.get("GOPRO_EVIDENCE_LABEL", ""))
    parser.add_argument("--operation", choices=["PICKUP", "DROPOFF", "MONITOR"], default="MONITOR")
    parser.add_argument("--task-id")
    parser.add_argument(
        "--publish-webrtc",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("GOPRO_PUBLISH_WEBRTC", "false").lower()
        in {"1", "true", "yes", "on"},
        help="publish burned-overlay full H264 RTSP stream to MediaMTX; ROI is controlled separately",
    )
    parser.add_argument(
        "--publish-roi-webrtc",
        action=argparse.BooleanOptionalAction,
        default=os.environ.get("GOPRO_PUBLISH_ROI_WEBRTC", "true").lower()
        in {"1", "true", "yes", "on"},
        help="publish the burned-overlay ROI/crop RTSP stream when --publish-webrtc is enabled",
    )
    parser.add_argument(
        "--webrtc-full-rtsp-url", default=os.environ.get("GOPRO_WEBRTC_FULL_RTSP_URL", "")
    )
    parser.add_argument(
        "--webrtc-roi-rtsp-url", default=os.environ.get("GOPRO_WEBRTC_ROI_RTSP_URL", "")
    )
    parser.add_argument(
        "--webrtc-full-output-width",
        type=int,
        default=int(os.environ.get("GOPRO_WEBRTC_FULL_OUTPUT_WIDTH", "1280")),
        help="fixed even width for the public full WebRTC stream",
    )
    parser.add_argument(
        "--webrtc-full-output-height",
        type=int,
        default=int(os.environ.get("GOPRO_WEBRTC_FULL_OUTPUT_HEIGHT", "720")),
        help="fixed even height for the public full WebRTC stream",
    )
    parser.add_argument(
        "--webrtc-roi-output-width",
        type=int,
        default=int(os.environ.get("GOPRO_WEBRTC_ROI_OUTPUT_WIDTH", "640")),
        help="fixed even width for the public lift ROI WebRTC stream",
    )
    parser.add_argument(
        "--webrtc-roi-output-height",
        type=int,
        default=int(os.environ.get("GOPRO_WEBRTC_ROI_OUTPUT_HEIGHT", "480")),
        help="fixed even height for the public lift ROI WebRTC stream",
    )
    parser.add_argument(
        "--webrtc-metrics-dir",
        default=os.environ.get(
            "GOPRO_WEBRTC_METRICS_DIR",
            os.environ.get(
                "VISION_WEBRTC_COMPOSITOR_METRICS_DIR", ".run/vision/compositor-metrics"
            ),
        ),
    )
    parser.add_argument(
        "--webrtc-stale-overlay-after-ms",
        type=float,
        default=float(os.environ.get("GOPRO_WEBRTC_STALE_OVERLAY_AFTER_MS", "1500")),
    )
    parser.add_argument(
        "--webrtc-bitrate",
        default=os.environ.get(
            "GOPRO_WEBRTC_BITRATE", os.environ.get("WEBRTC_SIDECAR_BITRATE", "2500k")
        ),
    )
    parser.add_argument(
        "--webrtc-bufsize",
        default=os.environ.get(
            "GOPRO_WEBRTC_BUFSIZE", os.environ.get("WEBRTC_SIDECAR_BUFSIZE", "500k")
        ),
    )
    parser.add_argument(
        "--webrtc-gop",
        type=int,
        default=int(os.environ.get("GOPRO_WEBRTC_GOP", os.environ.get("WEBRTC_SIDECAR_GOP", "15"))),
    )
    parser.add_argument(
        "--webrtc-encoder",
        default=os.environ.get(
            "GOPRO_WEBRTC_ENCODER", os.environ.get("WEBRTC_SIDECAR_ENCODER", "libx264")
        ),
    )
    parser.add_argument(
        "--webrtc-preset",
        default=os.environ.get(
            "GOPRO_WEBRTC_PRESET", os.environ.get("WEBRTC_SIDECAR_X264_PRESET", "ultrafast")
        ),
    )
    parser.add_argument("--ffmpeg-bin", default=os.environ.get("FFMPEG_BIN", "ffmpeg"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return run(parse_args(argv or sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())
