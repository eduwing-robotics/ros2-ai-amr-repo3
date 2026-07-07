from __future__ import annotations

import numpy as np
import pytest

from app.lift_roi import (
    DetectionCandidate,
    RoiPolygon,
    candidate_roi_overlap_ratio,
    evaluate_lift_load,
    stable_count,
    verify_dropoff,
    verify_pickup,
)

IMAGE_SIZE = (200, 160)
LIFT_ROI = RoiPolygon(
    roi_id="LIFT_ROI",
    points_xy=((50.0, 40.0), (150.0, 40.0), (150.0, 120.0), (50.0, 120.0)),
)


def test_evaluate_lift_load_counts_boxes_inside_roi_and_rejects_outside_items():
    candidates = [
        DetectionCandidate("box", (60.0, 50.0, 90.0, 90.0), 0.9, track_id="a"),
        DetectionCandidate("pallet", (100.0, 60.0, 140.0, 110.0), 0.8, track_id="b"),
        DetectionCandidate("box", (155.0, 60.0, 190.0, 100.0), 0.9, track_id="outside"),
        DetectionCandidate("person", (70.0, 60.0, 120.0, 130.0), 0.9, track_id="person"),
    ]

    result = evaluate_lift_load(candidates, LIFT_ROI, image_size=IMAGE_SIZE)

    assert result.count == 2
    assert [item.candidate.track_id for item in result.accepted] == ["a", "b"]
    assert {item.reason for item in result.rejected} == {"center_outside_roi", "class_not_load"}


def test_evaluate_lift_load_rejects_partial_bbox_with_insufficient_overlap():
    candidates = [DetectionCandidate("box", (20.0, 60.0, 120.0, 100.0), 0.9)]

    result = evaluate_lift_load(
        candidates,
        LIFT_ROI,
        image_size=IMAGE_SIZE,
        min_overlap_ratio=0.75,
    )

    assert result.count == 0
    assert result.rejected[0].reason == "insufficient_roi_overlap"
    assert result.rejected[0].center_inside_roi is True


def test_mask_overlap_is_used_when_instance_mask_is_available():
    mask = np.zeros((IMAGE_SIZE[1], IMAGE_SIZE[0]), dtype=bool)
    mask[60:100, 80:130] = True
    candidate = DetectionCandidate("box", (10.0, 10.0, 190.0, 150.0), 0.9, mask=mask)

    overlap = candidate_roi_overlap_ratio(candidate, LIFT_ROI, image_size=IMAGE_SIZE)
    result = evaluate_lift_load([candidate], LIFT_ROI, image_size=IMAGE_SIZE)

    assert overlap == pytest.approx(1.0)
    assert result.count == 1


def test_mask_overlap_can_reject_bbox_that_is_visually_mostly_outside_lift():
    mask = np.zeros((IMAGE_SIZE[1], IMAGE_SIZE[0]), dtype=bool)
    mask[60:100, 20:70] = True
    candidate = DetectionCandidate("box", (60.0, 60.0, 130.0, 110.0), 0.9, mask=mask)

    result = evaluate_lift_load([candidate], LIFT_ROI, image_size=IMAGE_SIZE, min_overlap_ratio=0.6)

    assert result.count == 0
    assert result.rejected[0].reason == "insufficient_roi_overlap"


def test_stable_count_requires_expected_count_for_required_window():
    assert stable_count([0, 1, 2, 2, 2], required_frames=3, expected_count=2)
    assert not stable_count([0, 1, 2, 1, 2], required_frames=3, expected_count=2)
    assert stable_count([1, 2, 2, 2], required_frames=2)
    with pytest.raises(ValueError):
        stable_count([1], required_frames=0)


def test_verify_pickup_combines_lift_sensor_count_stability_and_drop_check():
    evaluation = evaluate_lift_load(
        [DetectionCandidate("box", (60.0, 50.0, 90.0, 90.0), 0.9)],
        LIFT_ROI,
        image_size=IMAGE_SIZE,
    )

    assert (
        verify_pickup(
            lift_up_sensor=True,
            load_evaluation=evaluation,
            expected_count=1,
            count_stable=True,
        ).status
        == "CONFIRMED"
    )
    assert (
        verify_pickup(
            lift_up_sensor=False,
            load_evaluation=evaluation,
            expected_count=1,
            count_stable=True,
        ).reason
        == "lift_up_sensor_false"
    )
    assert (
        verify_pickup(
            lift_up_sensor=True,
            load_evaluation=evaluation,
            expected_count=2,
            count_stable=True,
        ).reason
        == "load_count_mismatch"
    )
    assert (
        verify_pickup(
            lift_up_sensor=True,
            load_evaluation=evaluation,
            expected_count=1,
            count_stable=True,
            dropped_item_count=1,
        ).reason
        == "dropped_item_candidate_present"
    )


def test_verify_dropoff_supports_mvp_sequence_only_and_optional_vision_checks():
    empty_lift = evaluate_lift_load([], LIFT_ROI, image_size=IMAGE_SIZE)
    occupied_target = evaluate_lift_load(
        [DetectionCandidate("box", (60.0, 50.0, 90.0, 90.0), 0.9)],
        LIFT_ROI,
        image_size=IMAGE_SIZE,
    )

    assert (
        verify_dropoff(lift_down_complete=True, backoff_complete=True).reason
        == "dropoff_sequence_verified"
    )
    assert verify_dropoff(lift_down_complete=False, backoff_complete=True).status == "FAILED"
    assert (
        verify_dropoff(
            lift_down_complete=True,
            backoff_complete=True,
            lift_evaluation=empty_lift,
            target_evaluation=occupied_target,
        ).reason
        == "dropoff_vision_verified"
    )
    assert (
        verify_dropoff(
            lift_down_complete=True,
            backoff_complete=True,
            lift_evaluation=occupied_target,
        ).reason
        == "lift_roi_not_empty"
    )
