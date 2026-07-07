from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal, Sequence

import cv2
import numpy as np


@dataclass(frozen=True)
class RoiPolygon:
    roi_id: str
    points_xy: tuple[tuple[float, float], ...]

    def as_np(self) -> np.ndarray:
        return np.asarray(self.points_xy, dtype=np.float32)


@dataclass(frozen=True)
class DetectionCandidate:
    class_name: str
    bbox_xyxy: tuple[float, float, float, float]
    confidence: float
    track_id: str | int | None = None
    mask: np.ndarray | None = None


@dataclass(frozen=True)
class ItemDecision:
    candidate: DetectionCandidate
    accepted: bool
    reason: str
    center_inside_roi: bool
    overlap_ratio: float


@dataclass(frozen=True)
class LiftLoadEvaluation:
    roi_id: str
    count: int
    accepted: tuple[ItemDecision, ...]
    rejected: tuple[ItemDecision, ...]

    @property
    def empty(self) -> bool:
        return self.count == 0


VerificationStatus = Literal["CONFIRMED", "CANDIDATE", "FAILED"]


@dataclass(frozen=True)
class VerificationResult:
    status: VerificationStatus
    reason: str


def bbox_center(bbox_xyxy: Sequence[float]) -> tuple[float, float]:
    x1, y1, x2, y2 = bbox_xyxy
    return ((float(x1) + float(x2)) / 2.0, (float(y1) + float(y2)) / 2.0)


def bbox_area(bbox_xyxy: Sequence[float]) -> float:
    x1, y1, x2, y2 = bbox_xyxy
    return max(0.0, float(x2) - float(x1)) * max(0.0, float(y2) - float(y1))


def point_inside_roi(point_xy: tuple[float, float], roi: RoiPolygon) -> bool:
    return cv2.pointPolygonTest(roi.as_np(), point_xy, False) >= 0


def _roi_mask(roi: RoiPolygon, image_size: tuple[int, int]) -> np.ndarray:
    width, height = image_size
    mask = np.zeros((height, width), dtype=np.uint8)
    points = np.round(roi.as_np()).astype(np.int32).reshape((-1, 1, 2))
    cv2.fillPoly(mask, [points], 1)
    return mask.astype(bool)


def _bbox_mask(bbox_xyxy: Sequence[float], image_size: tuple[int, int]) -> np.ndarray:
    width, height = image_size
    x1, y1, x2, y2 = bbox_xyxy
    left = max(0, min(width, int(np.floor(x1))))
    top = max(0, min(height, int(np.floor(y1))))
    right = max(0, min(width, int(np.ceil(x2))))
    bottom = max(0, min(height, int(np.ceil(y2))))
    mask = np.zeros((height, width), dtype=bool)
    if right > left and bottom > top:
        mask[top:bottom, left:right] = True
    return mask


def candidate_roi_overlap_ratio(
    candidate: DetectionCandidate,
    roi: RoiPolygon,
    *,
    image_size: tuple[int, int],
) -> float:
    """Return candidate area fraction inside ROI.

    If an instance mask is present, mask area is used. Otherwise the bbox area
    is used. image_size is `(width, height)`.
    """

    roi_mask = _roi_mask(roi, image_size)
    if candidate.mask is not None:
        candidate_mask = np.asarray(candidate.mask, dtype=bool)
        if candidate_mask.shape != roi_mask.shape:
            raise ValueError("candidate mask shape must match image_size")
    else:
        candidate_mask = _bbox_mask(candidate.bbox_xyxy, image_size)

    area = int(candidate_mask.sum())
    if area == 0:
        return 0.0
    return float(np.logical_and(candidate_mask, roi_mask).sum() / area)


def evaluate_lift_load(
    candidates: Iterable[DetectionCandidate],
    roi: RoiPolygon,
    *,
    image_size: tuple[int, int],
    load_classes: set[str] | None = None,
    min_confidence: float = 0.5,
    min_overlap_ratio: float = 0.6,
) -> LiftLoadEvaluation:
    """Evaluate count candidates inside a lift ROI.

    This returns evidence only. WMS should combine it with lift sensor state and
    task context before final pickup/dropoff transitions.
    """

    classes = load_classes or {"box", "pallet"}
    accepted: list[ItemDecision] = []
    rejected: list[ItemDecision] = []

    for candidate in candidates:
        center_inside = point_inside_roi(bbox_center(candidate.bbox_xyxy), roi)
        try:
            overlap = candidate_roi_overlap_ratio(candidate, roi, image_size=image_size)
        except ValueError:
            decision = ItemDecision(candidate, False, "invalid_mask_shape", center_inside, 0.0)
            rejected.append(decision)
            continue

        if candidate.class_name not in classes:
            decision = ItemDecision(candidate, False, "class_not_load", center_inside, overlap)
        elif candidate.confidence < min_confidence:
            decision = ItemDecision(candidate, False, "low_confidence", center_inside, overlap)
        elif not center_inside:
            decision = ItemDecision(candidate, False, "center_outside_roi", center_inside, overlap)
        elif overlap < min_overlap_ratio:
            decision = ItemDecision(
                candidate, False, "insufficient_roi_overlap", center_inside, overlap
            )
        else:
            decision = ItemDecision(candidate, True, "accepted", center_inside, overlap)

        (accepted if decision.accepted else rejected).append(decision)

    return LiftLoadEvaluation(roi.roi_id, len(accepted), tuple(accepted), tuple(rejected))


def stable_count(
    history: Sequence[int], *, required_frames: int, expected_count: int | None = None
) -> bool:
    if required_frames <= 0:
        raise ValueError("required_frames must be positive")
    if len(history) < required_frames:
        return False
    window = list(history[-required_frames:])
    if expected_count is not None:
        return all(value == expected_count for value in window)
    return len(set(window)) == 1


def verify_pickup(
    *,
    lift_up_sensor: bool,
    load_evaluation: LiftLoadEvaluation,
    expected_count: int,
    count_stable: bool,
    dropped_item_count: int = 0,
) -> VerificationResult:
    if not lift_up_sensor:
        return VerificationResult("FAILED", "lift_up_sensor_false")
    if dropped_item_count > 0:
        return VerificationResult("FAILED", "dropped_item_candidate_present")
    if load_evaluation.count != expected_count:
        return VerificationResult("CANDIDATE", "load_count_mismatch")
    if not count_stable:
        return VerificationResult("CANDIDATE", "load_count_not_stable")
    return VerificationResult("CONFIRMED", "pickup_verified")


def verify_dropoff(
    *,
    lift_down_complete: bool,
    backoff_complete: bool,
    lift_evaluation: LiftLoadEvaluation | None = None,
    target_evaluation: LiftLoadEvaluation | None = None,
) -> VerificationResult:
    if not lift_down_complete:
        return VerificationResult("FAILED", "lift_down_not_complete")
    if not backoff_complete:
        return VerificationResult("FAILED", "backoff_not_complete")

    if lift_evaluation is None and target_evaluation is None:
        return VerificationResult("CONFIRMED", "dropoff_sequence_verified")

    if lift_evaluation is not None and not lift_evaluation.empty:
        return VerificationResult("CANDIDATE", "lift_roi_not_empty")
    if target_evaluation is not None and target_evaluation.empty:
        return VerificationResult("CANDIDATE", "target_roi_empty")
    return VerificationResult("CONFIRMED", "dropoff_vision_verified")
