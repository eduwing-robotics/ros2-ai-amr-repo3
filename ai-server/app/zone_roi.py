from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

Point = tuple[float, float]


@dataclass(frozen=True)
class ZoneRoi:
    zone_id: str
    label: str
    role: str
    natural_item_location: bool
    polygon_normalized: tuple[Point, ...]
    reference_markers: tuple[int, ...] = ()
    overlay_label_anchor_normalized: Point | None = None
    notes: str = ""


@dataclass(frozen=True)
class ZoneRoiConfig:
    enabled: bool
    source: str
    coordinate_space: str
    zones: tuple[ZoneRoi, ...]
    location_aliases: dict[str, str] | None = None
    status: str = ""


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _require_mapping(value: Any, *, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{path} must be an object")
    return value


def _require_string(value: Any, *, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path} must be a non-empty string")
    return value.strip()


def _optional_string(value: Any, *, default: str = "") -> str:
    if value is None:
        return default
    if not isinstance(value, str):
        return default
    return value.strip() or default


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return False


def _parse_reference_markers(value: Any, *, path: str) -> tuple[int, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ValueError(f"{path} must be a list")
    markers: list[int] = []
    for index, item in enumerate(value):
        if isinstance(item, bool) or not isinstance(item, int):
            raise ValueError(f"{path}[{index}] must be an integer marker id")
        if item < 0 or item > 49:
            raise ValueError(f"{path}[{index}] must be in 0..49")
        markers.append(item)
    return tuple(markers)


def _parse_normalized_point(value: Any, *, path: str) -> Point:
    if not isinstance(value, list | tuple) or len(value) != 2:
        raise ValueError(f"{path} must be [x, y]")
    x_raw, y_raw = value
    if isinstance(x_raw, bool) or isinstance(y_raw, bool):
        raise ValueError(f"{path} coordinates must be numeric")
    try:
        x = float(x_raw)
        y = float(y_raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{path} coordinates must be numeric") from exc
    if not math.isfinite(x) or not math.isfinite(y) or x < 0.0 or x > 1.0 or y < 0.0 or y > 1.0:
        raise ValueError(f"{path} coordinates must be finite numbers in [0, 1]")
    return (x, y)


def _parse_normalized_polygon(value: Any, *, path: str) -> tuple[Point, ...]:
    if not isinstance(value, list) or len(value) < 3:
        raise ValueError(f"{path} must be a list of at least 3 normalized x/y points")
    return tuple(
        _parse_normalized_point(item, path=f"{path}[{index}]")
        for index, item in enumerate(value)
    )


def _parse_optional_normalized_point(value: Any, *, path: str) -> Point | None:
    if value is None:
        return None
    return _parse_normalized_point(value, path=path)


def _parse_location_aliases(value: Any, *, path: str) -> dict[str, str]:
    if value is None:
        return {}
    aliases = _require_mapping(value, path=path)
    parsed: dict[str, str] = {}
    for alias, zone_id in aliases.items():
        if not isinstance(alias, str) or not alias.strip():
            raise ValueError(f"{path} keys must be non-empty strings")
        parsed[alias.strip()] = _require_string(zone_id, path=f"{path}.{alias}")
    return parsed


def _zone_label(zone_id: str, raw_label: str) -> str:
    if raw_label and raw_label.isascii():
        return raw_label
    prefixes = {
        "inbound": "inbound",
        "outbound": "outbound",
        "charging": "charging",
        "storage_upper": "storage 1",
        "storage_lower": "storage 2",
    }
    for prefix, label in prefixes.items():
        if zone_id.startswith(prefix):
            return label
    return zone_id.replace("_static_item_zone", "").replace("_reference_zone", "").replace("_", " ")


def load_zone_roi_config(path: str | Path, *, enabled: bool = True) -> ZoneRoiConfig:
    config_path = Path(path)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    data = _require_mapping(raw, path=str(config_path))
    source = _require_string(data.get("source"), path="source")
    coordinate_space = _optional_string(
        data.get("coordinate_space"), default="normalized_full_frame_xy"
    )
    if coordinate_space != "normalized_full_frame_xy":
        raise ValueError(f"unsupported zone ROI coordinate_space: {coordinate_space}")
    zones_raw = data.get("zones")
    if not isinstance(zones_raw, list):
        raise ValueError("zones must be a list")
    zones: list[ZoneRoi] = []
    for index, zone_raw in enumerate(zones_raw):
        zone = _require_mapping(zone_raw, path=f"zones[{index}]")
        zone_id = _require_string(zone.get("zone_id"), path=f"zones[{index}].zone_id")
        raw_label = _optional_string(
            zone.get("label"), default=_optional_string(zone.get("label_ko"))
        )
        zones.append(
            ZoneRoi(
                zone_id=zone_id,
                label=_zone_label(zone_id, raw_label),
                role=_optional_string(zone.get("role"), default="zone_roi"),
                natural_item_location=_bool(zone.get("natural_item_location")),
                polygon_normalized=_parse_normalized_polygon(
                    zone.get("polygon_normalized"), path=f"zones[{index}].polygon_normalized"
                ),
                reference_markers=_parse_reference_markers(
                    zone.get("reference_markers"), path=f"zones[{index}].reference_markers"
                ),
                overlay_label_anchor_normalized=_parse_optional_normalized_point(
                    zone.get("overlay_label_anchor_normalized"),
                    path=f"zones[{index}].overlay_label_anchor_normalized",
                ),
                notes=_optional_string(zone.get("notes")),
            )
        )
    location_aliases = _parse_location_aliases(
        data.get("location_aliases"), path="location_aliases"
    )
    zone_ids = {zone.zone_id for zone in zones}
    for alias, target_zone_id in location_aliases.items():
        if target_zone_id not in zone_ids:
            raise ValueError(
                f"location_aliases.{alias} references unknown zone_id: {target_zone_id}"
            )
    return ZoneRoiConfig(
        enabled=enabled,
        source=source,
        coordinate_space=coordinate_space,
        zones=tuple(zones),
        location_aliases=location_aliases,
        status=_optional_string(data.get("status")),
    )


@lru_cache(maxsize=8)
def load_zone_roi_config_cached(path: str, enabled: bool) -> ZoneRoiConfig:
    return load_zone_roi_config(path, enabled=enabled)


def _polygon_to_pixels(
    polygon: tuple[Point, ...], *, image_width: int, image_height: int
) -> list[list[float]]:
    return [[float(x * image_width), float(y * image_height)] for x, y in polygon]


def _point_on_segment(x: float, y: float, a: Point, b: Point, *, eps: float = 1e-9) -> bool:
    ax, ay = a
    bx, by = b
    cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
    if abs(cross) > eps:
        return False
    return (
        min(ax, bx) - eps <= x <= max(ax, bx) + eps and min(ay, by) - eps <= y <= max(ay, by) + eps
    )


def _point_in_polygon(x: float, y: float, polygon: tuple[Point, ...]) -> bool:
    """Return whether a normalized/image-space point is inside a polygon.

    Uses the standard ray-casting rule. Points on horizontal/vertical edges are
    treated as inside by the endpoint callers because ZoneROI is operator-tuned
    evidence geometry, not a safety exclusion boundary.
    """

    inside = False
    count = len(polygon)
    j = count - 1
    for i in range(count):
        xi, yi = polygon[i]
        xj, yj = polygon[j]
        if _point_on_segment(x, y, polygon[j], polygon[i]):
            return True
        if ((yi > y) != (yj > y)) and (x <= (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi):
            inside = not inside
        j = i
    return inside


def zone_contains_pixel(
    zone: ZoneRoi,
    *,
    x: float,
    y: float,
    image_width: int,
    image_height: int,
) -> bool:
    """Return whether an image pixel coordinate lies inside a ZoneROI."""

    if image_width <= 0 or image_height <= 0:
        return False
    nx = float(x) / float(image_width)
    ny = float(y) / float(image_height)
    return _point_in_polygon(nx, ny, zone.polygon_normalized)


def find_zone_by_id(config: ZoneRoiConfig, zone_id: str) -> ZoneRoi | None:
    for zone in config.zones:
        if zone.zone_id == zone_id:
            return zone
    return None


def _label_anchor_xy(
    polygon_xy: list[list[float]],
    *,
    image_width: int,
    image_height: int,
    anchor_normalized: Point | None = None,
) -> list[float]:
    if anchor_normalized is not None:
        x = anchor_normalized[0] * image_width
        y = anchor_normalized[1] * image_height
        max_x = float(max(0, image_width - 1))
        max_y = float(max(14, image_height - 1))
        return [
            max(0.0, min(max_x, x)),
            max(14.0, min(max_y, y)),
        ]
    # Place zone labels just inside the polygon instead of on the border.
    # The renderer treats y as a text baseline, so this keeps the label
    # readable and avoids covering/being covered by the top ROI line.
    xs = [float(point[0]) for point in polygon_xy]
    ys = [float(point[1]) for point in polygon_xy]
    x = min(xs) + 8.0
    y = min(ys) + 24.0
    max_x = float(max(0, image_width - 1))
    max_y = float(max(14, image_height - 1))
    return [
        max(0.0, min(max_x, x)),
        max(14.0, min(max_y, y)),
    ]


def zone_to_overlay_event(
    zone: ZoneRoi,
    *,
    source: str,
    image_width: int,
    image_height: int,
    frame_seq: int | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    color_bgr = [255, 0, 255] if zone.natural_item_location else [0, 165, 255]
    label_prefix = "ZONE" if zone.natural_item_location else "REF"
    polygon_xy = _polygon_to_pixels(
        zone.polygon_normalized,
        image_width=image_width,
        image_height=image_height,
    )
    metadata: dict[str, Any] = {
        "debug_overlay": True,
        "overlay_kind": "zone_roi",
        "overlay_polygon_xy": polygon_xy,
        "overlay_color_bgr": color_bgr,
        "overlay_label": f"{label_prefix} {zone.label}",
        "overlay_label_scale": 0.7,
        "overlay_label_thickness": 2,
        "overlay_label_xy": _label_anchor_xy(
            polygon_xy,
            image_width=image_width,
            image_height=image_height,
            anchor_normalized=zone.overlay_label_anchor_normalized,
        ),
        "zone_roi": {
            "zone_id": zone.zone_id,
            "role": zone.role,
            "natural_item_location": zone.natural_item_location,
            "reference_markers": list(zone.reference_markers),
            "coordinate_space": "normalized_full_frame_xy",
        },
    }
    if frame_seq is not None:
        metadata["frame_seq"] = int(frame_seq)
        metadata["zone_roi"]["frame_seq"] = int(frame_seq)
    return {
        "timestamp": timestamp or _now_iso(),
        "source": source,
        "class_name": "zone_roi",
        "confidence": 1.0,
        "metadata": metadata,
    }


def zone_roi_overlay_events(
    config: ZoneRoiConfig,
    *,
    source: str,
    image_width: int,
    image_height: int,
    frame_seq: int | None = None,
    timestamp: str | None = None,
) -> list[dict[str, Any]]:
    if not config.enabled or source != config.source:
        return []
    return [
        zone_to_overlay_event(
            zone,
            source=source,
            image_width=image_width,
            image_height=image_height,
            frame_seq=frame_seq,
            timestamp=timestamp,
        )
        for zone in config.zones
    ]
