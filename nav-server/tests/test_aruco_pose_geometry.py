from __future__ import annotations

import math

import numpy as np
import pytest

cv2 = pytest.importorskip("cv2", reason="Nav geometry tests require system/AI OpenCV")

from aruco_pose_geometry import estimate_marker_pose, marker_object_points  # noqa: E402

CAMERA_MATRIX = np.array(
    [[600.0, 0.0, 320.0], [0.0, 600.0, 240.0], [0.0, 0.0, 1.0]],
    dtype=np.float64,
)
DISTORTION = np.zeros(5, dtype=np.float64)


def _project_marker(*, marker_size_m: float, rvec, tvec) -> np.ndarray:
    image_points, _ = cv2.projectPoints(
        marker_object_points(marker_size_m),
        np.asarray(rvec, dtype=np.float64).reshape(3, 1),
        np.asarray(tvec, dtype=np.float64).reshape(3, 1),
        CAMERA_MATRIX,
        DISTORTION,
    )
    return image_points.reshape(4, 2)


def test_pose_recovers_lateral_forward_distance_and_yaw():
    yaw = math.radians(12.0)
    corners = _project_marker(
        marker_size_m=0.08,
        rvec=[0.0, yaw, 0.0],
        tvec=[0.05, 0.0, 0.55],
    )

    pose = estimate_marker_pose(
        corners,
        marker_size_m=0.08,
        camera_matrix=CAMERA_MATRIX,
        dist_coeffs=DISTORTION,
    )

    assert pose["lateral_offset_m"] == pytest.approx(0.05, abs=0.002)
    assert pose["forward_distance_m"] == pytest.approx(0.55, abs=0.002)
    assert pose["marker_yaw_rad"] == pytest.approx(yaw, abs=0.02)
    assert pose["reprojection_error_px"] < 0.001


def test_pose_rejects_non_positive_marker_size():
    with pytest.raises(ValueError, match="marker_size_m"):
        estimate_marker_pose(
            np.zeros((4, 2)),
            marker_size_m=0.0,
            camera_matrix=CAMERA_MATRIX,
            dist_coeffs=DISTORTION,
        )
