"""Adapt AI Server PiCam ArUco events to the Nav docking observation contract."""

from __future__ import annotations

import json
import math
from datetime import datetime
from typing import Any, Mapping
from urllib.parse import urlencode
from urllib.request import Request, urlopen


_MARKER_PREFIX = "ARUCO_4X4_50_"
_MAX_RESPONSE_BYTES = 1_000_000


def _observed_at_epoch(value: Any) -> float | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    epoch = parsed.timestamp()
    return epoch if math.isfinite(epoch) and epoch > 0.0 else None


def _marker_number(value: Any) -> int | None:
    text = str(value or "").strip()
    if text.startswith(_MARKER_PREFIX):
        text = text[len(_MARKER_PREFIX) :]
    try:
        marker_id = int(text)
    except (TypeError, ValueError):
        return None
    return marker_id if 0 <= marker_id <= 49 else None


def _finite_bbox(value: Any) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 4:
        return None
    try:
        x1, y1, x2, y2 = (float(item) for item in value)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(item) for item in (x1, y1, x2, y2)):
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _detection_from_event(event: Mapping[str, Any]) -> tuple[float, dict[str, Any]] | None:
    observed_at = _observed_at_epoch(event.get("timestamp"))
    marker_id = _marker_number(event.get("marker_id"))
    bbox = _finite_bbox(event.get("bbox_xyxy"))
    metadata = event.get("metadata")
    if observed_at is None or marker_id is None or bbox is None or not isinstance(metadata, Mapping):
        return None
    try:
        image_width = int(metadata.get("image_width"))
        image_height = int(metadata.get("image_height"))
    except (TypeError, ValueError):
        return None
    if image_width <= 0 or image_height <= 0:
        return None

    x1, y1, x2, y2 = bbox
    center_x = (x1 + x2) / 2.0
    center_y = (y1 + y2) / 2.0
    width_px = x2 - x1
    height_px = y2 - y1
    detection: dict[str, Any] = {
        "marker_id": marker_id,
        "center_px": [center_x, center_y],
        "center_error_px": center_x - image_width / 2.0,
        "center_error_norm": (center_x - image_width / 2.0) / max(1.0, image_width / 2.0),
        "marker_width_px": width_px,
        "marker_height_px": height_px,
        "area_px": width_px * height_px,
        "image_width": image_width,
        "image_height": image_height,
        "corners_px": [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
        "confidence": event.get("confidence"),
        "event_id": event.get("event_id"),
        "frame_sequence": metadata.get("frame_seq"),
        "source": event.get("source"),
        "frame_id": event.get("frame_id"),
        "transport": "vision_http",
    }
    pose = event.get("pose_estimate")
    if isinstance(pose, Mapping):
        mappings = {
            "x": "lateral_offset_m",
            "y": "forward_distance_m",
            "yaw": "marker_yaw_rad",
        }
        for source_key, target_key in mappings.items():
            try:
                number = float(pose[source_key])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(number):
                detection[target_key] = number
        if "forward_distance_m" in detection:
            detection["estimated_distance_m"] = detection["forward_distance_m"]
    return observed_at, detection


def detector_payload_from_vision(
    response: Mapping[str, Any], *, expected_source: str
) -> dict[str, Any] | None:
    """Return the newest valid event per marker in the existing Nav JSON shape."""
    events = response.get("events")
    if not isinstance(events, list):
        return None
    newest: dict[int, tuple[float, dict[str, Any]]] = {}
    for event in events:
        if not isinstance(event, Mapping):
            continue
        if event.get("source") != expected_source:
            continue
        if event.get("event_kind") != "CONFIRMED" or event.get("class_name") != "aruco_marker":
            continue
        converted = _detection_from_event(event)
        if converted is None:
            continue
        observed_at, detection = converted
        marker_id = int(detection["marker_id"])
        prior = newest.get(marker_id)
        if prior is None or observed_at > prior[0]:
            newest[marker_id] = (observed_at, detection)
    if not newest:
        return None

    latest_stamp = max(item[0] for item in newest.values())
    sec = int(latest_stamp)
    nanosec = int(round((latest_stamp - sec) * 1e9))
    if nanosec >= 1_000_000_000:
        sec += 1
        nanosec = 0
    detections = [
        detection
        for _, detection in sorted(
            newest.values(), key=lambda item: item[0], reverse=True
        )
    ]
    return {
        "source_header_stamp": {"sec": sec, "nanosec": nanosec},
        "stamp": {"sec": sec, "nanosec": nanosec},
        "source": expected_source,
        "transport": "vision_http",
        "detections": detections,
    }


def fetch_detector_payload(
    *,
    api_base_url: str,
    source: str,
    limit: int = 20,
    timeout_sec: float = 0.3,
) -> dict[str, Any] | None:
    """Fetch only compact detection metadata; no frame or overlay bytes are transferred."""
    query = urlencode({"source": source, "limit": int(limit)})
    url = f"{api_base_url.rstrip('/')}/api/v1/detections/latest?{query}"
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=float(timeout_sec)) as response:
        raw = response.read(_MAX_RESPONSE_BYTES)
    document = json.loads(raw)
    if not isinstance(document, Mapping):
        return None
    return detector_payload_from_vision(document, expected_source=source)
