#!/usr/bin/env python3
"""Camera calibration helpers shared by the CLI and ArUco detector."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Tuple
import cv2
import numpy as np

def load_calibration(path: str) -> Tuple[np.ndarray, np.ndarray, Dict[str, Any]]:
    source = Path(path).expanduser()
    data = json.loads(source.read_text(encoding="utf-8"))
    matrix = np.asarray(data.get("camera_matrix"), dtype=np.float64)
    distortion = np.asarray(data.get("dist_coeffs"), dtype=np.float64).reshape(-1)
    if matrix.shape != (3, 3): raise ValueError(f"camera_matrix must be 3x3: {source}")
    if distortion.size not in (4, 5, 8, 12, 14): raise ValueError(f"invalid dist_coeffs: {source}")
    if not np.isfinite(matrix).all() or not np.isfinite(distortion).all(): raise ValueError(f"calibration contains non-finite values: {source}")
    return matrix, distortion, data

def calibrate_camera(object_points: Iterable[np.ndarray], image_points: Iterable[np.ndarray], image_size: Tuple[int, int]) -> Dict[str, Any]:
    objects, images = list(object_points), list(image_points)
    if len(objects) < 8 or len(objects) != len(images): raise ValueError("at least 8 matched calibration views are required")
    rms, matrix, distortion, rvecs, tvecs = cv2.calibrateCamera(objects, images, image_size, None, None)
    errors = []
    for obj, img, rvec, tvec in zip(objects, images, rvecs, tvecs):
        projected, _ = cv2.projectPoints(obj, rvec, tvec, matrix, distortion)
        errors.append(float(cv2.norm(img, projected, cv2.NORM_L2) / len(projected)))
    return {"format_version": 1, "image_width": image_size[0], "image_height": image_size[1], "camera_matrix": matrix.tolist(), "dist_coeffs": distortion.reshape(-1).tolist(), "rms_reprojection_error_px": float(rms), "mean_reprojection_error_px": float(np.mean(errors)), "max_view_reprojection_error_px": float(np.max(errors)), "sample_count": len(images)}

def save_calibration(path: str, calibration: Dict[str, Any]) -> None:
    destination = Path(path).expanduser(); destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(calibration, indent=2) + "\n", encoding="utf-8")
