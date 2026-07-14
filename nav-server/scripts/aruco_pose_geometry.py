#!/usr/bin/env python3
"""Pure OpenCV geometry used by the Nav-side ArUco detector."""
from __future__ import annotations

from math import atan2
from typing import Sequence

import cv2
import numpy as np


def marker_object_points(marker_size_m: float) -> np.ndarray:
    if marker_size_m <= 0.0:
        raise ValueError("marker_size_m must be positive")
    half = marker_size_m / 2.0
    return np.array(
        [
            [-half, half, 0.0],
            [half, half, 0.0],
            [half, -half, 0.0],
            [-half, -half, 0.0],
        ],
        dtype=np.float64,
    )


def estimate_marker_pose(
    corners_xy: Sequence[Sequence[float]],
    *,
    marker_size_m: float,
    camera_matrix: np.ndarray,
    dist_coeffs: np.ndarray,
) -> dict[str, float | list[float]]:
    """Return camera-frame lateral/forward offset and marker-normal yaw."""
    object_points = marker_object_points(marker_size_m)
    image_points = np.asarray(corners_xy, dtype=np.float64).reshape(4, 2)
    ok, rvec, tvec = cv2.solvePnP(
        object_points,
        image_points,
        np.asarray(camera_matrix, dtype=np.float64).reshape(3, 3),
        np.asarray(dist_coeffs, dtype=np.float64).reshape(-1, 1),
        flags=cv2.SOLVEPNP_IPPE_SQUARE,
    )
    if not ok:
        raise ValueError("marker pose estimation failed")

    rotation, _ = cv2.Rodrigues(rvec)
    marker_normal = rotation @ np.array([0.0, 0.0, 1.0], dtype=np.float64)
    if marker_normal[2] < 0.0:
        marker_normal = -marker_normal
    yaw_rad = float(atan2(marker_normal[0], marker_normal[2]))

    projected, _ = cv2.projectPoints(
        object_points,
        rvec,
        tvec,
        np.asarray(camera_matrix, dtype=np.float64).reshape(3, 3),
        np.asarray(dist_coeffs, dtype=np.float64).reshape(-1, 1),
    )
    reprojection_error = float(
        np.linalg.norm(projected.reshape(4, 2) - image_points, axis=1).mean()
    )
    translation = tvec.reshape(3)
    return {
        "lateral_offset_m": float(translation[0]),
        "vertical_offset_m": float(translation[1]),
        "forward_distance_m": float(translation[2]),
        "estimated_distance_m": float(np.linalg.norm(translation)),
        "marker_yaw_rad": yaw_rad,
        "reprojection_error_px": reprojection_error,
        "camera_tvec_m": [float(value) for value in translation],
        "camera_rvec_rad": [float(value) for value in rvec.reshape(3)],
    }
