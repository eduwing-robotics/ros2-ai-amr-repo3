from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from importlib import import_module
from threading import Lock
from typing import Any

import cv2
import numpy as np

from .vision_interfaces import DetectionBox, DetectorResult, InstanceMask


class ModelAdapterError(RuntimeError):
    """Raised when optional model runtime configuration is unavailable or invalid."""


@dataclass(frozen=True)
class VisionModelConfig:
    model_path: str
    task: str = "segment"
    confidence: float = 0.5
    iou: float = 0.5
    image_size: int = 640
    device: str = "cpu"
    class_map: Mapping[str, str] = field(default_factory=dict)
    unmapped_class: str = "unknown"


class UltralyticsSegmenterAdapter:
    """Segmentation-primary Ultralytics adapter with bbox fallback.

    Ultralytics is imported only during adapter construction so the AI Server
    core remains importable without heavy model packages installed.
    """

    def __init__(self, config: VisionModelConfig) -> None:
        if not config.model_path.strip():
            raise ModelAdapterError("vision model path is not configured")
        if config.task not in {"segment", "detect"}:
            raise ModelAdapterError("vision model task must be 'segment' or 'detect'")
        try:
            yolo_cls = import_module("ultralytics").YOLO
        except Exception as exc:  # noqa: BLE001 - optional runtime may be absent
            raise ModelAdapterError("ultralytics package is not installed") from exc

        self.config = config
        self._class_map = {str(key): str(value) for key, value in dict(config.class_map).items()}
        self._unmapped_class = str(config.unmapped_class)
        self.detector_name = f"ultralytics-{config.task}:{config.model_path}"
        self._model = yolo_cls(config.model_path, task=config.task)
        self._lock = Lock()

    def detect(self, image: np.ndarray) -> Iterable[DetectorResult]:
        with self._lock:
            results = self._model.predict(
                image,
                conf=self.config.confidence,
                iou=self.config.iou,
                imgsz=self.config.image_size,
                device=self.config.device,
                verbose=False,
            )
        return tuple(
            _results_to_detector_results(
                results,
                self.detector_name,
                class_map=self._class_map,
                unmapped_class=self._unmapped_class,
            )
        )


def _as_numpy(value: Any) -> np.ndarray:
    if value is None:
        return np.asarray([])
    if hasattr(value, "detach"):
        value = value.detach()
    if hasattr(value, "cpu"):
        value = value.cpu()
    if hasattr(value, "numpy"):
        value = value.numpy()
    return np.asarray(value)


PUBLIC_VISION_CLASSES = {
    "aruco_marker",
    "qr_marker",
    "apriltag_marker",
    "person",
    "obstacle",
    "box",
    "dropped_item",
    "pallet",
    "unknown",
}


def _class_name(names: Any, class_id: int) -> str:
    if isinstance(names, dict):
        return str(names.get(class_id, class_id))
    if isinstance(names, list) and 0 <= class_id < len(names):
        return str(names[class_id])
    return str(class_id)


def _normalize_class_name(
    raw_class_name: str, *, class_map: Mapping[str, str], unmapped_class: str
) -> str:
    mapped = class_map.get(raw_class_name, raw_class_name)
    if mapped in PUBLIC_VISION_CLASSES:
        return mapped
    if unmapped_class in PUBLIC_VISION_CLASSES:
        return unmapped_class
    return "unknown"


def _resize_mask_to_image(mask: np.ndarray, image_shape: tuple[int, int]) -> np.ndarray:
    height, width = image_shape
    mask_bool = np.asarray(mask, dtype=bool)
    if mask_bool.shape == (height, width):
        return mask_bool
    resized = cv2.resize(
        mask_bool.astype(np.uint8),
        (width, height),
        interpolation=cv2.INTER_NEAREST,
    )
    return resized.astype(bool)


def _results_to_detector_results(
    results: Any,
    detector_name: str,
    *,
    class_map: Mapping[str, str] | None = None,
    unmapped_class: str = "unknown",
) -> tuple[DetectorResult, ...]:
    resolved_class_map = class_map or {}
    detector_results: list[DetectorResult] = []
    for result in results:
        boxes = getattr(result, "boxes", None)
        if boxes is None:
            continue
        xyxy = _as_numpy(getattr(boxes, "xyxy", None))
        conf = _as_numpy(getattr(boxes, "conf", None))
        cls = _as_numpy(getattr(boxes, "cls", None))
        ids = _as_numpy(getattr(boxes, "id", None))
        masks_obj = getattr(result, "masks", None)
        masks = _as_numpy(getattr(masks_obj, "data", None)) if masks_obj is not None else None
        orig_shape = tuple(getattr(result, "orig_shape", (0, 0)))
        names = getattr(result, "names", {})

        for idx, bbox in enumerate(xyxy):
            class_id = int(cls[idx]) if idx < len(cls) else -1
            confidence = float(conf[idx]) if idx < len(conf) else 0.0
            track_id = None
            if ids.size and idx < len(ids):
                raw_track_id = ids[idx]
                track_id = (
                    int(raw_track_id) if float(raw_track_id).is_integer() else str(raw_track_id)
                )
            bbox_tuple = tuple(float(value) for value in bbox[:4])
            raw_class_name = _class_name(names, class_id)
            class_name = _normalize_class_name(
                raw_class_name,
                class_map=resolved_class_map,
                unmapped_class=unmapped_class,
            )

            if masks is not None and idx < len(masks) and len(orig_shape) == 2:
                mask = _resize_mask_to_image(masks[idx], (int(orig_shape[0]), int(orig_shape[1])))
                detector_results.append(
                    InstanceMask(
                        class_name=class_name,
                        bbox_xyxy=bbox_tuple,  # type: ignore[arg-type]
                        confidence=confidence,
                        mask=mask,
                        track_id=track_id,
                        detector=detector_name,
                    )
                )
            else:
                detector_results.append(
                    DetectionBox(
                        class_name=class_name,
                        bbox_xyxy=bbox_tuple,  # type: ignore[arg-type]
                        confidence=confidence,
                        track_id=track_id,
                        detector=detector_name,
                    )
                )
    return tuple(detector_results)
