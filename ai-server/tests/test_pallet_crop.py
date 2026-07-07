from __future__ import annotations

import numpy as np
import pytest
from generated_fixtures import synthetic_pallet_workspace_fixture

from app.pallet_crop import (
    assess_part_readiness,
    detect_high_contrast_part_blobs,
    estimate_crop_first_part_budget,
    estimate_full_frame_part_budget,
    find_pallet_roi_candidates,
    normalize_pallet_crop,
    temporally_stable_count,
)


def test_synthetic_fixture_models_full_workspace_pallet_and_40mm_parts():
    fixture = synthetic_pallet_workspace_fixture()

    assert fixture.frame_size_px == (1920, 1080)
    assert fixture.workspace_bbox_xyxy == (420, 0, 1500, 1080)
    assert fixture.inspection_scene_width_mm == 1800.0
    assert fixture.mm_per_px == pytest.approx(1800 / 1080)
    assert fixture.pallet_size_mm == (90.0, 45.0)
    assert fixture.pallet_size_px[0] == pytest.approx(54.0)
    assert fixture.pallet_size_px[1] == pytest.approx(27.0)
    assert fixture.part_short_side_mm == 40.0
    assert fixture.part_short_side_px == pytest.approx(24.0, abs=1.0)
    assert len(fixture.part_centers_xy) == 2


@pytest.mark.parametrize("scene_width_mm", [450.0, 600.0, 900.0])
@pytest.mark.parametrize("part_short_side_mm", [5.0, 10.0, 15.0, 20.0])
def test_inspection_width_fixtures_scale_small_parts(scene_width_mm, part_short_side_mm):
    fixture = synthetic_pallet_workspace_fixture(
        inspection_scene_width_mm=scene_width_mm,
        part_short_side_mm=part_short_side_mm,
    )

    expected_mm_per_px = scene_width_mm / fixture.frame_size_px[1]
    assert fixture.workspace_size_mm == scene_width_mm
    assert fixture.inspection_scene_width_mm == scene_width_mm
    assert fixture.mm_per_px == pytest.approx(expected_mm_per_px)
    assert fixture.part_short_side_px == pytest.approx(
        part_short_side_mm / expected_mm_per_px,
        abs=1.5,
    )
    assert find_pallet_roi_candidates(fixture.image)


def test_no_fiducial_contour_candidate_and_normalized_crop_find_parts():
    fixture = synthetic_pallet_workspace_fixture(pallet_angle_deg=10.0)

    candidates = find_pallet_roi_candidates(fixture.image)

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate.aspect_ratio == pytest.approx(2.0, abs=0.25)
    assert candidate.short_side_px >= 24.0
    assert candidate.long_side_px == pytest.approx(54.0, abs=8.0)

    crop = normalize_pallet_crop(fixture.image, candidate)
    assert crop.image.shape[:2] == (180, 360)
    blobs = detect_high_contrast_part_blobs(crop.image)
    assert len(blobs) == 2


@pytest.mark.parametrize("pallet_angle_deg", [45.0, 135.0])
def test_normalized_crop_keeps_unique_corners_for_diagonal_pallets(pallet_angle_deg):
    fixture = synthetic_pallet_workspace_fixture(pallet_angle_deg=pallet_angle_deg)
    candidate = find_pallet_roi_candidates(fixture.image)[0]

    crop = normalize_pallet_crop(fixture.image, candidate)

    assert len(set(crop.source_box_xy)) == 4
    assert crop.image.any()
    assert len(detect_high_contrast_part_blobs(crop.image)) == 2


