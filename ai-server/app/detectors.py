from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import cv2
import numpy as np


@dataclass(frozen=True)
class MarkerDetection:
    """Deterministic 2D marker detection result from an uploaded frame."""

    class_name: str
    marker_id: str
    bbox_xyxy: list[float]
    corners_xy: tuple[tuple[float, float], ...] = ()
    confidence: float = 1.0
    detector: str = "opencv"


def decode_image(image_bytes: bytes) -> np.ndarray:
    """Decode uploaded image bytes into an OpenCV BGR image."""

    image_array = np.frombuffer(image_bytes, dtype=np.uint8)
    image = cv2.imdecode(image_array, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("uploaded image is not a decodable image")
    return image


def _corners_from_points(points: np.ndarray) -> tuple[tuple[float, float], ...]:
    pts = points.reshape(-1, 2).astype(float)
    return tuple((float(x), float(y)) for x, y in pts)


def _bbox_from_points(points: np.ndarray) -> list[float]:
    pts = points.reshape(-1, 2).astype(float)
    x_min = float(np.min(pts[:, 0]))
    y_min = float(np.min(pts[:, 1]))
    x_max = float(np.max(pts[:, 0]))
    y_max = float(np.max(pts[:, 1]))
    return [x_min, y_min, x_max, y_max]


def _detect_aruco(image: np.ndarray) -> Iterable[MarkerDetection]:
    aruco = getattr(cv2, "aruco", None)
    if aruco is None:
        return []

    dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
    if hasattr(aruco, "ArucoDetector"):
        parameters = aruco.DetectorParameters()
        corners, ids, _ = aruco.ArucoDetector(dictionary, parameters).detectMarkers(image)
    else:  # pragma: no cover - compatibility path for older OpenCV builds
        parameters = aruco.DetectorParameters_create()
        corners, ids, _ = aruco.detectMarkers(image, dictionary, parameters=parameters)

    if ids is None:
        return []

    detections: list[MarkerDetection] = []
    for marker_corners, marker_id in zip(corners, ids.flatten(), strict=False):
        bbox = _bbox_from_points(marker_corners)
        if bbox[0] < bbox[2] and bbox[1] < bbox[3]:
            detections.append(
                MarkerDetection(
                    class_name="aruco_marker",
                    marker_id=f"ARUCO_4X4_50_{int(marker_id)}",
                    bbox_xyxy=bbox,
                    corners_xy=_corners_from_points(marker_corners),
                    detector="opencv-aruco-4x4-50",
                )
            )
    return detections


def detect_markers(image: np.ndarray) -> list[MarkerDetection]:
    """Detect deterministic ArUco markers without YOLO/Torch or ROS2 dependencies."""

    detections = list(_detect_aruco(image))
    return sorted(detections, key=lambda item: (item.class_name, item.marker_id, item.bbox_xyxy))


def generate_synthetic_aruco_frame(
    *,
    marker_id: int = 7,
    marker_size: int = 96,
    padding: int = 32,
) -> np.ndarray:
    """Generate a deterministic BGR ArUco frame for robot-free Lane B validation."""

    if not 0 <= marker_id < 50:
        raise ValueError("marker_id must be between 0 and 49 for DICT_4X4_50")
    if marker_size <= 0:
        raise ValueError("marker_size must be positive")
    if padding < 0:
        raise ValueError("padding must be non-negative")
    aruco = getattr(cv2, "aruco", None)
    if aruco is None:
        raise ValueError("OpenCV ArUco module is unavailable")
    dictionary = aruco.getPredefinedDictionary(aruco.DICT_4X4_50)
    marker = aruco.generateImageMarker(dictionary, marker_id, marker_size)
    canvas_size = marker_size + (padding * 2)
    canvas = np.full((canvas_size, canvas_size), 255, dtype=np.uint8)
    canvas[padding : padding + marker_size, padding : padding + marker_size] = marker
    return cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)
