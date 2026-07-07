from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Sequence

import cv2
import numpy as np

EvidenceStatus = Literal["CANDIDATE", "CONFIRMED", "FAILED"]
ProcessingMode = Literal["full_frame_direct", "crop_first"]


@dataclass(frozen=True)
class PalletRoiCandidate:
    box_xy: tuple[tuple[float, float], ...]
    bbox_xyxy: tuple[float, float, float, float]
    center_xy: tuple[float, float]
    size_px: tuple[float, float]
    angle_deg: float
    aspect_ratio: float
    area_px: float
    confidence: float

    @property
    def long_side_px(self) -> float:
        return max(self.size_px)

    @property
    def short_side_px(self) -> float:
        return min(self.size_px)


@dataclass(frozen=True)
class NormalizedPalletCrop:
    image: np.ndarray
    source_box_xy: tuple[tuple[float, float], ...]
    target_size_px: tuple[int, int]
    transform_matrix: tuple[tuple[float, float, float], ...]
    native_size_px: tuple[float, float]


@dataclass(frozen=True)
class PartPixelBudget:
    native_part_short_side_px: float
    effective_part_short_side_px: float
    resolution_status: str


@dataclass(frozen=True)
class PartBlob:
    bbox_xyxy: tuple[float, float, float, float]
    area_px: float


@dataclass(frozen=True)
class ImageQualityAssessment:
    exposure_quality: str
    lighting_quality: str
    white_balance_quality: str
    luminance_mean: float
    luminance_stddev: float
    white_balance_delta: float


@dataclass(frozen=True)
class PalletPartReadiness:
    evidence_status: EvidenceStatus
    reason: str
    failed_quality_gates: tuple[str, ...]
    processing_mode: ProcessingMode
    internal_detection_eligible: bool
    native_part_short_side_px: float
    effective_part_short_side_px: float
    resolution_status: str
    contrast_delta: float
    contrast_quality: str
    temporal_stability: str
    exposure_quality: str
    lighting_quality: str
    white_balance_quality: str
    luminance_mean: float
    luminance_stddev: float
    white_balance_delta: float


def workspace_mm_per_px(
    frame_size_px: tuple[int, int],
    *,
    workspace_size_mm: float = 1800.0,
) -> float:
    width_px, height_px = frame_size_px
    if width_px <= 0 or height_px <= 0:
        raise ValueError("frame_size_px must be positive")
    return float(workspace_size_mm) / float(height_px)


def _as_gray(image: np.ndarray) -> np.ndarray:
    if image.ndim == 2:
        return image
    if image.ndim == 3 and image.shape[2] == 3:
        return cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    raise ValueError("image must be grayscale or BGR")


def _bbox_from_points(points: np.ndarray) -> tuple[float, float, float, float]:
    pts = points.reshape(-1, 2).astype(float)
    return (
        float(np.min(pts[:, 0])),
        float(np.min(pts[:, 1])),
        float(np.max(pts[:, 0])),
        float(np.max(pts[:, 1])),
    )


def _order_box_points(points: Sequence[Sequence[float]]) -> np.ndarray:
    pts = np.asarray(points, dtype=np.float32).reshape(4, 2)
    center = pts.mean(axis=0)
    angles = np.arctan2(pts[:, 1] - center[1], pts[:, 0] - center[0])
    ordered = pts[np.argsort(angles)]

    start = min(range(4), key=lambda index: (ordered[index][1], ordered[index][0]))
    ordered = np.roll(ordered, -start, axis=0)
    if ordered[1][0] < ordered[3][0]:
        ordered = np.asarray(
            [ordered[0], ordered[3], ordered[2], ordered[1]],
            dtype=np.float32,
        )

    top_width = float(np.linalg.norm(ordered[1] - ordered[0]))
    left_height = float(np.linalg.norm(ordered[3] - ordered[0]))
    if top_width < left_height:
        ordered = np.asarray(
            [ordered[3], ordered[0], ordered[1], ordered[2]],
            dtype=np.float32,
        )
    return ordered


