from __future__ import annotations

import json
import math
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from time import monotonic
from typing import Any

import cv2
import numpy as np

from .detectors import MarkerDetection

Point = tuple[float, float]


FRESH = "FRESH"
STALE_USABLE = "STALE_USABLE"
EXPIRED = "EXPIRED"
LOCKED = "LOCKED"


@dataclass(frozen=True)
class MapRoiConfig:
    """Runtime-tunable global-map ROI overlay configuration.

    This is intentionally diagnostic/overlay-only.  It does not define the
    Main-facing dropped-item or lift evidence contract; it only helps operators
    visually tune the map polygon before those policies are enabled.
    """

    enabled: bool = False
    source: str = "global_cam_01"
    marker_ids: tuple[str, ...] = ("ARUCO_4X4_50_11", "ARUCO_4X4_50_12")
    min_markers: int = 1
    stale_usable_s: float = 180.0
    polygon_normalized: tuple[Point, ...] = ()
    label: str = "MAP ROI"
    freeze_marker_ids: tuple[str, ...] = ()
    freeze_mode: str = "any"


@dataclass(frozen=True)
class MapRoiSnapshot:
    source: str
    status: str
    polygon_xy: tuple[Point, ...]
    markers_used: tuple[str, ...]
    missing_markers: tuple[str, ...]
    frame_size_px: tuple[int, int]
    updated_monotonic: float
    observed_monotonic: float
    age_s: float
    quality: float
    reason: str

    def with_status(
        self,
        *,
        status: str,
        observed_monotonic: float,
        missing_markers: tuple[str, ...],
        reason: str,
    ) -> "MapRoiSnapshot":
        return replace(
            self,
            status=status,
            missing_markers=missing_markers,
            observed_monotonic=observed_monotonic,
            age_s=round(max(0.0, observed_monotonic - self.updated_monotonic), 3),
            reason=reason,
        )


def normalize_marker_id(value: str | int) -> str:
    raw = str(value).strip()
    if not raw:
        raise ValueError("marker id must not be empty")
    if raw.isdigit():
        number = int(raw)
        if number < 0 or number > 49:
            raise ValueError("DICT_4X4_50 marker id must be in 0..49")
        return f"ARUCO_4X4_50_{number}"
    prefix = "ARUCO_4X4_50_"
    if raw.startswith(prefix) and raw[len(prefix) :].isdigit():
        number = int(raw[len(prefix) :])
        if number < 0 or number > 49:
            raise ValueError("DICT_4X4_50 marker id must be in 0..49")
        return f"{prefix}{number}"
    raise ValueError(f"unsupported marker id '{value}'")


def parse_marker_ids(value: str | tuple[str, ...] | list[str]) -> tuple[str, ...]:
    if isinstance(value, str):
        parts = [part.strip() for part in value.split(",") if part.strip()]
    else:
        parts = [str(part).strip() for part in value if str(part).strip()]
    normalized: list[str] = []
    for part in parts:
        marker_id = normalize_marker_id(part)
        if marker_id not in normalized:
            normalized.append(marker_id)
    return tuple(normalized)


def parse_normalized_polygon(value: str | list[Any] | tuple[Any, ...]) -> tuple[Point, ...]:
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            return ()
        if raw.startswith("["):
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError("polygon JSON is invalid") from exc
        else:
            payload = []
            for part in raw.split(";"):
                part = part.strip()
                if not part:
                    continue
                pieces = [piece.strip() for piece in part.split(",")]
                if len(pieces) != 2:
                    raise ValueError("polygon points must be x,y pairs separated by semicolons")
                payload.append(pieces)
    else:
        payload = value

    points: list[Point] = []
    for item in payload:
        if not isinstance(item, (list, tuple)) or len(item) != 2:
            raise ValueError("polygon must contain [x, y] points")
        try:
            x = float(item[0])
            y = float(item[1])
        except (TypeError, ValueError) as exc:
            raise ValueError("polygon coordinates must be numeric") from exc
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("polygon coordinates must be finite")
        if x < 0.0 or x > 1.0 or y < 0.0 or y > 1.0:
            raise ValueError("polygon coordinates must be normalized 0..1")
        points.append((x, y))
    if points and len(points) < 3:
        raise ValueError("polygon needs at least 3 points")
    return tuple(points)


