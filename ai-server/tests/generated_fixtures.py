from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np


@dataclass(frozen=True)
class SyntheticPalletFixture:
    image: np.ndarray
    frame_size_px: tuple[int, int]
    workspace_bbox_xyxy: tuple[int, int, int, int]
    workspace_size_mm: float
    inspection_scene_width_mm: float
    mm_per_px: float
    pallet_box_xy: tuple[tuple[float, float], ...]
    pallet_size_mm: tuple[float, float]
    pallet_size_px: tuple[float, float]
    part_short_side_mm: float
    part_short_side_px: float
    part_centers_xy: tuple[tuple[float, float], ...]


def png_bytes(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".png", image)
    assert ok
    return encoded.tobytes()


def blank_png_bytes(*, width: int = 64, height: int = 64) -> bytes:
    return png_bytes(np.full((height, width, 3), 255, dtype=np.uint8))


def aruco_png_bytes(marker_id: int = 7, *, marker_size: int = 96, padding: int = 32) -> bytes:
    """Generate a deterministic ArUco fixture image entirely in test code."""

    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    marker = cv2.aruco.generateImageMarker(dictionary, marker_id, marker_size)
    canvas_size = marker_size + (padding * 2)
    canvas = np.full((canvas_size, canvas_size), 255, dtype=np.uint8)
    canvas[padding : padding + marker_size, padding : padding + marker_size] = marker
    return png_bytes(cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR))


def multi_aruco_png_bytes(marker_ids: tuple[int, int] = (4, 5)) -> bytes:
    """Generate a deterministic two-marker ArUco fixture with non-overlapping boxes."""

    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    canvas = np.full((160, 304), 255, dtype=np.uint8)
    for index, marker_id in enumerate(marker_ids):
        marker = cv2.aruco.generateImageMarker(dictionary, marker_id, 96)
        left = 32 + (index * 144)
        canvas[32:128, left : left + 96] = marker
    return png_bytes(cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR))


def synthetic_pallet_workspace_fixture(
    *,
    frame_size_px: tuple[int, int] = (1920, 1080),
    workspace_size_mm: float = 1800.0,
    inspection_scene_width_mm: float | None = None,
    pallet_size_mm: tuple[float, float] = (90.0, 45.0),
    part_short_side_mm: float = 40.0,
    part_count: int = 2,
    pallet_angle_deg: float = 0.0,
    exposure_offset: float = 0.0,
    white_balance_bgr: tuple[float, float, float] = (1.0, 1.0, 1.0),
) -> SyntheticPalletFixture:
    """Generate a D435-like full frame with a centered 1.8m square workspace."""

    frame_width, frame_height = frame_size_px
    if frame_width <= 0 or frame_height <= 0:
        raise ValueError("frame_size_px must be positive")
    if inspection_scene_width_mm is not None:
        workspace_size_mm = float(inspection_scene_width_mm)
    if workspace_size_mm <= 0:
        raise ValueError("workspace_size_mm must be positive")
    if part_count not in {0, 1, 2}:
        raise ValueError("part_count must be 0, 1, or 2 for this compact pallet fixture")
    if len(white_balance_bgr) != 3 or any(value <= 0 for value in white_balance_bgr):
        raise ValueError("white_balance_bgr must contain three positive multipliers")

    mm_per_px = workspace_size_mm / frame_height
    workspace_width_px = round(workspace_size_mm / mm_per_px)
    workspace_left = int(round((frame_width - workspace_width_px) / 2))
    workspace_bbox = (workspace_left, 0, workspace_left + workspace_width_px, frame_height)

    image = np.full((frame_height, frame_width, 3), (236, 236, 236), dtype=np.uint8)
    x1, y1, x2, y2 = workspace_bbox
    image[y1:y2, x1:x2] = (222, 222, 222)

    center = np.asarray((frame_width / 2.0, frame_height / 2.0), dtype=np.float32)
    half_long_mm = pallet_size_mm[0] / 2.0
    half_short_mm = pallet_size_mm[1] / 2.0
    angle_rad = np.deg2rad(pallet_angle_deg)
    rotation = np.asarray(
        [
            [np.cos(angle_rad), -np.sin(angle_rad)],
            [np.sin(angle_rad), np.cos(angle_rad)],
        ],
        dtype=np.float32,
    )

    def image_point(local_mm: tuple[float, float]) -> tuple[float, float]:
        local_px = np.asarray(local_mm, dtype=np.float32) / float(mm_per_px)
        point = center + rotation @ local_px
        return (float(point[0]), float(point[1]))

    pallet_local = (
        (-half_long_mm, -half_short_mm),
        (half_long_mm, -half_short_mm),
        (half_long_mm, half_short_mm),
        (-half_long_mm, half_short_mm),
    )
    pallet_box = tuple(image_point(point) for point in pallet_local)
    pallet_poly = np.round(np.asarray(pallet_box, dtype=np.float32)).astype(np.int32)
    cv2.fillPoly(image, [pallet_poly.reshape((-1, 1, 2))], (58, 58, 58))
    cv2.polylines(image, [pallet_poly.reshape((-1, 1, 2))], True, (22, 22, 22), 1)

    part_radius_px = int(round((part_short_side_mm / mm_per_px) / 2.0))
    if part_count == 0:
        part_offsets_mm: tuple[tuple[float, float], ...] = ()
    elif part_count == 1:
        part_offsets_mm = ((0.0, 0.0),)
    else:
        part_offsets_mm = ((-22.5, 0.0), (22.5, 0.0))
    colors = ((42, 84, 230), (230, 80, 48))
    part_centers = tuple(image_point(point) for point in part_offsets_mm)
    for index, part_center in enumerate(part_centers):
        cv2.circle(
            image,
            (int(round(part_center[0])), int(round(part_center[1]))),
            part_radius_px,
            colors[index % len(colors)],
            -1,
            lineType=cv2.LINE_AA,
        )

    if exposure_offset or white_balance_bgr != (1.0, 1.0, 1.0):
        adjusted = image.astype(np.float32)
        adjusted *= np.asarray(white_balance_bgr, dtype=np.float32).reshape(1, 1, 3)
        adjusted += float(exposure_offset)
        image = np.clip(adjusted, 0, 255).astype(np.uint8)

    return SyntheticPalletFixture(
        image=image,
        frame_size_px=frame_size_px,
        workspace_bbox_xyxy=workspace_bbox,
        workspace_size_mm=workspace_size_mm,
        inspection_scene_width_mm=float(workspace_size_mm),
        mm_per_px=float(mm_per_px),
        pallet_box_xy=pallet_box,
        pallet_size_mm=pallet_size_mm,
        pallet_size_px=(pallet_size_mm[0] / mm_per_px, pallet_size_mm[1] / mm_per_px),
        part_short_side_mm=part_short_side_mm,
        part_short_side_px=float(part_radius_px * 2),
        part_centers_xy=part_centers,
    )
