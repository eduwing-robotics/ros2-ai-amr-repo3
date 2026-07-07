from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

import numpy as np

from .pallet_crop import find_pallet_roi_candidates
from .vision_interfaces import DetectionBox, DetectorResult

ROI_CROP_VIEW_KINDS = {"smart_tracked_roi_crop", "tracked_roi_crop"}
DEFAULT_LIFT_ROI_NORMALIZED = (0.18, 0.18, 0.82, 0.88)


@dataclass(frozen=True)
class SmartRoiSelection:
    """One crop-first ROI decision in full-frame pixel coordinates.

    The selection is deliberately model-agnostic: camera adapters, API handlers,
    and tests can share the same crop, pixel-gain, and coordinate-mapping rules
    without coupling the source registry to a specific detector implementation.
    """

    view_id: str
    bbox_xyxy: tuple[int, int, int, int]
    frame_size_px: tuple[int, int]
    selection_source: str
    confidence: float
    reason: str
    model_input_size_px: tuple[int, int] = (640, 640)

    @property
    def crop_size_px(self) -> tuple[int, int]:
        x1, y1, x2, y2 = self.bbox_xyxy
        return x2 - x1, y2 - y1

    @property
    def pixel_gain_vs_full_resize(self) -> float:
        """Approximate model-space pixel gain vs resizing the whole frame first."""

        frame_width, frame_height = self.frame_size_px
        crop_width, crop_height = self.crop_size_px
        model_width, model_height = self.model_input_size_px
        full_scale = min(model_width / frame_width, model_height / frame_height)
        crop_scale = min(model_width / crop_width, model_height / crop_height)
        if full_scale <= 0:
            return 1.0
        return float(crop_scale / full_scale)

    def metadata(self) -> dict[str, Any]:
        crop_width, crop_height = self.crop_size_px
        frame_width, frame_height = self.frame_size_px
        x1, y1, x2, y2 = self.bbox_xyxy
        return {
            "view_id": self.view_id,
            "bbox_xyxy": [x1, y1, x2, y2],
            "crop_size_px": {"width": crop_width, "height": crop_height},
            "frame_size_px": {"width": frame_width, "height": frame_height},
            "selection_source": self.selection_source,
            "confidence": round(self.confidence, 3),
            "reason": self.reason,
            "model_input_size_px": {
                "width": self.model_input_size_px[0],
                "height": self.model_input_size_px[1],
            },
            "pixel_gain_vs_full_resize": round(self.pixel_gain_vs_full_resize, 3),
        }

    def roi_json_for_crop(self, *, roi_id: str | None = None, kind: str = "LIFT") -> dict[str, Any]:
        """Return a LiftRoiEvidence-compatible ROI polygon in crop coordinates."""

        crop_width, crop_height = self.crop_size_px
        return {
            "roi_id": roi_id or self.view_id,
            "kind": kind,
            "polygon_xy": [
                [0.0, 0.0],
                [float(crop_width - 1), 0.0],
                [float(crop_width - 1), float(crop_height - 1)],
                [0.0, float(crop_height - 1)],
            ],
        }


