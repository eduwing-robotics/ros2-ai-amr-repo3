"""No-hardware lift/load AI evidence contract regression tests."""

from app.vision_monitor_policies import evaluate_lift_load_marker_burst


def test_nohardware_lift_load_pass_sets_command_satisfying_true():
    result = evaluate_lift_load_marker_burst(
        per_frame_expected_counts=[1, 1, 1],
        per_frame_item_counts=[1, 1, 1],
        expected_count=1,
        operation="PICKUP",
        min_pass_frames=3,
        requested_frames=3,
    )

    assert result["result"] == "PASS"
    assert result["command_satisfying"] is True


def test_nohardware_lift_load_fail_sets_command_satisfying_false():
    result = evaluate_lift_load_marker_burst(
        per_frame_expected_counts=[1, 1, 1],
        per_frame_item_counts=[1, 2, 1],
        expected_count=1,
        operation="PICKUP",
        min_pass_frames=1,
        requested_frames=3,
    )

    assert result["result"] == "FAIL"
    assert result["command_satisfying"] is False


def test_nohardware_lift_load_uncertain_sets_command_satisfying_false():
    result = evaluate_lift_load_marker_burst(
        per_frame_expected_counts=[1],
        per_frame_item_counts=[1],
        expected_count=1,
        operation="DROPOFF",
        min_pass_frames=3,
        requested_frames=5,
    )

    assert result["result"] == "UNCERTAIN"
    assert result["command_satisfying"] is False


def test_nohardware_pre_dropoff_pass_is_command_satisfying():
    result = evaluate_lift_load_marker_burst(
        per_frame_expected_counts=[1, 1],
        per_frame_item_counts=[1, 1],
        expected_count=1,
        operation="PRE_DROP_OFF",
        min_pass_frames=2,
        requested_frames=2,
    )

    assert result["result"] == "PASS"
    assert result["event_type"] == "ITEM_PLACEMENT_READY"
    assert result["command_satisfying"] is True