def normalize_freeze_mode(value: str) -> str:
    raw = str(value or "any").strip().lower()
    if raw not in {"any", "all"}:
        raise ValueError("freeze mode must be 'any' or 'all'")
    return raw


def scale_normalized_polygon(
    polygon: tuple[Point, ...], *, image_width: int, image_height: int
) -> tuple[Point, ...]:
    max_x = max(0, int(image_width) - 1)
    max_y = max(0, int(image_height) - 1)
    return tuple((round(x * max_x, 3), round(y * max_y, 3)) for x, y in polygon)


def _marker_corners_by_id(
    detections: list[MarkerDetection] | tuple[MarkerDetection, ...],
) -> dict[str, tuple[Point, ...]]:
    by_id: dict[str, tuple[Point, ...]] = {}
    for detection in detections:
        marker_id = normalize_marker_id(detection.marker_id)
        corners = tuple((float(x), float(y)) for x, y in detection.corners_xy)
        if len(corners) >= 4:
            by_id[marker_id] = corners[:4]
    return by_id


def _flatten_marker_points(
    by_id: dict[str, tuple[Point, ...]], marker_ids: tuple[str, ...]
) -> np.ndarray:
    points: list[Point] = []
    for marker_id in marker_ids:
        points.extend(by_id[marker_id])
    return np.asarray(points, dtype=np.float32)


def _estimate_affine(ref_points: np.ndarray, current_points: np.ndarray) -> np.ndarray:
    if len(ref_points) >= 3:
        matrix, _ = cv2.estimateAffinePartial2D(ref_points, current_points, method=cv2.LMEDS)
        if matrix is not None:
            return matrix.astype(np.float32)
    ref_center = ref_points.mean(axis=0)
    current_center = current_points.mean(axis=0)
    delta = current_center - ref_center
    return np.asarray([[1.0, 0.0, float(delta[0])], [0.0, 1.0, float(delta[1])]], dtype=np.float32)


def _transform_polygon(
    polygon_xy: tuple[Point, ...], matrix: np.ndarray, *, image_width: int, image_height: int
) -> tuple[Point, ...]:
    if not polygon_xy:
        return ()
    points = np.asarray([[x, y, 1.0] for x, y in polygon_xy], dtype=np.float32)
    transformed = points @ matrix.T
    max_x = max(0.0, float(image_width - 1))
    max_y = max(0.0, float(image_height - 1))
    return tuple(
        (
            round(min(max(float(x), 0.0), max_x), 3),
            round(min(max(float(y), 0.0), max_y), 3),
        )
        for x, y in transformed
    )


