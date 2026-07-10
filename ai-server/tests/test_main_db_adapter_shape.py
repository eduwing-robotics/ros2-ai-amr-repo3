import json
from pathlib import Path

import pytest

from app.contracts import ContractValidationError
from app.vision_main_db_adapter import (
    command_progress_satisfied,
    evidence_event_row_from_lift_evaluation,
    evidence_event_row_from_monitor_payload,
    safety_stop_decision_from_evidence_row,
)
from app.vision_monitor_policies import evaluate_lift_load_marker_burst

ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "docs" / "contracts" / "fixtures" / "vision-monitor-event"


def _load(name: str):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _lift_marker_evaluation(*, operation: str, result: str = "PASS"):
    if result == "UNCERTAIN":
        return evaluate_lift_load_marker_burst(
            per_frame_expected_counts=[],
            per_frame_item_counts=[],
            expected_count=1,
            operation=operation,
            min_pass_frames=1,
            requested_frames=5,
        )
    return evaluate_lift_load_marker_burst(
        per_frame_expected_counts=[1],
        per_frame_item_counts=[1],
        expected_count=1,
        operation=operation,
        min_pass_frames=1,
        requested_frames=5,
    )


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


def test_ai_monitor_evidence_event_row_is_untrusted_and_compact():
    row = evidence_event_row_from_monitor_payload(_load("valid.person-hazard.json"))
    flattened = set(_flatten(row))

    assert row["event_type"] == "HUMAN_DETECTED"
    assert row["trusted"] is False
    assert row["data_json"]["result"] == "ADVISORY"
    assert row["data_json"]["reason_code"] == "HUMAN_DETECTED"
    assert not (flattened & {"bbox", "bbox_xyxy", "mask", "polygon", "raw_detections"})
    assert not (flattened & {"E_STOP", "HOLD", "STOP_COMMAND", "MOTION_CANCELLED", "BLOCKED"})


def test_main_db_adapter_rejects_raw_bbox_or_control_fields():
    payload = _load("valid.dropped-item-candidate.json")
    payload["data_json"]["bbox_xyxy"] = [1, 2, 3, 4]

    with pytest.raises(ContractValidationError):
        evidence_event_row_from_monitor_payload(payload)


def test_pickup_pass_maps_to_item_picked_and_satisfies_command_progress():
    evaluation = _lift_marker_evaluation(operation="PICKUP")

    row = evidence_event_row_from_lift_evaluation(
        evaluation,
        operation="PICK_UP",
        robot_id="tb3_1",
        task_id=1001,
        command_id=11,
    )

    assert row["event_type"] == "ITEM_PICKED"
    assert command_progress_satisfied(row) is True
    assert row["trusted"] is False
    assert row["data_json"]["ai_judgement"]["verification_status"] == "PASS"


def test_dropoff_pass_maps_to_item_placed_and_satisfies_command_progress():
    evaluation = _lift_marker_evaluation(operation="DROPOFF")

    row = evidence_event_row_from_lift_evaluation(
        evaluation,
        operation="DROP_OFF",
        robot_id="tb3_1",
        task_id=1002,
        command_id=12,
    )

    assert row["event_type"] == "ITEM_PLACED"
    assert command_progress_satisfied(row) is True


def test_pre_dropoff_pass_maps_to_placement_ready_and_satisfies_command_progress():
    evaluation = _lift_marker_evaluation(operation="PRE_DROP_OFF")

    row = evidence_event_row_from_lift_evaluation(
        evaluation,
        operation="PRE_DROP_OFF",
        robot_id="tb3_1",
        task_id=1004,
        command_id=14,
    )

    assert row["event_type"] == "ITEM_PLACEMENT_READY"
    assert command_progress_satisfied(row) is True
    assert row["trusted"] is False


def test_uncertain_lift_evidence_does_not_satisfy_command_progress():
    evaluation = _lift_marker_evaluation(operation="PICKUP", result="UNCERTAIN")

    row = evidence_event_row_from_lift_evaluation(
        evaluation,
        operation="PICK_UP",
        robot_id="tb3_1",
        task_id=1003,
        command_id=13,
    )

    assert row["event_type"] == "LIFT_LOAD_UNCERTAIN"
    assert command_progress_satisfied(row) is False
    assert row["data_json"]["ai_judgement"]["verification_status"] == "UNCERTAIN"


def test_safety_stop_opens_only_for_robot_resolvable_safety_evidence_without_task_blocked():
    row = evidence_event_row_from_monitor_payload(_load("valid.person-hazard.json"))

    decision = safety_stop_decision_from_evidence_row(row)

    assert decision["open_safety_stop"] is True
    assert decision["status"] == "OPEN"
    assert decision["robot_resolvable"] is True
    assert decision["task_status_update"] is None
    assert "BLOCKED" not in set(_flatten(decision))


def test_ambiguous_or_unassigned_safety_evidence_does_not_open_robot_specific_hold():
    row = evidence_event_row_from_monitor_payload(_load("valid.dropped-item-candidate.json"))
    row["data_json"]["assignment_status"] = "AMBIGUOUS"
    row["data_json"]["robot_id"] = None
    row["task_id"] = None

    decision = safety_stop_decision_from_evidence_row(row)

    assert decision["open_safety_stop"] is False
    assert decision["status"] == "NO_DECISION"
    assert decision["robot_resolvable"] is False
    assert decision["task_status_update"] is None
