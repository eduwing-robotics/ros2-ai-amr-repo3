from __future__ import annotations

import json

import numpy as np
import pytest
from camera_calibration import load_calibration, scale_camera_matrix


def test_load_and_scale_calibration(tmp_path):
    path = tmp_path / "camera.json"
    path.write_text(
        json.dumps(
            {
                "image_width": 320,
                "image_height": 240,
                "camera_matrix": [[300, 0, 160], [0, 301, 120], [0, 0, 1]],
                "dist_coeffs": [0.1, -0.2, 0, 0, 0.05],
            }
        ),
        encoding="utf-8",
    )
    matrix, distortion, metadata = load_calibration(str(path))
    scaled = scale_camera_matrix(
        matrix,
        calibrated_width=metadata["image_width"],
        calibrated_height=metadata["image_height"],
        image_width=640,
        image_height=480,
    )

    assert distortion.shape == (5,)
    assert scaled[0, 0] == pytest.approx(600.0)
    assert scaled[1, 1] == pytest.approx(602.0)
    assert scaled[0, 2] == pytest.approx(320.0)


def test_scale_rejects_changed_aspect_ratio():
    with pytest.raises(ValueError, match="aspect ratio"):
        scale_camera_matrix(
            np.eye(3),
            calibrated_width=320,
            calibrated_height=240,
            image_width=640,
            image_height=360,
        )
