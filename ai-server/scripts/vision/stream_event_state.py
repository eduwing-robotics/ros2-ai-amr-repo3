from __future__ import annotations

import math
import numbers
from typing import Any


def _valid_bbox_xyxy(value: Any) -> bool:
    if not isinstance(value, list | tuple) or len(value) != 4:
        return False
    if any(isinstance(item, bool) or not isinstance(item, numbers.Real) for item in value):
        return False
    try:
        x1, y1, x2, y2 = [float(item) for item in value]
    except (TypeError, ValueError):
        return False
    if not all(math.isfinite(coord) for coord in (x1, y1, x2, y2)):
        return False
    return x2 > x1 and y2 > y1


def _valid_overlay_polygon_xy(value: Any) -> bool:
    if not isinstance(value, list | tuple) or len(value) < 3:
        return False
    for item in value:
        if not isinstance(item, list | tuple) or len(item) != 2:
            return False
        if any(isinstance(coord, bool) or not isinstance(coord, numbers.Real) for coord in item):
            return False
        if not all(math.isfinite(float(coord)) for coord in item):
            return False
    return True


def _valid_stream_overlay_event(event: dict[str, Any]) -> bool:
    if not isinstance(event.get("class_name"), str):
        return False
    if _valid_bbox_xyxy(event.get("bbox_xyxy")):
        return True
    metadata = event.get("metadata")
    if isinstance(metadata, dict) and _valid_overlay_polygon_xy(metadata.get("overlay_polygon_xy")):
        return True
    return False


def successful_events(
    status: int | None, body: Any, error: str | None
) -> list[dict[str, Any]] | None:
    """Return valid stream-overlay event dicts only for successful AI responses.

    Invalid/missing events are treated as no fresh AI result, not as an empty
    fresh scene. Callers should preserve previous events and let stale timing
    make the degraded state visible.
    """

    if error or status is None or status < 200 or status >= 300 or not isinstance(body, dict):
        return None
    events = body.get("overlay_events")
    if not isinstance(events, list):
        events = body.get("events")
    if not isinstance(events, list):
        return None
    normalized: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            return None
        if not _valid_stream_overlay_event(event):
            return None
        normalized.append(dict(event))
    return normalized