class MapRoiTracker:
    """Latch a configured map polygon and update it from ArUco marker motion."""

    def __init__(self) -> None:
        self._reference_markers: dict[str, tuple[Point, ...]] = {}
        self._reference_polygon_xy: tuple[Point, ...] = ()
        self._reference_frame_size_px: tuple[int, int] | None = None
        self._last_snapshot: MapRoiSnapshot | None = None
        self._frozen_snapshot: MapRoiSnapshot | None = None

    def reset(self) -> None:
        self._reference_markers = {}
        self._reference_polygon_xy = ()
        self._reference_frame_size_px = None
        self._last_snapshot = None
        self._frozen_snapshot = None

    def update(
        self,
        *,
        source: str,
        detections: list[MarkerDetection] | tuple[MarkerDetection, ...],
        image_width: int,
        image_height: int,
        config: MapRoiConfig,
        now_monotonic: float | None = None,
    ) -> MapRoiSnapshot | None:
        if not config.enabled or source != config.source or not config.polygon_normalized:
            return None
        now = monotonic() if now_monotonic is None else float(now_monotonic)
        frame_size = (int(image_width), int(image_height))
        if (
            self._reference_frame_size_px is not None
            and self._reference_frame_size_px != frame_size
        ):
            self.reset()

        configured_ids = config.marker_ids
        if not configured_ids:
            polygon = scale_normalized_polygon(
                config.polygon_normalized, image_width=image_width, image_height=image_height
            )
            snapshot = MapRoiSnapshot(
                source=source,
                status=FRESH,
                polygon_xy=polygon,
                markers_used=(),
                missing_markers=(),
                frame_size_px=frame_size,
                updated_monotonic=now,
                observed_monotonic=now,
                age_s=0.0,
                quality=1.0,
                reason="static_normalized_polygon",
            )
            self._last_snapshot = snapshot
            return snapshot

        current_markers = _marker_corners_by_id(detections)
        visible_ids = tuple(
            marker_id for marker_id in configured_ids if marker_id in current_markers
        )
        missing_ids = tuple(
            marker_id for marker_id in configured_ids if marker_id not in current_markers
        )
        min_markers = max(1, min(int(config.min_markers), len(configured_ids)))
        if self._frozen_snapshot is not None:
            return self._frozen_snapshot.with_status(
                status=LOCKED,
                observed_monotonic=now,
                missing_markers=missing_ids,
                reason="marker_freeze_locked",
            )

        if len(visible_ids) >= min_markers and not self._reference_markers:
            self._reference_markers = {
                marker_id: current_markers[marker_id] for marker_id in visible_ids
            }
            self._reference_polygon_xy = scale_normalized_polygon(
                config.polygon_normalized,
                image_width=image_width,
                image_height=image_height,
            )
            self._reference_frame_size_px = frame_size
        elif self._reference_markers:
            # If the first latch only saw one marker, allow later observations of
            # other configured markers to become additional small-shake anchors.
            # The overlay remains diagnostic; Main-facing policies must not treat
            # this as a calibrated floor homography.
            for marker_id in visible_ids:
                self._reference_markers.setdefault(marker_id, current_markers[marker_id])

        usable_ids = tuple(
            marker_id
            for marker_id in configured_ids
            if marker_id in current_markers and marker_id in self._reference_markers
        )
        if len(usable_ids) >= min_markers and self._reference_polygon_xy:
            ref_points = _flatten_marker_points(self._reference_markers, usable_ids)
            current_points = _flatten_marker_points(current_markers, usable_ids)
            matrix = _estimate_affine(ref_points, current_points)
            polygon = _transform_polygon(
                self._reference_polygon_xy,
                matrix,
                image_width=image_width,
                image_height=image_height,
            )
            snapshot = MapRoiSnapshot(
                source=source,
                status=FRESH,
                polygon_xy=polygon,
                markers_used=usable_ids,
                missing_markers=missing_ids,
                frame_size_px=frame_size,
                updated_monotonic=now,
                observed_monotonic=now,
                age_s=0.0,
                quality=round(len(usable_ids) / max(1, len(configured_ids)), 3),
                reason="marker_affine_latch",
            )
            if self._should_freeze(
                tuple(current_markers), config.freeze_marker_ids, config.freeze_mode
            ):
                snapshot = self._freeze_snapshot(snapshot, now_monotonic=now)
            self._last_snapshot = snapshot
            return snapshot

        if self._last_snapshot is None:
            return None

        age_s = max(0.0, now - self._last_snapshot.updated_monotonic)
        if age_s <= max(0.0, float(config.stale_usable_s)):
            return self._last_snapshot.with_status(
                status=STALE_USABLE,
                observed_monotonic=now,
                missing_markers=missing_ids,
                reason="markers_missing_using_latched_polygon",
            )
        return self._last_snapshot.with_status(
            status=EXPIRED,
            observed_monotonic=now,
            missing_markers=missing_ids,
            reason="markers_missing_latched_polygon_expired",
        )

    def _should_freeze(
        self,
        visible_marker_ids: tuple[str, ...],
        freeze_marker_ids: tuple[str, ...],
        freeze_mode: str,
    ) -> bool:
        if self._frozen_snapshot is not None or not freeze_marker_ids:
            return False
        visible = set(visible_marker_ids)
        mode = normalize_freeze_mode(freeze_mode)
        if mode == "all":
            return all(marker_id in visible for marker_id in freeze_marker_ids)
        return any(marker_id in visible for marker_id in freeze_marker_ids)

    def _freeze_snapshot(self, snapshot: MapRoiSnapshot, *, now_monotonic: float) -> MapRoiSnapshot:
        frozen = replace(
            snapshot,
            status=LOCKED,
            updated_monotonic=now_monotonic,
            observed_monotonic=now_monotonic,
            age_s=0.0,
            reason="marker_freeze_latch",
        )
        self._frozen_snapshot = frozen
        return frozen


