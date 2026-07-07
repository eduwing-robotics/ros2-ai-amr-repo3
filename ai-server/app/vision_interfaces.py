from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Protocol, Sequence

import cv2
import numpy as np

from .lift_roi import DetectionCandidate

BBox = tuple[float, float, float, float]
TrackId = str | int | None


@dataclass(frozen=True)
class DetectionBox:
    """Model-agnostic object detection result with bbox evidence only."""

    class_name: str
    bbox_xyxy: BBox
    confidence: float
    track_id: TrackId = None
    detector: str = "provided-bbox"


@dataclass(frozen=True)
class InstanceMask:
    """Model-agnostic instance-segmentation result.

    The raw mask stays inside the AI Server process. Public contracts expose
    only summary fields such as `evidence_type` and `mask_area_px`.
    """

    class_name: str
    bbox_xyxy: BBox
    confidence: float
    mask: np.ndarray
    track_id: TrackId = None
    detector: str = "provided-instance-mask"


DetectorResult = DetectionBox | InstanceMask


class DetectorSegmenter(Protocol):
    """Internal seam for future detector or segmenter providers."""

    detector_name: str

    def detect(self, image: np.ndarray) -> Iterable[DetectorResult]:
        """Return image-space object candidates without owning WMS decisions."""


@dataclass(frozen=True)
class StaticCandidateProvider:
    """Deterministic provider used by tests and pre-model API callers."""

    results: tuple[DetectorResult, ...]
    detector_name: str = "provided-candidates"

    def detect(self, image: np.ndarray) -> Iterable[DetectorResult]:
        _ = image
        return self.results


def normalize_bbox_xyxy(value: Sequence[float]) -> BBox:
    try:
        value_len = len(value)
    except TypeError as exc:
        raise ValueError("bbox_xyxy must contain exactly four numbers") from exc
    if value_len != 4:
        raise ValueError("bbox_xyxy must contain exactly four numbers")
    try:
        x1, y1, x2, y2 = (float(part) for part in value)
    except (TypeError, ValueError) as exc:
        raise ValueError("bbox_xyxy values must be numeric") from exc
    if not (x1 < x2 and y1 < y2):
        raise ValueError("bbox_xyxy must satisfy x1 < x2 and y1 < y2")
    return (x1, y1, x2, y2)


def validate_confidence(value: float) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("confidence must be numeric") from exc
    if not 0.0 <= confidence <= 1.0:
        raise ValueError("confidence must be between 0 and 1")
    return confidence


def mask_from_polygon(
    polygon_xy: Sequence[Sequence[float]],
    *,
    image_size: tuple[int, int],
) -> np.ndarray:
    """Rasterize a polygon to a boolean mask for synthetic seam tests/API input."""

    try:
        point_count = len(polygon_xy)
    except TypeError as exc:
        raise ValueError("mask_polygon_xy must contain at least three points") from exc
    if point_count < 3:
        raise ValueError("mask_polygon_xy must contain at least three points")
    width, height = image_size
    mask = np.zeros((height, width), dtype=np.uint8)
    try:
        points = np.asarray(polygon_xy, dtype=np.float32)
    except (TypeError, ValueError) as exc:
        raise ValueError("mask_polygon_xy points must be numeric [x, y] pairs") from exc
    if points.ndim != 2 or points.shape[1] != 2:
        raise ValueError("mask_polygon_xy points must be [x, y] pairs")
    cv2.fillPoly(mask, [np.round(points).astype(np.int32).reshape((-1, 1, 2))], 1)
    return mask.astype(bool)


def evidence_type(result: DetectorResult) -> str:
    return "instance_mask" if isinstance(result, InstanceMask) else "bbox"


def mask_area_px(result: DetectorResult) -> int | None:
    if isinstance(result, InstanceMask):
        return int(np.asarray(result.mask, dtype=bool).sum())
    return None


def to_lift_roi_candidate(result: DetectorResult) -> DetectionCandidate:
    mask = np.asarray(result.mask, dtype=bool) if isinstance(result, InstanceMask) else None
    return DetectionCandidate(
        class_name=result.class_name,
        bbox_xyxy=result.bbox_xyxy,
        confidence=result.confidence,
        track_id=result.track_id,
        mask=mask,
    )


def to_lift_roi_candidates(results: Iterable[DetectorResult]) -> tuple[DetectionCandidate, ...]:
    return tuple(to_lift_roi_candidate(result) for result in results)
