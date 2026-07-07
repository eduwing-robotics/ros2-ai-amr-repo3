from __future__ import annotations

import numpy as np
import pytest

from app.lift_roi import RoiPolygon, evaluate_lift_load
from app.vision_interfaces import (
    DetectionBox,
    InstanceMask,
    StaticCandidateProvider,
    mask_area_px,
    mask_from_polygon,
    normalize_bbox_xyxy,
    to_lift_roi_candidates,
    validate_confidence,
)

IMAGE_SIZE = (200, 160)
LIFT_ROI = RoiPolygon(
    roi_id="LIFT_ROI",
    points_xy=((50.0, 40.0), (150.0, 40.0), (150.0, 120.0), (50.0, 120.0)),
)


def test_static_candidate_provider_exposes_bbox_and_instance_mask_seam():
    mask = np.zeros((IMAGE_SIZE[1], IMAGE_SIZE[0]), dtype=bool)
    mask[60:100, 80:130] = True
    provider = StaticCandidateProvider(
        (
            DetectionBox("box", (60.0, 50.0, 90.0, 90.0), 0.91, track_id="bbox-1"),
            InstanceMask(
                "pallet",
                (10.0, 10.0, 190.0, 150.0),
                0.82,
                mask,
                track_id="mask-1",
            ),
        )
    )

    results = tuple(provider.detect(np.zeros((160, 200, 3), dtype=np.uint8)))
    evaluation = evaluate_lift_load(
        to_lift_roi_candidates(results),
        LIFT_ROI,
        image_size=IMAGE_SIZE,
    )

    assert evaluation.count == 2
    assert [item.candidate.track_id for item in evaluation.accepted] == ["bbox-1", "mask-1"]
    assert mask_area_px(results[1]) == 2000


def test_mask_polygon_can_be_rasterized_for_synthetic_segmenter_results():
    mask = mask_from_polygon(
        ((80.0, 60.0), (130.0, 60.0), (130.0, 100.0), (80.0, 100.0)),
        image_size=IMAGE_SIZE,
    )
    candidate = InstanceMask("box", (0.0, 0.0, 199.0, 159.0), 0.9, mask)

    evaluation = evaluate_lift_load(
        to_lift_roi_candidates([candidate]),
        LIFT_ROI,
        image_size=IMAGE_SIZE,
        min_overlap_ratio=0.95,
    )

    assert evaluation.count == 1
    assert evaluation.accepted[0].overlap_ratio == pytest.approx(1.0)


def test_interface_rejects_invalid_bbox_and_confidence_before_provider_boundary():
    with pytest.raises(ValueError, match="x1 < x2"):
        normalize_bbox_xyxy((10, 10, 5, 20))
    with pytest.raises(ValueError, match="between 0 and 1"):
        validate_confidence(1.5)
    with pytest.raises(ValueError, match="at least three"):
        mask_from_polygon(((1, 2), (3, 4)), image_size=IMAGE_SIZE)