def test_full_frame_direct_detection_downgrades_while_crop_first_is_candidate():
    fixture = synthetic_pallet_workspace_fixture()
    candidate = find_pallet_roi_candidates(fixture.image)[0]
    crop = normalize_pallet_crop(fixture.image, candidate)
    part_count = len(detect_high_contrast_part_blobs(crop.image))

    full_budget = estimate_full_frame_part_budget(fixture.frame_size_px)
    full_readiness = assess_part_readiness(
        fixture.image,
        processing_mode="full_frame_direct",
        pixel_budget=full_budget,
        count_history=[part_count, part_count, part_count, part_count, part_count],
        expected_count=part_count,
    )

    assert full_budget.native_part_short_side_px == pytest.approx(24.0)
    assert full_budget.effective_part_short_side_px == pytest.approx(8.0)
    assert full_readiness.evidence_status == "CANDIDATE"
    assert full_readiness.reason == "insufficient_part_pixels"
    assert "insufficient_part_pixels" in full_readiness.failed_quality_gates
    assert not full_readiness.internal_detection_eligible

    crop_budget = estimate_crop_first_part_budget(candidate, frame_size_px=fixture.frame_size_px)
    crop_readiness = assess_part_readiness(
        crop.image,
        processing_mode="crop_first",
        pixel_budget=crop_budget,
        count_history=[part_count, part_count, part_count, part_count, part_count],
        expected_count=part_count,
    )

    assert crop_budget.native_part_short_side_px == pytest.approx(24.0)
    assert crop_budget.effective_part_short_side_px > 100.0
    assert crop_readiness.evidence_status == "CANDIDATE"
    assert crop_readiness.reason == "crop_first_candidate"
    assert crop_readiness.resolution_status == "marginal"
    assert crop_readiness.internal_detection_eligible
    assert crop_readiness.failed_quality_gates == ()


@pytest.mark.parametrize("part_short_side_mm", [5.0, 10.0, 15.0, 20.0])
def test_full_square_direct_detection_remains_downgraded_for_small_parts(
    part_short_side_mm,
):
    fixture = synthetic_pallet_workspace_fixture(part_short_side_mm=part_short_side_mm)
    full_budget = estimate_full_frame_part_budget(
        fixture.frame_size_px,
        part_short_side_mm=part_short_side_mm,
    )
    readiness = assess_part_readiness(
        fixture.image,
        processing_mode="full_frame_direct",
        pixel_budget=full_budget,
        count_history=[2, 2, 2, 2, 2],
        expected_count=2,
        confirm_when_eligible=True,
    )

    assert readiness.evidence_status == "CANDIDATE"
    assert readiness.reason == "insufficient_part_pixels"
    assert "insufficient_part_pixels" in readiness.failed_quality_gates
    assert not readiness.internal_detection_eligible


@pytest.mark.parametrize("scene_width_mm", [450.0, 600.0, 900.0])
@pytest.mark.parametrize("part_short_side_mm", [5.0, 10.0, 15.0, 20.0])
def test_inspection_width_crop_first_requires_all_quality_gates(
    scene_width_mm,
    part_short_side_mm,
):
    fixture = synthetic_pallet_workspace_fixture(
        inspection_scene_width_mm=scene_width_mm,
        part_short_side_mm=part_short_side_mm,
    )
    candidate = find_pallet_roi_candidates(fixture.image)[0]
    crop = normalize_pallet_crop(fixture.image, candidate)
    crop_budget = estimate_crop_first_part_budget(
        candidate,
        workspace_size_mm=scene_width_mm,
        frame_size_px=fixture.frame_size_px,
        part_short_side_mm=part_short_side_mm,
    )

    readiness = assess_part_readiness(
        crop.image,
        processing_mode="crop_first",
        pixel_budget=crop_budget,
        count_history=[2, 2, 2, 2, 2],
        expected_count=2,
        confirm_when_eligible=True,
    )

    if crop_budget.native_part_short_side_px >= 20.0:
        assert readiness.evidence_status == "CONFIRMED"
        assert readiness.internal_detection_eligible
        assert readiness.reason == "crop_first_candidate"
        assert readiness.failed_quality_gates == ()
    else:
        assert readiness.evidence_status == "CANDIDATE"
        assert not readiness.internal_detection_eligible
        assert "insufficient_part_pixels" in readiness.failed_quality_gates


