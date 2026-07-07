from __future__ import annotations

from dataclasses import dataclass
from math import atan2
from typing import Sequence

import cv2
import numpy as np


@dataclass(frozen=True)
class CameraIntrinsics:
    """Pinhole camera intrinsics for marker pose estimation."""

    fx: float
    fy: float
    cx: float
    cy: float
    dist_coeffs: tuple[float, ...] = ()

    @property
    def matrix(self) -> np.ndarray:
        return np.array(
            [[self.fx, 0.0, self.cx], [0.0, self.fy, self.cy], [0.0, 0.0, 1.0]],
            dtype=np.float64,
        )

    @property
    def distortion(self) -> np.ndarray:
        if not self.dist_coeffs:
            return np.zeros((5, 1), dtype=np.float64)
        return np.asarray(self.dist_coeffs, dtype=np.float64).reshape(-1, 1)


@dataclass(frozen=True)
class MarkerPose:
    """Marker pose in the OpenCV camera frame.

    OpenCV camera frame convention is x right, y down, z forward. For docking we
    use x as lateral error and z as forward distance. yaw_rad is the marker
    normal heading error around the camera vertical axis.
    """

    rvec: tuple[float, float, float]
    tvec: tuple[float, float, float]
    yaw_rad: float
    reprojection_error_px: float

    @property
    def lateral_m(self) -> float:
        return self.tvec[0]

    @property
    def vertical_m(self) -> float:
        return self.tvec[1]

    @property
    def distance_m(self) -> float:
        return self.tvec[2]


@dataclass(frozen=True)
class DockingTarget:
    """Desired camera-to-marker offset for final alignment."""

    distance_m: float
    lateral_offset_m: float = 0.0
    yaw_rad: float = 0.0


@dataclass(frozen=True)
class DockingError:
    lateral_error_m: float
    distance_error_m: float
    yaw_error_rad: float
    visible: bool = True


@dataclass(frozen=True)
class DockingTolerances:
    lateral_m: float = 0.04
    distance_m: float = 0.04
    yaw_rad: float = 0.08726646259971647  # 5 degrees


@dataclass(frozen=True)
class DockingGains:
    distance: float = 0.35
    lateral: float = 1.2
    yaw: float = 0.8


@dataclass(frozen=True)
class DockingLimits:
    max_linear_mps: float = 0.06
    max_angular_radps: float = 0.35


@dataclass(frozen=True)
class DockingCommand:
    linear_x_mps: float
    angular_z_radps: float
    reason: str


def marker_object_points(marker_size_m: float) -> np.ndarray:
    """Return object points matching OpenCV ArUco corner order.

    Corner order: top-left, top-right, bottom-right, bottom-left.
    """

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


def _as_corner_array(corners_xy: Sequence[Sequence[float]]) -> np.ndarray:
    corners = np.asarray(corners_xy, dtype=np.float64).reshape(4, 2)
    return corners


def estimate_marker_pose(
    corners_xy: Sequence[Sequence[float]],
    *,
    marker_size_m: float,
    intrinsics: CameraIntrinsics,
) -> MarkerPose:
    """Estimate marker pose from four 2D corners using solvePnP."""

    if marker_size_m <= 0:
        raise ValueError("marker_size_m must be positive")

    image_points = _as_corner_array(corners_xy)
    object_points = marker_object_points(marker_size_m)
    ok, rvec, tvec = cv2.solvePnP(
        object_points,
        image_points,
        intrinsics.matrix,
        intrinsics.distortion,
        flags=cv2.SOLVEPNP_IPPE_SQUARE,
    )
    if not ok:
        raise ValueError("marker pose estimation failed")

    rotation, _ = cv2.Rodrigues(rvec)
    marker_normal = rotation @ np.array([0.0, 0.0, 1.0], dtype=np.float64)
    # Planar marker pose can flip the normal direction depending on corner
    # convention/solver ambiguity. For docking, yaw should describe the marker
    # face alignment, so normalize the normal to face generally toward +Z in
    # the camera-forward convention before extracting yaw. This maps both
    # fronto-parallel normal directions to yaw ~= 0 instead of sometimes pi.
    if marker_normal[2] < 0:
        marker_normal = -marker_normal
    yaw_rad = float(atan2(marker_normal[0], marker_normal[2]))

    projected, _ = cv2.projectPoints(
        object_points,
        rvec,
        tvec,
        intrinsics.matrix,
        intrinsics.distortion,
    )
    projected = projected.reshape(4, 2)
    reprojection_error = float(np.linalg.norm(projected - image_points, axis=1).mean())

    return MarkerPose(
        rvec=tuple(float(v) for v in rvec.reshape(3)),
        tvec=tuple(float(v) for v in tvec.reshape(3)),
        yaw_rad=yaw_rad,
        reprojection_error_px=reprojection_error,
    )


def compute_docking_error(pose: MarkerPose, target: DockingTarget) -> DockingError:
    return DockingError(
        lateral_error_m=pose.lateral_m - target.lateral_offset_m,
        distance_error_m=pose.distance_m - target.distance_m,
        yaw_error_rad=pose.yaw_rad - target.yaw_rad,
        visible=True,
    )


def lost_marker_error() -> DockingError:
    return DockingError(0.0, 0.0, 0.0, visible=False)


def is_aligned(error: DockingError, tolerances: DockingTolerances) -> bool:
    return bool(
        error.visible
        and abs(error.lateral_error_m) <= tolerances.lateral_m
        and abs(error.distance_error_m) <= tolerances.distance_m
        and abs(error.yaw_error_rad) <= tolerances.yaw_rad
    )


def _clamp(value: float, limit: float) -> float:
    return max(-limit, min(limit, value))


def propose_docking_command(
    error: DockingError,
    *,
    tolerances: DockingTolerances = DockingTolerances(),
    gains: DockingGains = DockingGains(),
    limits: DockingLimits = DockingLimits(),
) -> DockingCommand:
    """Create a bounded differential-drive docking command proposal.

    This is pure math and does not publish to ROS. Positive camera x means the
    marker is to the right of image center; a differential-drive robot should
    rotate right, which is negative ROS angular_z.
    """

    if not error.visible:
        return DockingCommand(0.0, 0.0, "marker_lost")
    if is_aligned(error, tolerances):
        return DockingCommand(0.0, 0.0, "aligned")

    linear = _clamp(gains.distance * error.distance_error_m, limits.max_linear_mps)
    angular = -_clamp(
        gains.lateral * error.lateral_error_m + gains.yaw * error.yaw_error_rad,
        limits.max_angular_radps,
    )
    return DockingCommand(linear, angular, "tracking")


def stable_alignment_count(
    errors: Sequence[DockingError],
    tolerances: DockingTolerances,
) -> int:
    """Count consecutive aligned errors from the end of a history window."""

    count = 0
    for error in reversed(errors):
        if not is_aligned(error, tolerances):
            break
        count += 1
    return count