def find_pallet_roi_candidates(
    image: np.ndarray,
    *,
    expected_aspect_ratio: float = 2.0,
    aspect_ratio_tolerance: float = 0.35,
    min_short_side_px: float = 24.0,
    min_background_delta: float = 30.0,
    max_candidates: int = 3,
) -> tuple[PalletRoiCandidate, ...]:
    """Find pallet-shaped ROI candidates from contrast/contour only.

    This intentionally does not depend on ArUco, AprilTag, RealSense hardware,
    runtime source ids, or view cache state.
    """

    if expected_aspect_ratio <= 0:
        raise ValueError("expected_aspect_ratio must be positive")
    if aspect_ratio_tolerance < 0:
        raise ValueError("aspect_ratio_tolerance must be non-negative")
    if min_short_side_px <= 0:
        raise ValueError("min_short_side_px must be positive")
    if min_background_delta < 0:
        raise ValueError("min_background_delta must be non-negative")
    if max_candidates <= 0:
        raise ValueError("max_candidates must be positive")

    gray = _as_gray(image)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    otsu_threshold, _ = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)
    background_floor = float(np.median(blurred)) - float(min_background_delta)
    threshold_value = max(0.0, min(float(otsu_threshold), background_floor))
    _, mask = cv2.threshold(blurred, threshold_value, 255, cv2.THRESH_BINARY_INV)
    kernel = np.ones((3, 3), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel, iterations=1)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    candidates: list[PalletRoiCandidate] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area <= 0:
            continue
        (center_x, center_y), (width, height), angle = cv2.minAreaRect(contour)
        if width <= 0 or height <= 0:
            continue
        short_side = min(float(width), float(height))
        long_side = max(float(width), float(height))
        if short_side < min_short_side_px:
            continue
        aspect_ratio = long_side / short_side
        aspect_error = abs(aspect_ratio - expected_aspect_ratio)
        if aspect_error > aspect_ratio_tolerance:
            continue
        box = cv2.boxPoints(((center_x, center_y), (width, height), angle)).astype(np.float32)
        confidence = max(0.0, 1.0 - (aspect_error / max(aspect_ratio_tolerance, 1e-6)))
        candidates.append(
            PalletRoiCandidate(
                box_xy=tuple((float(x), float(y)) for x, y in box),
                bbox_xyxy=_bbox_from_points(box),
                center_xy=(float(center_x), float(center_y)),
                size_px=(float(long_side), float(short_side)),
                angle_deg=float(angle),
                aspect_ratio=float(aspect_ratio),
                area_px=area,
                confidence=float(confidence),
            )
        )

    return tuple(
        sorted(candidates, key=lambda item: (item.confidence, item.area_px), reverse=True)[
            :max_candidates
        ]
    )


def normalize_pallet_crop(
    image: np.ndarray,
    candidate: PalletRoiCandidate,
    *,
    target_size_px: tuple[int, int] = (360, 180),
) -> NormalizedPalletCrop:
    target_width, target_height = target_size_px
    if target_width <= 0 or target_height <= 0:
        raise ValueError("target_size_px must be positive")

    source = _order_box_points(candidate.box_xy)
    target = np.asarray(
        [
            [0.0, 0.0],
            [float(target_width - 1), 0.0],
            [float(target_width - 1), float(target_height - 1)],
            [0.0, float(target_height - 1)],
        ],
        dtype=np.float32,
    )
    matrix = cv2.getPerspectiveTransform(source, target)
    warped = cv2.warpPerspective(image, matrix, (target_width, target_height))
    return NormalizedPalletCrop(
        image=warped,
        source_box_xy=tuple((float(x), float(y)) for x, y in source),
        target_size_px=(target_width, target_height),
        transform_matrix=tuple(tuple(float(value) for value in row) for row in matrix),
        native_size_px=candidate.size_px,
    )


def estimate_full_frame_part_budget(
    frame_size_px: tuple[int, int],
    *,
    workspace_size_mm: float = 1800.0,
    part_short_side_mm: float = 40.0,
    model_input_size_px: tuple[int, int] = (640, 640),
    min_effective_part_px: float = 20.0,
    preferred_effective_part_px: float = 30.0,
) -> PartPixelBudget:
    frame_width, frame_height = frame_size_px
    model_width, model_height = model_input_size_px
    if part_short_side_mm <= 0:
        raise ValueError("part_short_side_mm must be positive")
    if model_width <= 0 or model_height <= 0:
        raise ValueError("model_input_size_px must be positive")
    mm_per_px = workspace_mm_per_px(
        (frame_width, frame_height), workspace_size_mm=workspace_size_mm
    )
    native_px = part_short_side_mm / mm_per_px
    resize_scale = min(
        float(model_width) / float(frame_width),
        float(model_height) / float(frame_height),
    )
    effective_px = native_px * resize_scale
    return PartPixelBudget(
        native_part_short_side_px=float(native_px),
        effective_part_short_side_px=float(effective_px),
        resolution_status=_resolution_status(
            effective_px,
            minimum_px=min_effective_part_px,
            preferred_px=preferred_effective_part_px,
        ),
    )