def _clamp_bbox(
    bbox_xyxy: Sequence[float | int],
    *,
    frame_size_px: tuple[int, int],
    min_side_px: int = 8,
) -> tuple[int, int, int, int]:
    frame_width, frame_height = frame_size_px
    if frame_width <= 0 or frame_height <= 0:
        raise ValueError("frame_size_px must be positive")
    if len(bbox_xyxy) != 4:
        raise ValueError("bbox_xyxy must contain exactly four values")
    x1, y1, x2, y2 = (int(round(float(value))) for value in bbox_xyxy)
    x1 = max(0, min(frame_width - 1, x1))
    y1 = max(0, min(frame_height - 1, y1))
    x2 = max(1, min(frame_width, x2))
    y2 = max(1, min(frame_height, y2))
    if x2 <= x1:
        x2 = min(frame_width, x1 + min_side_px)
        x1 = max(0, x2 - min_side_px)
    if y2 <= y1:
        y2 = min(frame_height, y1 + min_side_px)
        y1 = max(0, y2 - min_side_px)
    if x2 - x1 < min_side_px:
        extra = min_side_px - (x2 - x1)
        x1 = max(0, x1 - extra // 2)
        x2 = min(frame_width, x2 + extra - extra // 2)
    if y2 - y1 < min_side_px:
        extra = min_side_px - (y2 - y1)
        y1 = max(0, y1 - extra // 2)
        y2 = min(frame_height, y2 + extra - extra // 2)
    return x1, y1, x2, y2


def _expand_bbox(
    bbox_xyxy: Sequence[float | int],
    *,
    frame_size_px: tuple[int, int],
    margin_ratio: float,
    min_side_px: int,
) -> tuple[int, int, int, int]:
    if margin_ratio < 0:
        raise ValueError("margin_ratio must be non-negative")
    x1, y1, x2, y2 = (float(value) for value in bbox_xyxy)
    width = max(1.0, x2 - x1)
    height = max(1.0, y2 - y1)
    margin_x = width * margin_ratio
    margin_y = height * margin_ratio
    return _clamp_bbox(
        (x1 - margin_x, y1 - margin_y, x2 + margin_x, y2 + margin_y),
        frame_size_px=frame_size_px,
        min_side_px=min_side_px,
    )


def parse_normalized_bbox(
    value: str | Sequence[float] | None,
) -> tuple[float, float, float, float] | None:
    """Parse an optional normalized x1,y1,x2,y2 ROI hint."""

    if value is None:
        return None
    if isinstance(value, str):
        if not value.strip():
            return None
        parts = [part.strip() for part in value.replace(";", ",").split(",")]
        if len(parts) != 4:
            raise ValueError("normalized ROI hint must contain x1,y1,x2,y2")
        bbox = tuple(float(part) for part in parts)
    else:
        if len(value) != 4:
            raise ValueError("normalized ROI hint must contain x1,y1,x2,y2")
        bbox = tuple(float(part) for part in value)
    x1, y1, x2, y2 = bbox
    if not (0.0 <= x1 < x2 <= 1.0 and 0.0 <= y1 < y2 <= 1.0):
        raise ValueError("normalized ROI hint must satisfy 0 <= x1 < x2 <= 1 and 0 <= y1 < y2 <= 1")
    return bbox  # type: ignore[return-value]


def normalized_bbox_to_pixels(
    bbox_norm: Sequence[float],
    *,
    frame_size_px: tuple[int, int],
    min_side_px: int = 8,
) -> tuple[int, int, int, int]:
    frame_width, frame_height = frame_size_px
    x1, y1, x2, y2 = (float(value) for value in bbox_norm)
    return _clamp_bbox(
        (x1 * frame_width, y1 * frame_height, x2 * frame_width, y2 * frame_height),
        frame_size_px=frame_size_px,
        min_side_px=min_side_px,
    )


def select_smart_roi(
    image: np.ndarray,
    *,
    view_id: str,
    roi_hint_normalized: Sequence[float] | None = None,
    model_input_size_px: tuple[int, int] = (640, 640),
    margin_ratio: float = 0.2,
    min_side_px: int = 64,
) -> SmartRoiSelection:
    """Choose a deterministic crop-first ROI from a full camera frame.

    Priority order:
    1. explicit map/calibration hint in normalized frame coordinates,
    2. high-contrast pallet-like contour candidate,
    3. conservative central fallback sized for the currently mounted overview.
    """

    if image.ndim < 2:
        raise ValueError("image must have at least height and width")
    frame_height, frame_width = image.shape[:2]
    frame_size_px = (int(frame_width), int(frame_height))
    model_width, model_height = model_input_size_px
    if model_width <= 0 or model_height <= 0:
        raise ValueError("model_input_size_px must be positive")

    if roi_hint_normalized is not None:
        hinted = normalized_bbox_to_pixels(
            roi_hint_normalized,
            frame_size_px=frame_size_px,
            min_side_px=min_side_px,
        )
        bbox = _expand_bbox(
            hinted,
            frame_size_px=frame_size_px,
            margin_ratio=margin_ratio,
            min_side_px=min_side_px,
        )
        return SmartRoiSelection(
            view_id=view_id,
            bbox_xyxy=bbox,
            frame_size_px=frame_size_px,
            selection_source="normalized_hint",
            confidence=1.0,
            reason="operator/map ROI hint",
            model_input_size_px=model_input_size_px,
        )

    candidates = find_pallet_roi_candidates(
        image,
        expected_aspect_ratio=2.0,
        aspect_ratio_tolerance=0.55,
        min_short_side_px=max(16.0, min_side_px / 2.0),
        min_background_delta=20.0,
        max_candidates=1,
    )
    if candidates:
        candidate = candidates[0]
        bbox = _expand_bbox(
            candidate.bbox_xyxy,
            frame_size_px=frame_size_px,
            margin_ratio=margin_ratio,
            min_side_px=min_side_px,
        )
        return SmartRoiSelection(
            view_id=view_id,
            bbox_xyxy=bbox,
            frame_size_px=frame_size_px,
            selection_source="pallet_contour",
            confidence=max(0.2, min(0.95, candidate.confidence)),
            reason="high-contrast pallet-like contour",
            model_input_size_px=model_input_size_px,
        )

    fallback_norm = DEFAULT_LIFT_ROI_NORMALIZED
    bbox = normalized_bbox_to_pixels(
        fallback_norm,
        frame_size_px=frame_size_px,
        min_side_px=min_side_px,
    )
    return SmartRoiSelection(
        view_id=view_id,
        bbox_xyxy=bbox,
        frame_size_px=frame_size_px,
        selection_source="central_fallback",
        confidence=0.25,
        reason="no ROI hint or stable contour candidate; using central workspace fallback",
        model_input_size_px=model_input_size_px,
    )


def crop_smart_roi(image: np.ndarray, selection: SmartRoiSelection) -> np.ndarray:
    x1, y1, x2, y2 = selection.bbox_xyxy
    return image[y1:y2, x1:x2].copy()


def translate_bbox_from_roi_to_full(
    bbox_xyxy: Sequence[float | int],
    selection: SmartRoiSelection,
) -> tuple[float, float, float, float]:
    x1, y1, _, _ = selection.bbox_xyxy
    bx1, by1, bx2, by2 = (float(value) for value in bbox_xyxy)
    return bx1 + x1, by1 + y1, bx2 + x1, by2 + y1


def translate_bbox_from_full_to_roi(
    bbox_xyxy: Sequence[float | int],
    selection: SmartRoiSelection,
) -> tuple[float, float, float, float] | None:
    roi_x1, roi_y1, roi_x2, roi_y2 = selection.bbox_xyxy
    x1, y1, x2, y2 = (float(value) for value in bbox_xyxy)
    ix1 = max(float(roi_x1), x1)
    iy1 = max(float(roi_y1), y1)
    ix2 = min(float(roi_x2), x2)
    iy2 = min(float(roi_y2), y2)
    if ix2 <= ix1 or iy2 <= iy1:
        return None
    return ix1 - roi_x1, iy1 - roi_y1, ix2 - roi_x1, iy2 - roi_y1


def translate_detector_result_from_roi_to_full(
    result: DetectorResult,
    selection: SmartRoiSelection,
) -> DetectionBox:
    """Map a crop-space detector result to full-frame VisionEvent coordinates."""

    detector = getattr(result, "detector", "roi-detector")
    detector_name = f"{detector}:{selection.view_id}"
    return DetectionBox(
        class_name=str(getattr(result, "class_name", "unknown")),
        bbox_xyxy=translate_bbox_from_roi_to_full(
            getattr(result, "bbox_xyxy"),
            selection,
        ),
        confidence=float(getattr(result, "confidence", 0.0)),
        track_id=getattr(result, "track_id", None),
        detector=detector_name,
    )


def event_for_roi_overlay(
    event: dict[str, Any], selection: SmartRoiSelection
) -> dict[str, Any] | None:
    """Return an event copy whose bbox is expressed in crop coordinates."""

    bbox = event.get("bbox_xyxy")
    if not isinstance(bbox, list | tuple) or len(bbox) != 4:
        return None
    translated = translate_bbox_from_full_to_roi(bbox, selection)
    if translated is None:
        return None
    roi_event = dict(event)
    roi_event["bbox_xyxy"] = [float(value) for value in translated]
    metadata = dict(roi_event.get("metadata") or {})
    metadata["roi_view"] = selection.view_id
    metadata["roi_selection"] = selection.metadata()
    roi_event["metadata"] = metadata
    return roi_event


def estimate_object_pixel_budget(
    *,
    object_size_m: float,
    visible_scene_width_m: float,
    frame_width_px: int,
    pixel_gain_vs_full_resize: float = 1.0,
    min_object_px: float = 12.0,
) -> dict[str, Any]:
    """Estimate model-space pixels available for a small object.

    This is a deterministic planning/observability helper, not a detector.
    It lets the GoPro/global-camera path report when a 4 cm dropped-item target
    is below the current stream/evidence pixel budget before operators raise
    continuous AI FPS or model input size.
    """

    if object_size_m <= 0:
        raise ValueError("object_size_m must be positive")
    if visible_scene_width_m <= 0:
        raise ValueError("visible_scene_width_m must be positive")
    if frame_width_px <= 0:
        raise ValueError("frame_width_px must be positive")
    if pixel_gain_vs_full_resize <= 0:
        raise ValueError("pixel_gain_vs_full_resize must be positive")
    if min_object_px <= 0:
        raise ValueError("min_object_px must be positive")

    full_frame_object_px = (object_size_m / visible_scene_width_m) * float(frame_width_px)
    effective_object_px = full_frame_object_px * float(pixel_gain_vs_full_resize)
    return {
        "object_size_m": round(float(object_size_m), 4),
        "visible_scene_width_m": round(float(visible_scene_width_m), 4),
        "frame_width_px": int(frame_width_px),
        "pixel_gain_vs_full_resize": round(float(pixel_gain_vs_full_resize), 3),
        "full_frame_object_px": round(full_frame_object_px, 2),
        "effective_object_px": round(effective_object_px, 2),
        "min_object_px": round(float(min_object_px), 2),
        "meets_min_object_px": effective_object_px >= float(min_object_px),
    }
