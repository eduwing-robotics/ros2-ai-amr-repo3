#!/usr/bin/env python3
"""Shared burned-overlay compositor helpers for SmartFactory Vision WebRTC.

This module is intentionally Vision-PC only.  Robot Raspberry Pi devices keep
running their existing camera bringup; the Vision PC owns overlay composition,
H264 encoding, MediaMTX publishing, and heartbeat metrics.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import cv2
import numpy as np

ROOT_DIR = Path(__file__).resolve().parents[2]
AI_SERVER_DIR = ROOT_DIR

if str(AI_SERVER_DIR) not in sys.path:
    sys.path.insert(0, str(AI_SERVER_DIR))

from app.frame_store import StoredFrame  # noqa: E402
from app.overlay import render_overlay_bgr  # noqa: E402


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def clamp_crop(frame: np.ndarray, bbox_xyxy: Iterable[int | float]) -> tuple[int, int, int, int]:
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = [int(round(float(value))) for value in bbox_xyxy]
    x1 = max(0, min(width - 1, x1))
    y1 = max(0, min(height - 1, y1))
    x2 = max(x1 + 1, min(width, x2))
    y2 = max(y1 + 1, min(height, y2))
    return x1, y1, x2, y2


def crop_frame(frame: np.ndarray, bbox_xyxy: Iterable[int | float]) -> np.ndarray:
    x1, y1, x2, y2 = clamp_crop(frame, bbox_xyxy)
    return frame[y1:y2, x1:x2].copy()


def letterbox_frame_bgr(
    frame_bgr: np.ndarray,
    *,
    width: int,
    height: int,
    fill: tuple[int, int, int] = (0, 0, 0),
) -> np.ndarray:
    """Resize BGR pixels into a fixed even canvas without aspect distortion.

    H264/yuv420p encoders require even dimensions, and RTSP/WebRTC readers are
    much more stable when a path keeps one constant video size.  ROI crops can
    change by a few pixels frame-to-frame, so public WebRTC crop streams should
    publish a fixed letterboxed canvas while high-resolution evidence capture
    keeps using the original crop in the separate evidence API path.
    """

    target_width = max(2, int(width) - int(width) % 2)
    target_height = max(2, int(height) - int(height) % 2)
    src_height, src_width = frame_bgr.shape[:2]
    if src_width <= 0 or src_height <= 0:
        raise ValueError("cannot letterbox an empty frame")
    scale = min(target_width / src_width, target_height / src_height)
    resized_width = max(2, int(round(src_width * scale)))
    resized_height = max(2, int(round(src_height * scale)))
    resized_width -= resized_width % 2
    resized_height -= resized_height % 2
    resized_width = max(2, min(target_width, resized_width))
    resized_height = max(2, min(target_height, resized_height))
    resized = cv2.resize(frame_bgr, (resized_width, resized_height), interpolation=cv2.INTER_AREA)
    canvas = np.full((target_height, target_width, 3), fill, dtype=frame_bgr.dtype)
    x_offset = (target_width - resized_width) // 2
    y_offset = (target_height - resized_height) // 2
    canvas[
        y_offset : y_offset + resized_height,
        x_offset : x_offset + resized_width,
    ] = resized
    return canvas


def letterbox_geometry(
    *,
    src_width: int,
    src_height: int,
    width: int,
    height: int,
) -> dict[str, float | int]:
    """Return the scale/offset used to fit a source frame into an even canvas."""

    target_width = max(2, int(width) - int(width) % 2)
    target_height = max(2, int(height) - int(height) % 2)
    if src_width <= 0 or src_height <= 0:
        raise ValueError("cannot letterbox empty geometry")
    scale = min(target_width / src_width, target_height / src_height)
    resized_width = max(2, int(round(src_width * scale)))
    resized_height = max(2, int(round(src_height * scale)))
    resized_width -= resized_width % 2
    resized_height -= resized_height % 2
    resized_width = max(2, min(target_width, resized_width))
    resized_height = max(2, min(target_height, resized_height))
    x_offset = (target_width - resized_width) // 2
    y_offset = (target_height - resized_height) // 2
    x_scale = resized_width / src_width
    y_scale = resized_height / src_height
    return {
        "target_width": target_width,
        "target_height": target_height,
        "resized_width": resized_width,
        "resized_height": resized_height,
        "x_offset": x_offset,
        "y_offset": y_offset,
        "x_scale": x_scale,
        "y_scale": y_scale,
    }


def letterbox_frame_and_events_bgr(
    frame_bgr: np.ndarray,
    events: Iterable[dict[str, Any]],
    *,
    width: int,
    height: int,
    fill: tuple[int, int, int] = (0, 0, 0),
) -> tuple[np.ndarray, list[dict[str, Any]]]:
    """Letterbox a frame and remap bbox events into the output canvas."""

    src_height, src_width = frame_bgr.shape[:2]
    geometry = letterbox_geometry(
        src_width=src_width,
        src_height=src_height,
        width=width,
        height=height,
    )
    target_width = int(geometry["target_width"])
    target_height = int(geometry["target_height"])
    resized_width = int(geometry["resized_width"])
    resized_height = int(geometry["resized_height"])
    x_offset = int(geometry["x_offset"])
    y_offset = int(geometry["y_offset"])
    x_scale = float(geometry["x_scale"])
    y_scale = float(geometry["y_scale"])
    resized = cv2.resize(frame_bgr, (resized_width, resized_height), interpolation=cv2.INTER_AREA)
    canvas = np.full((target_height, target_width, 3), fill, dtype=frame_bgr.dtype)
    canvas[y_offset : y_offset + resized_height, x_offset : x_offset + resized_width] = resized

    def map_point(x: float, y: float) -> list[int]:
        nx = int(round(max(0.0, min(float(src_width), x)) * x_scale + x_offset))
        ny = int(round(max(0.0, min(float(src_height), y)) * y_scale + y_offset))
        nx = max(x_offset, min(x_offset + resized_width, nx))
        ny = max(y_offset, min(y_offset + resized_height, ny))
        return [nx, ny]

    def translated_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
        copied_metadata: dict[str, Any] = {
            **metadata,
            "letterbox_translated": True,
            "letterbox_source_size_px": {"width": src_width, "height": src_height},
            "letterbox_output_size_px": {"width": target_width, "height": target_height},
            "letterbox_scale": {"x": x_scale, "y": y_scale},
            "letterbox_offset_px": {"x": x_offset, "y": y_offset},
        }
        raw_polygon = metadata.get("overlay_polygon_xy")
        if isinstance(raw_polygon, list) and len(raw_polygon) >= 3:
            polygon: list[list[int]] = []
            for item in raw_polygon:
                if not isinstance(item, list | tuple) or len(item) != 2:
                    polygon = []
                    break
                try:
                    polygon.append(map_point(float(item[0]), float(item[1])))
                except (TypeError, ValueError):
                    polygon = []
                    break
            if polygon:
                copied_metadata["overlay_polygon_xy"] = polygon
        raw_label_xy = metadata.get("overlay_label_xy")
        if isinstance(raw_label_xy, list | tuple) and len(raw_label_xy) == 2:
            try:
                copied_metadata["overlay_label_xy"] = map_point(
                    float(raw_label_xy[0]), float(raw_label_xy[1])
                )
            except (TypeError, ValueError):
                pass
        return copied_metadata

    mapped: list[dict[str, Any]] = []
    for event in events:
        metadata = event.get("metadata")
        metadata = metadata if isinstance(metadata, dict) else {}
        copied = dict(event)
        copied["metadata"] = translated_metadata(metadata)

        raw = event.get("bbox_xyxy")
        raw_polygon = metadata.get("overlay_polygon_xy")
        has_polygon = isinstance(raw_polygon, list) and len(raw_polygon) >= 3
        if not isinstance(raw, list | tuple) or len(raw) != 4:
            if has_polygon:
                mapped.append(copied)
            continue
        try:
            x1, y1, x2, y2 = [float(value) for value in raw]
        except (TypeError, ValueError):
            if has_polygon:
                mapped.append(copied)
            continue
        x1 = max(0.0, min(float(src_width), x1))
        y1 = max(0.0, min(float(src_height), y1))
        x2 = max(0.0, min(float(src_width), x2))
        y2 = max(0.0, min(float(src_height), y2))
        if x2 <= x1 or y2 <= y1:
            if has_polygon:
                mapped.append(copied)
            continue
        active_x1 = x_offset
        active_y1 = y_offset
        active_x2 = x_offset + resized_width
        active_y2 = y_offset + resized_height
        nx1, ny1 = map_point(x1, y1)
        nx2, ny2 = map_point(x2, y2)
        nx1 = max(active_x1, min(active_x2, nx1))
        ny1 = max(active_y1, min(active_y2, ny1))
        nx2 = max(active_x1, min(active_x2, nx2))
        ny2 = max(active_y1, min(active_y2, ny2))
        if nx2 <= nx1 or ny2 <= ny1:
            if has_polygon:
                mapped.append(copied)
            continue
        copied["bbox_xyxy"] = [nx1, ny1, nx2, ny2]
        mapped.append(copied)
    return canvas, mapped


def events_for_crop(
    events: Iterable[dict[str, Any]], bbox_xyxy: Iterable[int | float]
) -> list[dict[str, Any]]:
    """Translate full-frame events into crop coordinates.

    Events that do not intersect the crop are dropped.  The returned payloads
    preserve all original fields except for `bbox_xyxy`, which is clipped and
    translated into crop-local pixel coordinates.
    """

    x1, y1, x2, y2 = [int(round(float(value))) for value in bbox_xyxy]
    crop_width = max(1, x2 - x1)
    crop_height = max(1, y2 - y1)
    translated: list[dict[str, Any]] = []
    for event in events:
        raw = event.get("bbox_xyxy")
        if not isinstance(raw, list | tuple) or len(raw) != 4:
            continue
        try:
            ex1, ey1, ex2, ey2 = [int(round(float(value))) for value in raw]
        except (TypeError, ValueError):
            continue
        ix1 = max(ex1, x1)
        iy1 = max(ey1, y1)
        ix2 = min(ex2, x2)
        iy2 = min(ey2, y2)
        if ix2 <= ix1 or iy2 <= iy1:
            continue
        copied = dict(event)
        copied["bbox_xyxy"] = [
            max(0, ix1 - x1),
            max(0, iy1 - y1),
            min(crop_width, ix2 - x1),
            min(crop_height, iy2 - y1),
        ]
        copied.setdefault("metadata", {})
        if isinstance(copied["metadata"], dict):
            copied["metadata"] = {
                **copied["metadata"],
                "crop_translated": True,
                "crop_bbox_xyxy": [x1, y1, x2, y2],
            }
        translated.append(copied)
    return translated


def render_burned_overlay_bgr(
    frame_bgr: np.ndarray,
    *,
    source: str,
    view: str,
    frame_seq: int,
    events: Iterable[dict[str, Any]],
    stale: bool = False,
) -> np.ndarray:
    """Return BGR pixels with AI overlay burned into the frame."""

    height, width = frame_bgr.shape[:2]
    stored = StoredFrame(
        source=source,
        frame_seq=frame_seq,
        timestamp=now_iso(),
        image_width=int(width),
        image_height=int(height),
        encoded=b"",
        content_type="image/bgr",
        decoded_bgr=frame_bgr,
    )
    return render_overlay_bgr(stored, events=list(events), stale=stale, view=view)


@dataclass
class CompositorMetrics:
    source: str
    view: str
    path_id: str
    target_fps: float
    ai_fps: float
    output_frames: int = 0
    input_frames: int = 0
    stale_frames: int = 0
    repeated_frames: int = 0
    dropped_frames: int = 0
    ffmpeg_restarts: int = 0
    last_error: str | None = None
    started_at_epoch_s: float = field(default_factory=time.time)
    updated_at_epoch_s: float = field(default_factory=time.time)

    def as_dict(self) -> dict[str, Any]:
        now = time.time()
        elapsed = max(0.001, now - self.started_at_epoch_s)
        return {
            "schema_version": "smartfactory-vision-compositor-metrics.v1",
            "status": "running" if self.last_error is None else "degraded",
            "source": self.source,
            "view": self.view,
            "path_id": self.path_id,
            "target_fps": self.target_fps,
            "ai_fps": self.ai_fps,
            "output_frames": self.output_frames,
            "input_frames": self.input_frames,
            "output_fps_estimate": round(self.output_frames / elapsed, 3),
            "stale_frames": self.stale_frames,
            "repeated_frames": self.repeated_frames,
            "dropped_frames": self.dropped_frames,
            "ffmpeg_restarts": self.ffmpeg_restarts,
            "last_error": self.last_error,
            "started_at_epoch_s": self.started_at_epoch_s,
            "updated_at_epoch_s": self.updated_at_epoch_s,
            "updated_at": datetime.fromtimestamp(
                self.updated_at_epoch_s, tz=timezone.utc
            ).isoformat(),
        }


class MetricsWriter:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, metrics: CompositorMetrics) -> None:
        metrics.updated_at_epoch_s = time.time()
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(
            json.dumps(metrics.as_dict(), ensure_ascii=False, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        tmp.replace(self.path)


class RawVideoRtspPublisher:
    """Pipe fixed-size BGR frames to ffmpeg and publish RTSP/H264."""

    def __init__(
        self,
        *,
        rtsp_url: str,
        width: int,
        height: int,
        fps: float,
        bitrate: str = "2500k",
        bufsize: str = "500k",
        gop: int = 15,
        encoder: str = "libx264",
        preset: str = "ultrafast",
        ffmpeg_bin: str = "ffmpeg",
    ):
        self.rtsp_url = rtsp_url
        self.width = int(width)
        self.height = int(height)
        self.fps = float(fps)
        self.bitrate = bitrate
        self.bufsize = bufsize
        self.gop = int(gop)
        self.encoder = encoder
        self.preset = preset
        self.ffmpeg_bin = ffmpeg_bin
        self.process: subprocess.Popen[bytes] | None = None

    def command(self) -> list[str]:
        encoder_args = []
        if self.encoder.startswith("libx264"):
            encoder_args = [
                "-preset",
                self.preset,
                "-tune",
                "zerolatency",
                "-x264-params",
                f"keyint={self.gop}:min-keyint={self.gop}:scenecut=0",
            ]
        return [
            self.ffmpeg_bin,
            "-hide_banner",
            "-loglevel",
            "warning",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{self.width}x{self.height}",
            "-r",
            str(self.fps),
            "-i",
            "pipe:0",
            "-an",
            "-c:v",
            self.encoder,
            *encoder_args,
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(self.fps),
            "-g",
            str(self.gop),
            "-bf",
            "0",
            "-b:v",
            self.bitrate,
            "-maxrate",
            self.bitrate,
            "-bufsize",
            self.bufsize,
            "-muxdelay",
            "0",
            "-muxpreload",
            "0",
            "-flush_packets",
            "1",
            "-f",
            "rtsp",
            "-rtsp_transport",
            "tcp",
            self.rtsp_url,
        ]

    def start(self) -> None:
        if self.process is not None and self.process.poll() is None:
            return
        self.process = subprocess.Popen(  # noqa: S603 - command is locally configured operator tooling
            self.command(),
            stdin=subprocess.PIPE,
        )

    def write(self, frame_bgr: np.ndarray) -> None:
        if frame_bgr.shape[0] != self.height or frame_bgr.shape[1] != self.width:
            raise ValueError(
                f"publisher frame size changed: got {frame_bgr.shape[1]}x{frame_bgr.shape[0]}, "
                f"expected {self.width}x{self.height}"
            )
        if self.process is None or self.process.poll() is not None:
            self.start()
        assert self.process is not None and self.process.stdin is not None
        self.process.stdin.write(frame_bgr.tobytes())
        self.process.stdin.flush()

    def close(self) -> None:
        proc = self.process
        if proc is None:
            return
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
        self.process = None
