from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.pose_profiles import PoseProfileError, get_pose_profile, load_pose_profiles

ROOT = Path(__file__).resolve().parents[1]


def test_load_pose_profiles_reads_example_config():
    profiles = load_pose_profiles(
        str(ROOT / "config" / "perception" / "aruco_pose_profiles.example.json")
    )

    profile = profiles["tb3_1_lab_marker_7"]
    assert profile.source == "tb3_1_picam"
    assert profile.marker_id == "ARUCO_4X4_50_7"
    assert profile.marker_size_m == pytest.approx(0.08)
    assert profile.intrinsics.fx == pytest.approx(600.0)
    assert profile.applies_to(source="tb3_1_picam", marker_id="ARUCO_4X4_50_7")
    assert not profile.applies_to(source="tb3_2_picam", marker_id="ARUCO_4X4_50_7")


def test_get_pose_profile_rejects_unknown_profile(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text(json.dumps({"profiles": {}}), encoding="utf-8")

    with pytest.raises(PoseProfileError, match="unknown pose_profile"):
        get_pose_profile("missing", path=path)


def test_load_pose_profiles_rejects_invalid_camera_config(tmp_path):
    path = tmp_path / "profiles.json"
    path.write_text(
        json.dumps(
            {
                "profiles": {
                    "bad": {
                        "marker_size_m": 0.08,
                        "camera": {"fx": 0, "fy": 600, "cx": 80, "cy": 80},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(PoseProfileError, match="fx/fy must be positive"):
        load_pose_profiles(str(path))
