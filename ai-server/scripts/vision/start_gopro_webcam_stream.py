#!/usr/bin/env python3
"""Start a GoPro HERO USB webcam-mode transport without GUI dependencies.

This is the server/laptop-friendly replacement for OpenGoPro's GUI demo:
it opens the camera over USB using WiredGoPro, starts OpenGoPro's "webcam"
transport mode, prints the OpenCV input URL, optionally validates one frame
read, and keeps the stream alive until interrupted.

Important naming boundary: "webcam" here is the GoPro/OpenGoPro transport
mode name only. In SmartFactory contracts this device remains the global camera
source `global_cam_01`, not a generic webcam source.
"""

from __future__ import annotations

import argparse
import asyncio
import signal
import sys
import time
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
AI_SERVER_DIR = ROOT_DIR
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(AI_SERVER_DIR))

try:
    import cv2
    from open_gopro import WiredGoPro
    from open_gopro.models.streaming import (
        StreamType,
        WebcamFOV,
        WebcamProtocol,
        WebcamResolution,
        WebcamStreamOptions,
    )
    from returns.pipeline import is_successful
except ImportError as exc:  # pragma: no cover - environment diagnostic
    raise SystemExit(
        "Missing GoPro stream dependencies. Run:\n"
        "  .venv/bin/python -m pip install -r requirements-gopro.txt"
    ) from exc

from app.smart_roi import parse_normalized_bbox  # noqa: E402  # validates PYTHONPATH/venv seam
from scripts.vision.run_gopro_smart_roi_adapter import _normalize_video_capture_url  # noqa: E402


def _protocol(value: str) -> WebcamProtocol:
    normalized = value.strip().upper()
    if normalized == "TS":
        return WebcamProtocol.TS
    if normalized == "RTSP":
        return WebcamProtocol.RTSP
    raise argparse.ArgumentTypeError("protocol must be TS or RTSP")


def _resolution(value: str) -> WebcamResolution:
    normalized = value.strip().lower().replace("p", "")
    mapping = {
        "1080": WebcamResolution.RES_1080,
        "720": WebcamResolution.RES_720,
        "480": WebcamResolution.RES_480,
    }
    try:
        return mapping[normalized]
    except KeyError as exc:
        raise argparse.ArgumentTypeError("resolution must be 1080, 720, or 480") from exc


def _fov(value: str) -> WebcamFOV:
    normalized = value.strip().upper()
    try:
        return getattr(WebcamFOV, normalized)
    except AttributeError as exc:
        choices = ", ".join(item.name.lower() for item in WebcamFOV)
        raise argparse.ArgumentTypeError(f"fov must be one of: {choices}") from exc


def _test_read(url: str, *, timeout_s: float) -> tuple[bool, tuple[int, int, int] | None]:
    capture_url = _normalize_video_capture_url(url)
    cap = cv2.VideoCapture(capture_url, cv2.CAP_FFMPEG)
    try:
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            ok, frame = cap.read()
            if ok and frame is not None:
                return True, tuple(int(value) for value in frame.shape)
            time.sleep(0.05)
        return False, None
    finally:
        cap.release()


async def run(args: argparse.Namespace) -> int:
    # Keep this import path exercised; it catches accidental execution from the
    # wrong venv before the camera is opened.
    _ = parse_normalized_bbox(args.roi_hint_normalized) if args.roi_hint_normalized else None

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop_event.set)
        except NotImplementedError:  # pragma: no cover - non-Unix fallback
            pass

    async with WiredGoPro(args.identifier or None) as gopro:
        print(f"gopro_opened identifier={gopro.identifier} ip={gopro.ip_address}", flush=True)
        options = WebcamStreamOptions(
            resolution=args.resolution,
            fov=args.fov,
            port=args.port,
            protocol=args.protocol,
        )
        result = await gopro.streaming.start_stream(
            stream_type=StreamType.WEBCAM,
            options=options,
        )
        if not is_successful(result):
            print(f"ERROR: failed to start webcam stream: {result.failure()}", file=sys.stderr)
            return 1
        raw_url = gopro.streaming.url or f"udp://0.0.0.0:{args.port}"
        opencv_url = _normalize_video_capture_url(raw_url)
        print(f"gopro_stream_url={raw_url}", flush=True)
        print(f"opencv_input={opencv_url}", flush=True)

        if args.test_read:
            ok, shape = _test_read(raw_url, timeout_s=args.test_timeout)
            print(f"opencv_test_read={'ok' if ok else 'failed'} shape={shape}", flush=True)
            if not ok and args.exit_after_test:
                await gopro.streaming.stop_active_stream()
                return 2
        if args.exit_after_test:
            await gopro.streaming.stop_active_stream()
            print("gopro_stream_stopped", flush=True)
            return 0

        print("stream_alive=true; press Ctrl-C to stop", flush=True)
        await stop_event.wait()
        await gopro.streaming.stop_active_stream()
        print("gopro_stream_stopped", flush=True)
    return 0


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--identifier",
        default="",
        help="optional GoPro serial/identifier; default auto-discovers wired camera",
    )
    parser.add_argument("--protocol", type=_protocol, default=WebcamProtocol.TS)
    parser.add_argument("--resolution", type=_resolution, default=WebcamResolution.RES_1080)
    parser.add_argument("--fov", type=_fov, default=WebcamFOV.WIDE)
    parser.add_argument("--port", type=int, default=8554)
    parser.add_argument(
        "--test-read", action="store_true", help="open the stream with OpenCV and read one frame"
    )
    parser.add_argument(
        "--exit-after-test",
        action="store_true",
        help="stop the stream after --test-read or after printing URLs",
    )
    parser.add_argument("--test-timeout", type=float, default=10.0)
    parser.add_argument(
        "--roi-hint-normalized", default="", help="optional validation-only x1,y1,x2,y2 hint"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(run(parse_args(argv or sys.argv[1:])))


if __name__ == "__main__":
    raise SystemExit(main())