def estimate_crop_first_part_budget(
    candidate: PalletRoiCandidate,
    *,
    workspace_size_mm: float = 1800.0,
    frame_size_px: tuple[int, int],
    part_short_side_mm: float = 40.0,
    target_size_px: tuple[int, int] = (360, 180),
    min_native_part_px: float = 20.0,
    preferred_native_part_px: float = 30.0,
) -> PartPixelBudget:
    if part_short_side_mm <= 0:
        raise ValueError("part_short_side_mm must be positive")
    mm_per_px = workspace_mm_per_px(frame_size_px, workspace_size_mm=workspace_size_mm)
    native_px = part_short_side_mm / mm_per_px
    target_width, target_height = target_size_px
    crop_scale = min(
        float(target_width) / max(candidate.long_side_px, 1e-6),
        float(target_height) / max(candidate.short_side_px, 1e-6),
    )
    return PartPixelBudget(
        native_part_short_side_px=float(native_px),
        effective_part_short_side_px=float(native_px * crop_scale),
        resolution_status=_resolution_status(
            native_px,
            minimum_px=min_native_part_px,
            preferred_px=preferred_native_part_px,
        ),
    )


def _resolution_status(value_px: float, *, minimum_px: float, preferred_px: float) -> str:
    if value_px < minimum_px:
        return "insufficient_resolution"
    if value_px < preferred_px:
        return "marginal"
    return "ok"


def crop_contrast_delta(image: np.ndarray) -> float:
    gray = _as_gray(image).astype(np.float32)
    # Small parts occupy little crop area; p2/p98 keeps localized contrast visible.
    p2, p98 = np.percentile(gray, [2, 98])
    return float(p98 - p2)


def assess_image_quality(
    image: np.ndarray,
    *,
    min_luminance_mean: float = 35.0,
    max_luminance_mean: float = 220.0,
    min_luminance_stddev: float = 6.0,
    max_white_balance_delta: float = 55.0,
) -> ImageQualityAssessment:
    if min_luminance_mean < 0 or max_luminance_mean <= min_luminance_mean:
        raise ValueError("luminance mean thresholds must be ordered and non-negative")
    if min_luminance_stddev < 0:
        raise ValueError("min_luminance_stddev must be non-negative")
    if max_white_balance_delta < 0:
        raise ValueError("max_white_balance_delta must be non-negative")

    gray = _as_gray(image).astype(np.float32)
    luminance_mean = float(np.mean(gray))
    luminance_stddev = float(np.std(gray))
    exposure_quality = "ok"
    if luminance_mean < min_luminance_mean or luminance_mean > max_luminance_mean:
        exposure_quality = "bad_exposure"

    lighting_quality = "ok"
    if luminance_stddev < min_luminance_stddev:
        lighting_quality = "poor_lighting"

    white_balance_delta = 0.0
    if image.ndim == 3:
        channel_means = image.astype(np.float32).reshape(-1, image.shape[2]).mean(axis=0)
        white_balance_delta = float(np.max(channel_means) - np.min(channel_means))
    white_balance_quality = "ok"
    if white_balance_delta > max_white_balance_delta:
        white_balance_quality = "bad_white_balance"

    return ImageQualityAssessment(
        exposure_quality=exposure_quality,
        lighting_quality=lighting_quality,
        white_balance_quality=white_balance_quality,
        luminance_mean=luminance_mean,
        luminance_stddev=luminance_stddev,
        white_balance_delta=white_balance_delta,
    )


def temporally_stable_count(
    count_history: Sequence[int],
    *,
    required_frames: int = 5,
    min_agreeing_frames: int = 4,
    expected_count: int | None = None,
) -> bool:
    if required_frames <= 0:
        raise ValueError("required_frames must be positive")
    if min_agreeing_frames <= 0 or min_agreeing_frames > required_frames:
        raise ValueError("min_agreeing_frames must be between 1 and required_frames")
    if len(count_history) < required_frames:
        return False
    window = [int(value) for value in count_history[-required_frames:]]
    if expected_count is not None:
        return window.count(int(expected_count)) >= min_agreeing_frames
    return max(window.count(value) for value in set(window)) >= min_agreeing_frames


