from __future__ import annotations

import cv2
import numpy as np
import pytest

from app.detectors import decode_image, detect_markers


def _marker_image(marker_id: int, marker_size: int = 80) -> np.ndarray:
    aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    if hasattr(cv2.aruco, "generateImageMarker"):
        return cv2.aruco.generateImageMarker(aruco_dict, marker_id, marker_size)
    marker = np.zeros((marker_size, marker_size), dtype=np.uint8)
    cv2.aruco.drawMarker(aruco_dict, marker_id, marker_size, marker, 1)
    return marker


def _canvas_with_markers(markers: list[tuple[int, int, int]]) -> np.ndarray:
    canvas = np.full((220, 360), 255, dtype=np.uint8)
    for marker_id, x, y in markers:
        marker = _marker_image(marker_id)
        canvas[y : y + marker.shape[0], x : x + marker.shape[1]] = marker
    return cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)


def test_opencv_aruco_dependency_is_available():
    assert hasattr(cv2, "aruco")
    assert hasattr(cv2.aruco, "DICT_4X4_50")


def test_decode_image_rejects_bad_payload():
    with pytest.raises(ValueError):
        decode_image(b"not-an-image")


def test_detect_aruco_marker_from_generated_fixture():
    image = _canvas_with_markers([(4, 40, 40)])
    detections = detect_markers(image)
    assert len(detections) == 1
    detection = detections[0]
    assert detection.marker_id == "ARUCO_4X4_50_4"
    assert detection.class_name == "aruco_marker"
    assert detection.detector == "opencv-aruco-4x4-50"
    x1, y1, x2, y2 = detection.bbox_xyxy
    assert 0 <= x1 < x2 <= image.shape[1]
    assert 0 <= y1 < y2 <= image.shape[0]
    assert len(detection.corners_xy) == 4
    assert all(len(corner) == 2 for corner in detection.corners_xy)


def test_detect_aruco_markers_returns_empty_for_blank_frame():
    image = np.full((120, 160, 3), 255, dtype=np.uint8)
    assert detect_markers(image) == []


def test_detect_aruco_markers_are_sorted_by_marker_id():
    image = _canvas_with_markers([(9, 30, 40), (2, 200, 70)])
    detections = detect_markers(image)
    assert [detection.marker_id for detection in detections] == ["ARUCO_4X4_50_2", "ARUCO_4X4_50_9"]
