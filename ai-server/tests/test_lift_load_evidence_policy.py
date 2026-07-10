from app.vision_monitor_policies import evaluate_lift_load_marker_burst


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


def test_lift_load_marker_burst_passes_with_stable_expected_item_counts():
    result = evaluate_lift_load_marker_burst(
        per_frame_expected_counts=[1, 1, 1, 0, 0],
        per_frame_item_counts=[1, 1, 1, 0, 0],
        expected_count=1,
        operation="PICKUP",
        min_pass_frames=3,
        requested_frames=5,
    )

    assert result["result"] == "PASS"
    assert result["event_type"] == "ITEM_PICKED"
    assert result["reason_code"] == "EXPECTED_ITEM_COUNT_MATCH_AND_STABLE"
    assert result["confidence"] == 0.6
    assert result["accepted_frames"] == 3
    assert result["total_frames"] == 5


def test_lift_load_marker_burst_is_uncertain_when_default_burst_has_too_few_frames():
    result = evaluate_lift_load_marker_burst(
        per_frame_expected_counts=[1],
        per_frame_item_counts=[1],
        expected_count=1,
        operation="PICKUP",
        min_pass_frames=3,
        requested_frames=5,
    )

    assert result["result"] == "UNCERTAIN"
    assert result["event_type"] == "LIFT_LOAD_UNCERTAIN"
    assert result["reason_code"] == "LOW_CONFIDENCE"
    assert result["confidence"] == 0.2
    assert result["accepted_frames"] == 1
    assert result["total_frames"] == 1


def test_lift_load_marker_burst_fails_when_extra_item_appears_anywhere_in_burst():
    result = evaluate_lift_load_marker_burst(
        per_frame_expected_counts=[1, 1, 1, 1, 1],
        per_frame_item_counts=[1, 1, 2, 1, 1],
        expected_count=1,
        operation="DROPOFF",
        min_pass_frames=1,
        requested_frames=5,
    )

    assert result["result"] == "FAIL"
    assert result["event_type"] == "LIFT_LOAD_EVIDENCE"
    assert result["reason_code"] == "EXPECTED_ITEM_COUNT_MISMATCH"
    assert result["accepted_frames"] == 4
    assert result["observed_count"] == 2
    assert result["command_satisfying"] is False


def test_lift_load_marker_burst_fails_when_wrong_item_marker_is_present():
    result = evaluate_lift_load_marker_burst(
        per_frame_expected_counts=[0, 0, 0],
        per_frame_item_counts=[1, 1, 1],
        expected_count=1,
        operation="DROPOFF",
        min_pass_frames=2,
        requested_frames=3,
    )

    assert result["result"] == "FAIL"
    assert result["event_type"] == "LIFT_LOAD_EVIDENCE"
    assert result["reason_code"] == "EXPECTED_ITEM_COUNT_MISMATCH"
    assert result["observed_count"] == 1
    assert result["command_satisfying"] is False


def test_lift_load_marker_burst_output_is_compact_no_bbox_or_control_action():
    result = evaluate_lift_load_marker_burst(
        per_frame_expected_counts=[1],
        per_frame_item_counts=[1],
        expected_count=1,
        operation="PICKUP",
        min_pass_frames=1,
        requested_frames=5,
    )
    flattened = set(_flatten(result))

    assert not (flattened & {"bbox", "bbox_xyxy", "mask", "polygon", "raw_detections"})
    assert not (flattened & {"E_STOP", "HOLD", "STOP_COMMAND", "MOTION_CANCELLED"})


def test_lift_load_marker_burst_pre_dropoff_pass_is_placement_ready():
    result = evaluate_lift_load_marker_burst(
        per_frame_expected_counts=[1, 1, 1],
        per_frame_item_counts=[1, 1, 1],
        expected_count=1,
        operation="PRE_DROP_OFF",
        min_pass_frames=2,
        requested_frames=3,
    )

    assert result["result"] == "PASS"
    assert result["event_type"] == "ITEM_PLACEMENT_READY"
    assert result["reason_code"] == "EXPECTED_ITEM_COUNT_MATCH_AND_STABLE"
    assert result["command_satisfying"] is True
