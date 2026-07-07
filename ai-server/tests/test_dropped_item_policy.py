from app.vision_monitor_policies import RectRoi, evaluate_dropped_item_policy


def _map_roi():
    return RectRoi("map", 0, 0, 1800, 1800)


def _carriers():
    return [
        RectRoi("tb3_1_carrier", 200, 200, 500, 500, robot_id="tb3_1"),
        RectRoi("tb3_2_carrier", 1200, 1200, 1500, 1500, robot_id="tb3_2"),
    ]


def _target(center, confidence=0.81):
    x, y = center
    return {
        "class_name": "target_item",
        "confidence": confidence,
        "bbox_xyxy": [x - 5, y - 5, x + 5, y + 5],
    }


def _flatten(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _flatten(child)
    elif isinstance(value, list):
        for child in value:
            yield from _flatten(child)
    else:
        yield value


def test_target_item_inside_active_carrier_is_ignored_not_dropped():
    result = evaluate_dropped_item_policy(
        detections=[_target((300, 300))],
        map_roi=_map_roi(),
        carrier_rois=_carriers(),
    )

    assert result["result"] == "IGNORED"
    assert result["reason_code"] == "TARGET_ITEM_INSIDE_DYNAMIC_CARRIER_ROI"
    assert result["assignment_status"] == "OWNED"
    assert result["robot_id"] == "tb3_1"


def test_target_item_outside_all_carriers_after_stability_is_candidate_with_clear_owner():
    result = evaluate_dropped_item_policy(
        detections=[_target((650, 500), confidence=0.73)],
        map_roi=_map_roi(),
        carrier_rois=_carriers(),
        stable_frame_count=3,
        min_stable_frames=2,
    )

    assert result["event_type"] == "DROPPED_ITEM_CANDIDATE"
    assert result["result"] == "CANDIDATE"
    assert result["reason_code"] == "TARGET_ITEM_OUTSIDE_DYNAMIC_CARRIER_ROI"
    assert result["assignment_status"] == "OWNED"
    assert result["robot_id"] == "tb3_1"
    assert result["confidence"] == 0.73


def test_target_item_in_allowed_zone_is_ignored_before_dropped_candidate():
    result = evaluate_dropped_item_policy(
        detections=[_target((900, 100))],
        map_roi=_map_roi(),
        carrier_rois=_carriers(),
        allowed_zones=[RectRoi("lift_entry_allowed", 800, 0, 1000, 200)],
        stable_frame_count=5,
        min_stable_frames=2,
    )

    assert result["event_type"] == "IGNORED"
    assert result["result"] == "IGNORED"
    assert result["reason_code"] == "IGNORED_ALLOWED_ZONE"
    assert result["assignment_status"] == "UNASSIGNED"


def test_overlapping_dynamic_carrier_rois_are_ambiguous_no_decision():
    result = evaluate_dropped_item_policy(
        detections=[_target((360, 360))],
        map_roi=_map_roi(),
        carrier_rois=[
            RectRoi("tb3_1_carrier", 200, 200, 500, 500, robot_id="tb3_1"),
            RectRoi("tb3_2_carrier", 300, 300, 600, 600, robot_id="tb3_2"),
        ],
    )

    assert result["result"] == "NO_DECISION"
    assert result["reason_code"] == "AMBIGUOUS_DYNAMIC_CARRIER_ROI"
    assert result["assignment_status"] == "AMBIGUOUS"
    assert set(result["related_robot_ids"]) == {"tb3_1", "tb3_2"}


def test_unstable_target_item_does_not_become_candidate_yet():
    result = evaluate_dropped_item_policy(
        detections=[_target((650, 500))],
        map_roi=_map_roi(),
        carrier_rois=_carriers(),
        stable_frame_count=1,
        min_stable_frames=3,
    )

    assert result["result"] == "NO_DECISION"
    assert result["reason_code"] == "POLICY_NOT_APPLICABLE"
    assert result["assignment_status"] == "OWNED"
    assert result["robot_id"] == "tb3_1"


def test_equidistant_target_between_two_carriers_is_ambiguous():
    result = evaluate_dropped_item_policy(
        detections=[_target((900, 900))],
        map_roi=_map_roi(),
        carrier_rois=_carriers(),
        stable_frame_count=3,
        min_stable_frames=2,
        ambiguous_distance_delta=500,
    )

    assert result["result"] == "CANDIDATE"
    assert result["assignment_status"] == "AMBIGUOUS"
    assert result["robot_id"] is None
    assert set(result["related_robot_ids"]) == {"tb3_1", "tb3_2"}


def test_no_target_item_returns_no_decision():
    result = evaluate_dropped_item_policy(
        detections=[{"class_name": "person", "confidence": 0.95, "center": [100, 100]}],
        map_roi=_map_roi(),
        carrier_rois=_carriers(),
    )

    assert result["result"] == "NO_DECISION"
    assert result["reason_code"] == "NO_RELEVANT_DETECTION"
    assert result["assignment_status"] == "UNASSIGNED"


def test_dropped_item_policy_output_is_compact_no_bbox_or_control_action():
    result = evaluate_dropped_item_policy(
        detections=[_target((650, 500))],
        map_roi=_map_roi(),
        carrier_rois=_carriers(),
        stable_frame_count=3,
        min_stable_frames=2,
    )
    flattened = set(_flatten(result))

    assert not (flattened & {"bbox", "bbox_xyxy", "mask", "polygon", "raw_detections"})
    assert not (flattened & {"E_STOP", "HOLD", "STOP_COMMAND", "MOTION_CANCELLED"})