def map_roi_config_from_settings(settings: Any) -> MapRoiConfig:
    return MapRoiConfig(
        enabled=bool(getattr(settings, "vision_map_roi_enabled", False)),
        source=str(getattr(settings, "vision_map_roi_source", "global_cam_01")),
        marker_ids=parse_marker_ids(str(getattr(settings, "vision_map_roi_marker_ids", "11,12"))),
        min_markers=int(getattr(settings, "vision_map_roi_min_markers", 1)),
        stale_usable_s=float(getattr(settings, "vision_map_roi_stale_usable_s", 180.0)),
        polygon_normalized=parse_normalized_polygon(
            str(getattr(settings, "vision_map_roi_polygon_normalized", ""))
        ),
        label=str(getattr(settings, "vision_map_roi_label", "MAP ROI")),
        freeze_marker_ids=parse_marker_ids(
            str(getattr(settings, "vision_map_roi_freeze_marker_ids", ""))
        ),
        freeze_mode=normalize_freeze_mode(
            str(getattr(settings, "vision_map_roi_freeze_mode", "any"))
        ),
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def snapshot_to_overlay_event(
    snapshot: MapRoiSnapshot,
    *,
    label: str = "MAP ROI",
    frame_seq: int | None = None,
    timestamp: str | None = None,
) -> dict[str, Any] | None:
    if snapshot.status == EXPIRED or not snapshot.polygon_xy:
        return None
    # Keep Map ROI visually stable.  Status/age still appear in the label and
    # metadata, but the polygon color remains cyan so stale transitions do not
    # flicker amber in the operator's live view.
    color_bgr = [255, 255, 0]
    label_text = f"{label} {snapshot.status} age={snapshot.age_s:.1f}s"
    if snapshot.markers_used:
        label_text += " " + ",".join(marker.rsplit("_", 1)[-1] for marker in snapshot.markers_used)
    metadata: dict[str, Any] = {
        "debug_overlay": True,
        "overlay_kind": "map_roi",
        "overlay_polygon_xy": [[float(x), float(y)] for x, y in snapshot.polygon_xy],
        "overlay_color_bgr": color_bgr,
        "overlay_label": label_text,
        "map_roi": {
            "status": snapshot.status,
            "age_s": snapshot.age_s,
            "markers_used": list(snapshot.markers_used),
            "missing_markers": list(snapshot.missing_markers),
            "quality": snapshot.quality,
            "reason": snapshot.reason,
            "frame_size_px": list(snapshot.frame_size_px),
        },
    }
    if frame_seq is not None:
        metadata["frame_seq"] = int(frame_seq)
        metadata["map_roi"]["frame_seq"] = int(frame_seq)
    return {
        "timestamp": timestamp or _now_iso(),
        "source": snapshot.source,
        "class_name": "map_roi",
        "confidence": snapshot.quality,
        "metadata": metadata,
    }