def assess_part_readiness(
    image: np.ndarray,
    *,
    processing_mode: ProcessingMode,
    pixel_budget: PartPixelBudget,
    count_history: Sequence[int],
    expected_count: int | None = None,
    min_native_part_px: float = 20.0,
    min_effective_part_px: float = 20.0,
    min_contrast_delta: float = 18.0,
    required_stable_frames: int = 5,
    min_agreeing_frames: int = 4,
    min_luminance_mean: float = 35.0,
    max_luminance_mean: float = 220.0,
    min_luminance_stddev: float = 6.0,
    max_white_balance_delta: float = 55.0,
    confirm_when_eligible: bool = False,
) -> PalletPartReadiness:
    failed: list[str] = []
    if processing_mode == "full_frame_direct":
        if pixel_budget.effective_part_short_side_px < min_effective_part_px:
            failed.append("insufficient_part_pixels")
    elif processing_mode == "crop_first":
        if pixel_budget.native_part_short_side_px < min_native_part_px:
            failed.append("insufficient_part_pixels")
    else:
        raise ValueError("processing_mode must be full_frame_direct or crop_first")

    contrast_delta = crop_contrast_delta(image)
    contrast_quality = "ok"
    if contrast_delta < min_contrast_delta:
        contrast_quality = "low_contrast"
        failed.append("low_contrast")

    image_quality = assess_image_quality(
        image,
        min_luminance_mean=min_luminance_mean,
        max_luminance_mean=max_luminance_mean,
        min_luminance_stddev=min_luminance_stddev,
        max_white_balance_delta=max_white_balance_delta,
    )
    if image_quality.exposure_quality != "ok":
        failed.append(image_quality.exposure_quality)
    if image_quality.lighting_quality != "ok":
        failed.append(image_quality.lighting_quality)
    if image_quality.white_balance_quality != "ok":
        failed.append(image_quality.white_balance_quality)

    temporal_stability = "ok"
    if not temporally_stable_count(
        count_history,
        required_frames=required_stable_frames,
        min_agreeing_frames=min_agreeing_frames,
        expected_count=expected_count,
    ):
        temporal_stability = "unstable_part_count"
        failed.append("unstable_part_count")

    internal_detection_eligible = processing_mode == "crop_first" and not failed
    if failed:
        reason = failed[0]
    elif processing_mode == "crop_first":
        reason = "crop_first_candidate"
    else:
        reason = "full_frame_internal_detection_disabled"
    evidence_status: EvidenceStatus = "CANDIDATE"
    if internal_detection_eligible and confirm_when_eligible:
        evidence_status = "CONFIRMED"

    return PalletPartReadiness(
        evidence_status=evidence_status,
        reason=reason,
        failed_quality_gates=tuple(failed),
        processing_mode=processing_mode,
        internal_detection_eligible=internal_detection_eligible,
        native_part_short_side_px=float(pixel_budget.native_part_short_side_px),
        effective_part_short_side_px=float(pixel_budget.effective_part_short_side_px),
        resolution_status=pixel_budget.resolution_status,
        contrast_delta=float(contrast_delta),
        contrast_quality=contrast_quality,
        temporal_stability=temporal_stability,
        exposure_quality=image_quality.exposure_quality,
        lighting_quality=image_quality.lighting_quality,
        white_balance_quality=image_quality.white_balance_quality,
        luminance_mean=image_quality.luminance_mean,
        luminance_stddev=image_quality.luminance_stddev,
        white_balance_delta=image_quality.white_balance_delta,
    )


def detect_high_contrast_part_blobs(
    normalized_crop: np.ndarray,
    *,
    min_area_px: float = 250.0,
) -> tuple[PartBlob, ...]:
    if min_area_px <= 0:
        raise ValueError("min_area_px must be positive")
    if normalized_crop.ndim != 3 or normalized_crop.shape[2] != 3:
        raise ValueError("normalized_crop must be a BGR image")

    hsv = cv2.cvtColor(normalized_crop, cv2.COLOR_BGR2HSV)
    saturation = hsv[:, :, 1]
    value = hsv[:, :, 2]
    mask = np.logical_and(saturation > 50, value > 40).astype(np.uint8) * 255
    kernel = np.ones((7, 7), dtype=np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel, iterations=1)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    blobs: list[PartBlob] = []
    for contour in contours:
        area = float(cv2.contourArea(contour))
        if area < min_area_px:
            continue
        x, y, width, height = cv2.boundingRect(contour)
        blobs.append(
            PartBlob(
                bbox_xyxy=(float(x), float(y), float(x + width), float(y + height)),
                area_px=area,
            )
        )
    return tuple(sorted(blobs, key=lambda blob: blob.bbox_xyxy))
