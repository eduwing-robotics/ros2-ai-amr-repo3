#!/usr/bin/env python3
"""Load robot-specific camera intrinsics for Nav ArUco pose estimation."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np


def load_calibration(path: str) -> tuple[np.ndarray, np.ndarray, dict[str, Any]]:
    source = Path(path).expanduser()
    data = json.loads(source.read_text(encoding="utf-8"))
    matrix = np.asarray(data.get("camera_matrix"), dtype=np.float64)
    distortion = np.asarray(data.get("dist_coeffs"), dtype=np.float64).reshape(-1)
    if matrix.shape != (3, 3):
        raise ValueError(f"camera_matrix must be 3x3: {source}")
    if distortion.size not in (4, 5, 8, 12, 14):
        raise ValueError(f"invalid dist_coeffs: {source}")
    if not np.isfinite(matrix).all() or not np.isfinite(distortion).all():
        raise ValueError(f"calibration contains non-finite values: {source}")
    width = int(data.get("image_width") or 0)
    height = int(data.get("image_height") or 0)
    if width <= 0 or height <= 0:
        raise ValueError(f"image_width/image_height must be positive: {source}")
    return matrix, distortion, data


def scale_camera_matrix(
    matrix: np.ndarray,
    *,
    calibrated_width: int,
    calibrated_height: int,
    image_width: int,
    image_height: int,
) -> np.ndarray:
    """Scale intrinsics when runtime resolution preserves the calibrated aspect ratio."""
    if min(calibrated_width, calibrated_height, image_width, image_height) <= 0:
        raise ValueError("camera dimensions must be positive")
    calibrated_ratio = calibrated_width / calibrated_height
    image_ratio = image_width / image_height
    if abs(calibrated_ratio - image_ratio) > 0.01:
        raise ValueError(
            "runtime image aspect ratio differs from camera calibration: "
            f"{image_width}x{image_height} vs {calibrated_width}x{calibrated_height}"
        )
    scaled = np.asarray(matrix, dtype=np.float64).copy()
    scale_x = image_width / calibrated_width
    scale_y = image_height / calibrated_height
    scaled[0, 0] *= scale_x
    scaled[0, 2] *= scale_x
    scaled[1, 1] *= scale_y
    scaled[1, 2] *= scale_y
    return scaled
