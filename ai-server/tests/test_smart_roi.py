from __future__ import annotations

import numpy as np

from app.smart_roi import (
    crop_smart_roi,
    estimate_object_pixel_budget,
    event_for_roi_overlay,
    parse_normalized_bbox,
    select_smart_roi,
    translate_bbox_from_roi_to_full,
    translate_detector_result_from_roi_to_full,
)
from app.vision_interfaces import DetectionBox


def test_smart_roi_hint_crops_before_resize_and_reports_pixel_gain():
    image = np.full((2160, 3840, 3), 180, dtype=np.uint8)

    selection = select_smart_roi(
        image,
        view_id="lift_roi",
        roi_hint_normalized=(0.35, 0.30, 0.65, 0.70),
        model_input_size_px=(640, 640),
        margin_ratio=0.0,
    )
    crop = crop_smart_roi(image, selection)

    assert selection.selection_source == "normalized_hint"
    assert selection.frame_size_px == (3840, 2160)
    assert selection.crop_size_px == (1152, 864)
    assert crop.shape[:2] == (864, 1152)
    assert selection.pixel_gain_vs_full_resize > 3.0


def test_smart_roi_uses_pallet_like_contour_when_no_hint_exists():
    image = np.full((1080, 1920, 3), 220, dtype=np.uint8)
    image[420:620, 700:1100] = 40

    selection = select_smart_roi(
        image,
        view_id="pallet_zoom",
        model_input_size_px=(640, 640),
        margin_ratio=0.1,
    )

    assert selection.selection_source == "pallet_contour"
    x1, y1, x2, y2 = selection.bbox_xyxy
    assert x1 <= 700 < 1100 <= x2
    assert y1 <= 420 < 620 <= y2
    assert selection.crop_size_px[0] < image.shape[1]


def test_roi_coordinate_mapping_round_trips_detector_boxes_for_full_frame_events():
    image = np.zeros((100, 200, 3), dtype=np.uint8)
    selection = select_smart_roi(
        image,
        view_id="lift_roi",
        roi_hint_normalized=parse_normalized_bbox("0.25,0.2,0.75,0.8"),
        margin_ratio=0.0,
        min_side_px=8,
    )

    assert translate_bbox_from_roi_to_full((10, 20, 30, 40), selection) == (
        60.0,
        40.0,
        80.0,
        60.0,
    )
    mapped = translate_detector_result_from_roi_to_full(
        DetectionBox(class_name="box", bbox_xyxy=(10, 20, 30, 40), confidence=0.8),
        selection,
    )
    assert mapped.bbox_xyxy == (60.0, 40.0, 80.0, 60.0)
    assert mapped.detector.endswith(":lift_roi")

    roi_event = event_for_roi_overlay(
        {"bbox_xyxy": [60.0, 40.0, 80.0, 60.0], "metadata": {}},
        selection,
    )
    assert roi_event is not None
    assert roi_event["bbox_xyxy"] == [10.0, 20.0, 30.0, 40.0]


def test_pixel_budget_estimator_marks_four_cm_target_below_low_res_stream_budget():
    estimate = estimate_object_pixel_budget(
        object_size_m=0.04,
        visible_scene_width_m=4.0,
        frame_width_px=1280,
        pixel_gain_vs_full_resize=1.0,
        min_object_px=16.0,
    )

    assert estimate["full_frame_object_px"] == 12.8
    assert estimate["effective_object_px"] == 12.8
    assert estimate["meets_min_object_px"] is False


def test_pixel_budget_estimator_reports_crop_first_gain_as_enough_for_review():
    estimate = estimate_object_pixel_budget(
        object_size_m=0.04,
        visible_scene_width_m=4.0,
        frame_width_px=1920,
        pixel_gain_vs_full_resize=3.0,
        min_object_px=16.0,
    )

    assert estimate["full_frame_object_px"] == 19.2
    assert estimate["effective_object_px"] == 57.6
    assert estimate["meets_min_object_px"] is True
