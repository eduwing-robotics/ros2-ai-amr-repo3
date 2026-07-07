from __future__ import annotations

import math

import cv2
import numpy as np

from app.docking import (
    CameraIntrinsics,
    DockingError,
    DockingGains,
    DockingLimits,
    DockingTarget,
    DockingTolerances,
    compute_docking_error,
    estimate_marker_pose,
    is_aligned,
    lost_marker_error,
    marker_object_points,
    propose_docking_command,
    stable_alignment_count,
)


def _intrinsics() -> CameraIntrinsics:
    return CameraIntrinsics(fx=600.0, fy=600.0, cx=320.0, cy=240.0)


def _project_marker(*, marker_size_m: float, rvec, tvec) -> np.ndarray:
    image_points, _ = cv2.projectPoints(
        marker_object_points(marker_size_m),
        np.asarray(rvec, dtype=np.float64).reshape(3, 1),
        np.asarray(tvec, dtype=np.float64).reshape(3, 1),
        _intrinsics().matrix,
        _intrinsics().distortion,
    )
    return image_points.reshape(4, 2)


def test_estimate_marker_pose_recovers_synthetic_lateral_and_distance():
    corners = _project_marker(marker_size_m=0.08, rvec=[0.0, 0.0, 0.0], tvec=[0.05, 0.0, 0.55])

    pose = estimate_marker_pose(corners, marker_size_m=0.08, intrinsics=_intrinsics())

    assert pose.lateral_m == pytest_approx(0.05, abs=0.002)
    assert pose.distance_m == pytest_approx(0.55, abs=0.002)
    assert pose.yaw_rad == pytest_approx(0.0, abs=0.01)
    assert pose.reprojection_error_px < 0.001


def test_estimate_marker_pose_recovers_yaw_from_marker_normal():
    yaw = math.radians(12.0)
    rvec = np.array([0.0, yaw, 0.0], dtype=np.float64)
    corners = _project_marker(marker_size_m=0.08, rvec=rvec, tvec=[0.0, 0.0, 0.6])

    pose = estimate_marker_pose(corners, marker_size_m=0.08, intrinsics=_intrinsics())

    assert pose.yaw_rad == pytest_approx(yaw, abs=0.02)


def test_compute_docking_error_against_target_offset():
    corners = _project_marker(marker_size_m=0.08, rvec=[0.0, 0.0, 0.0], tvec=[0.03, 0.0, 0.62])
    pose = estimate_marker_pose(corners, marker_size_m=0.08, intrinsics=_intrinsics())

    error = compute_docking_error(pose, DockingTarget(distance_m=0.50, lateral_offset_m=0.01))

    assert error.lateral_error_m == pytest_approx(0.02, abs=0.002)
    assert error.distance_error_m == pytest_approx(0.12, abs=0.002)


def test_propose_command_stops_when_aligned_or_marker_lost():
    tolerances = DockingTolerances(lateral_m=0.03, distance_m=0.03, yaw_rad=0.05)

    aligned_command = propose_docking_command(
        DockingError(0.01, -0.02, 0.02), tolerances=tolerances
    )
    lost_command = propose_docking_command(lost_marker_error(), tolerances=tolerances)

    assert aligned_command.linear_x_mps == 0.0
    assert aligned_command.angular_z_radps == 0.0
    assert aligned_command.reason == "aligned"
    assert lost_command.reason == "marker_lost"


def test_propose_command_turns_right_when_marker_is_right_of_camera_center():
    command = propose_docking_command(
        DockingError(lateral_error_m=0.10, distance_error_m=0.20, yaw_error_rad=0.0),
        gains=DockingGains(distance=1.0, lateral=1.0, yaw=0.0),
        limits=DockingLimits(max_linear_mps=0.05, max_angular_radps=0.20),
    )

    assert command.reason == "tracking"
    assert command.linear_x_mps == 0.05
    assert command.angular_z_radps < 0.0
    assert abs(command.angular_z_radps) <= 0.20


def test_stable_alignment_count_counts_only_trailing_aligned_errors():
    tolerances = DockingTolerances(lateral_m=0.03, distance_m=0.03, yaw_rad=0.05)
    errors = [
        DockingError(0.01, 0.01, 0.01),
        DockingError(0.10, 0.01, 0.01),
        DockingError(0.02, 0.01, 0.01),
        DockingError(0.01, 0.02, 0.01),
    ]

    assert stable_alignment_count(errors, tolerances) == 2
    assert is_aligned(errors[-1], tolerances)


def pytest_approx(*args, **kwargs):
    import pytest

    return pytest.approx(*args, **kwargs)
