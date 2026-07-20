from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import cv2
import numpy as np

from .config import get_settings
from .evidence_cache import DEFAULT_VIEW_ID, normalize_view_id
from .frame_store import StoredFrame


@dataclass(frozen=True)
class OverlayRenderResult:
    source: str
    frame_seq: int
    frame_timestamp: str
    evidence_timestamp: str | None
    overlay_timestamp: str
    latency_ms: float | None
    event_count: int
    stale: bool
    image_width: int
    image_height: int
    jpeg: bytes
    view: str = DEFAULT_VIEW_ID
    content_type: str = "image/jpeg"

    def __post_init__(self) -> None:
        object.__setattr__(self, "view", normalize_view_id(self.view))

    def metadata(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "view": self.view,
            "frame_seq": self.frame_seq,
            "frame_timestamp": self.frame_timestamp,
            "evidence_timestamp": self.evidence_timestamp,
            "overlay_timestamp": self.overlay_timestamp,
            "latency_ms": self.latency_ms,
            "event_count": self.event_count,
            "stale": self.stale,
            "visual_state": "stale" if self.stale else "fresh",
            "image": {"width": self.image_width, "height": self.image_height},
            "content_type": self.content_type,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _frame_clock_label(frame_timestamp: str) -> str:
    """Return the local observation time captured with the source frame."""

    try:
        parsed = datetime.fromisoformat(frame_timestamp.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return "--:--:--"
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone().strftime("%H:%M:%S")


def _draw_label(
    image: np.ndarray,
    text: str,
    x: int,
    y: int,
    color: tuple[int, int, int],
    *,
    scale: float = 0.45,
    thickness: int = 1,
) -> None:
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = max(0.1, float(scale))
    thickness = max(1, int(thickness))
    pad_x = max(3, int(round(7 * scale)))
    pad_y = max(2, int(round(5 * scale)))
    (text_width, text_height), baseline = cv2.getTextSize(text, font, scale, thickness)
    y_top = max(0, y - text_height - baseline - (pad_y * 2))
    x_right = min(image.shape[1] - 1, x + text_width + (pad_x * 2))
    cv2.rectangle(image, (x, y_top), (x_right, y_top + text_height + baseline + (pad_y * 2)), color, -1)
    cv2.putText(
        image,
        text,
        (x + pad_x, y_top + text_height + pad_y),
        font,
        scale,
        (255, 255, 255),
        thickness,
        cv2.LINE_AA,
    )


def _bbox(event: dict[str, Any]) -> tuple[int, int, int, int] | None:
    raw = event.get("bbox_xyxy")
    if not isinstance(raw, list) or len(raw) != 4:
        return None
    try:
        x1, y1, x2, y2 = [int(round(float(value))) for value in raw]
    except (TypeError, ValueError):
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _event_color(event: dict[str, Any], *, stale: bool) -> tuple[int, int, int]:
    metadata = event.get("metadata")
    if isinstance(metadata, dict):
        raw_color = metadata.get("overlay_color_bgr")
        if isinstance(raw_color, (list, tuple)) and len(raw_color) == 3:
            try:
                b, g, r = (max(0, min(255, int(value))) for value in raw_color)
                return (b, g, r)
            except (TypeError, ValueError):
                pass
    if stale:
        return (0, 165, 255)
    if event.get("class_name") == "person":
        return (0, 0, 255)
    if event.get("class_name") == "map_roi":
        return (255, 255, 0)
    return (0, 180, 0)


def _overlay_polygon(event: dict[str, Any]) -> tuple[tuple[int, int], ...] | None:
    metadata = event.get("metadata")
    if not isinstance(metadata, dict):
        return None
    raw = metadata.get("overlay_polygon_xy")
    if not isinstance(raw, list) or len(raw) < 3:
        return None
    points: list[tuple[int, int]] = []
    for item in raw:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            return None
        try:
            x = int(round(float(item[0])))
            y = int(round(float(item[1])))
        except (TypeError, ValueError):
            return None
        points.append((x, y))
    return tuple(points)


def _overlay_label_xy(event: dict[str, Any], fallback: tuple[int, int]) -> tuple[int, int]:
    metadata = event.get("metadata")
    if not isinstance(metadata, dict):
        return fallback
    raw = metadata.get("overlay_label_xy")
    if not isinstance(raw, (list, tuple)) or len(raw) != 2:
        return fallback
    try:
        return int(round(float(raw[0]))), int(round(float(raw[1])))
    except (TypeError, ValueError):
        return fallback


def _draw_overlay_polygon(image: np.ndarray, event: dict[str, Any], *, stale: bool) -> None:
    polygon = _overlay_polygon(event)
    if polygon is None:
        return
    color = _event_color(event, stale=stale)
    points = np.asarray(polygon, dtype=np.int32).reshape((-1, 1, 2))
    cv2.polylines(image, [points], isClosed=True, color=color, thickness=3, lineType=cv2.LINE_AA)
    metadata = event.get("metadata")
    label = metadata.get("overlay_label") if isinstance(metadata, dict) else None
    if isinstance(label, str) and label:
        x, y = _overlay_label_xy(event, polygon[0])
        scale = metadata.get("overlay_label_scale", 0.45) if isinstance(metadata, dict) else 0.45
        thickness = metadata.get("overlay_label_thickness", 1) if isinstance(metadata, dict) else 1
        _draw_label(
            image,
            label,
            max(0, x),
            max(14, y),
            color,
            scale=float(scale) if isinstance(scale, int | float) else 0.45,
            thickness=int(thickness) if isinstance(thickness, int | float) else 1,
        )


def _is_visual_overlay_event(
    event: dict[str, Any],
    *,
    min_confidence: float,
) -> bool:
    # Keep model fallback/unknown candidates available in event payloads for
    # diagnostics, but do not clutter the live operator overlay with ambiguous
    # boxes.  Main-facing hazard/evidence read models still decide from their
    # own compact policies, not from this visual filter.
    if event.get("class_name") == "unknown":
        return False
    confidence = event.get("confidence")
    if isinstance(confidence, int | float):
        return float(confidence) >= min_confidence
    return True


def _short_marker_id(marker_id: Any) -> str | None:
    raw = str(marker_id or "").strip()
    if not raw:
        return None
    suffix = raw.rsplit("_", 1)[-1]
    if suffix.isdigit():
        return f"A{suffix}"
    return raw


def _event_label(event: dict[str, Any]) -> str:
    class_name = str(event.get("class_name") or "evidence")
    label_parts: list[str] = []
    if class_name == "aruco_marker":
        label_parts.append(_short_marker_id(event.get("marker_id")) or "A?")
    else:
        label_parts.append(class_name)
        if event.get("marker_id"):
            label_parts.append(str(event["marker_id"]))
    confidence = event.get("confidence")
    if isinstance(confidence, int | float):
        label_parts.append(f"{confidence:.2f}")
    return " ".join(label_parts)


def render_overlay(
    frame: StoredFrame,
    *,
    events: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    stale: bool = False,
    view: str | None = None,
    min_confidence: float | None = None,
) -> OverlayRenderResult:
    """Render visual evidence overlay for the latest frame.

    Overlay is non-authoritative: it shows detection evidence only and never
    implies Main/WMS task success.
    """

    image = render_overlay_bgr(
        frame,
        events=events,
        stale=stale,
        view=view,
        min_confidence=min_confidence,
    )

    ok, buffer = cv2.imencode(".jpg", image)
    if not ok:
        raise ValueError("failed to encode overlay JPEG")

    evidence_timestamps = [
        event.get("timestamp") for event in events if isinstance(event.get("timestamp"), str)
    ]
    latencies = [
        event.get("metadata", {}).get("latency_ms")
        for event in events
        if isinstance(event.get("metadata"), dict)
    ]
    numeric_latencies = [float(value) for value in latencies if isinstance(value, int | float)]
    return OverlayRenderResult(
        source=frame.source,
        view=normalize_view_id(view),
        frame_seq=frame.frame_seq,
        frame_timestamp=frame.timestamp,
        evidence_timestamp=max(evidence_timestamps) if evidence_timestamps else None,
        overlay_timestamp=_now_iso(),
        latency_ms=max(numeric_latencies) if numeric_latencies else None,
        event_count=len(events),
        stale=stale,
        image_width=frame.image_width,
        image_height=frame.image_height,
        jpeg=buffer.tobytes(),
    )


def render_overlay_bgr(
    frame: StoredFrame,
    *,
    events: list[dict[str, Any]] | tuple[dict[str, Any], ...] = (),
    stale: bool = False,
    view: str | None = None,
    min_confidence: float | None = None,
) -> np.ndarray:
    """Render visual evidence overlay and return BGR pixels without JPEG encoding."""

    _ = normalize_view_id(view)

    if frame.decoded_bgr is None:
        image_array = np.frombuffer(frame.encoded, dtype=np.uint8)
        image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
        if image is None:
            raise ValueError("stored frame is not decodable")
    else:
        image = frame.decoded_bgr.copy()

    confidence_floor = (
        get_settings().vision_overlay_min_confidence
        if min_confidence is None
        else max(0.0, min(1.0, float(min_confidence)))
    )
    visual_events = [
        event
        for event in events
        if _is_visual_overlay_event(event, min_confidence=confidence_floor)
    ]

    for event in visual_events:
        _draw_overlay_polygon(image, event, stale=stale)

    for event in visual_events:
        bbox = _bbox(event)
        if bbox is None:
            continue
        color = _event_color(event, stale=stale)
        x1, y1, x2, y2 = bbox
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        _draw_label(image, _event_label(event), max(0, x1), max(14, y1), color)

    if stale:
        # Make stale evidence visually unmistakable for GUI/debug QA.  The full-width
        # amber header is intentionally stronger than bbox color alone so operators
        # do not confuse old visual evidence with current WMS/task success.
        cv2.rectangle(
            image, (0, 0), (image.shape[1] - 1, min(25, image.shape[0] - 1)), (0, 165, 255), -1
        )
        warning_text = "STALE FRAME - DEBUG ONLY"
        if image.shape[1] < 220:
            warning_text = "STALE FRAME"
        cv2.putText(
            image,
            warning_text,
            (6, min(18, image.shape[0] - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 0, 0),
            1,
            cv2.LINE_AA,
        )

    clock_label = _frame_clock_label(frame.timestamp)
    valid_event_count = len(visual_events)
    if image.shape[1] < 240:
        short_source = frame.source.replace("_picam", "").replace("global_cam_", "gcam")
        banner = f"{short_source} last={clock_label} valid={valid_event_count}"
    else:
        banner = f"{frame.source} last={clock_label} valid={valid_event_count}"
    _draw_label(image, banner, 4, image.shape[0] - 6, (40, 40, 40))

    return image