def test_quality_gates_downgrade_low_contrast_and_unstable_counts():
    fixture = synthetic_pallet_workspace_fixture()
    candidate = find_pallet_roi_candidates(fixture.image)[0]
    crop = normalize_pallet_crop(fixture.image, candidate)
    crop_budget = estimate_crop_first_part_budget(candidate, frame_size_px=fixture.frame_size_px)

    low_contrast_crop = np.full((180, 360, 3), 70, dtype=np.uint8)
    low_contrast_crop[40:140, 80:280] = 76

    contrast_readiness = assess_part_readiness(
        low_contrast_crop,
        processing_mode="crop_first",
        pixel_budget=crop_budget,
        count_history=[2, 2, 2, 2, 2],
        expected_count=2,
    )

    assert contrast_readiness.reason == "low_contrast"
    assert "low_contrast" in contrast_readiness.failed_quality_gates
    assert contrast_readiness.contrast_quality == "low_contrast"

    unstable_readiness = assess_part_readiness(
        crop.image,
        processing_mode="crop_first",
        pixel_budget=crop_budget,
        count_history=[2, 1, 2, 1, 3],
        expected_count=2,
    )

    assert unstable_readiness.reason == "unstable_part_count"
    assert "unstable_part_count" in unstable_readiness.failed_quality_gates
    assert unstable_readiness.temporal_stability == "unstable_part_count"
    assert temporally_stable_count([2, 2, 1, 2, 2], expected_count=2)
    assert not temporally_stable_count([2, 1, 2, 1, 3], expected_count=2)


def test_quality_gates_downgrade_exposure_lighting_and_white_balance():
    fixture = synthetic_pallet_workspace_fixture(
        inspection_scene_width_mm=600.0,
        part_short_side_mm=20.0,
    )
    candidate = find_pallet_roi_candidates(fixture.image)[0]
    crop = normalize_pallet_crop(fixture.image, candidate)
    crop_budget = estimate_crop_first_part_budget(
        candidate,
        workspace_size_mm=600.0,
        frame_size_px=fixture.frame_size_px,
        part_short_side_mm=20.0,
    )

    overexposed = np.full(crop.image.shape, 230, dtype=np.uint8)
    overexposed[40:140, 80:280] = 255
    overexposed_readiness = assess_part_readiness(
        overexposed,
        processing_mode="crop_first",
        pixel_budget=crop_budget,
        count_history=[2, 2, 2, 2, 2],
        expected_count=2,
    )
    assert "bad_exposure" in overexposed_readiness.failed_quality_gates
    assert overexposed_readiness.exposure_quality == "bad_exposure"

    flat_lighting = np.full(crop.image.shape, 70, dtype=np.uint8)
    flat_lighting[80:100, 160:200] = 74
    flat_readiness = assess_part_readiness(
        flat_lighting,
        processing_mode="crop_first",
        pixel_budget=crop_budget,
        count_history=[2, 2, 2, 2, 2],
        expected_count=2,
    )
    assert "poor_lighting" in flat_readiness.failed_quality_gates
    assert flat_readiness.lighting_quality == "poor_lighting"

    blue_cast = synthetic_pallet_workspace_fixture(
        inspection_scene_width_mm=600.0,
        part_short_side_mm=20.0,
        white_balance_bgr=(2.5, 0.6, 0.6),
    )
    blue_candidate = find_pallet_roi_candidates(blue_cast.image)[0]
    blue_crop = normalize_pallet_crop(blue_cast.image, blue_candidate)
    blue_readiness = assess_part_readiness(
        blue_crop.image,
        processing_mode="crop_first",
        pixel_budget=crop_budget,
        count_history=[2, 2, 2, 2, 2],
        expected_count=2,
    )
    assert "bad_white_balance" in blue_readiness.failed_quality_gates
    assert blue_readiness.white_balance_quality == "bad_white_balance"


def test_missing_pallet_contour_returns_no_candidates():
    blank = np.full((1080, 1920, 3), 230, dtype=np.uint8)

    assert find_pallet_roi_candidates(blank) == ()
