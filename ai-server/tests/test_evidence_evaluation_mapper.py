from __future__ import annotations

import json
import logging
from pathlib import Path

from app.contracts import validate_evidence_evaluation
from app.evidence_evaluation import (
    build_evidence_image_location,
    build_no_frame_evaluation,
    build_quality_review_evaluation,
    map_lift_roi_evidence_to_evaluation,
    map_vision_event_to_evaluation,
    record_evidence_evaluation_observability,
    save_evidence_image,
)
from app.runtime_state import create_runtime_context

OBSERVED_AT = "2026-06-24T17:20:00+09:00"


def _accepted_item(class_name: str = "box", confidence: float = 0.91) -> dict:
    return {
        "class_name": class_name,
        "bbox_xyxy": [10.0, 20.0, 50.0, 80.0],
        "confidence": confidence,
        "track_id": "item-1",
        "evidence_type": "bbox",
        "mask_area_px": None,
        "center_inside_roi": True,
        "overlap_ratio": 1.0,
        "reason": "accepted",
    }


def _lift_roi_evidence(
    *,
    operation: str = "PICKUP",
    expected_count: int | None = 1,
    count: int = 1,
    count_stable: bool = True,
    dropped_item_count: int = 0,
    verification_status: str = "CONFIRMED",
    verification_reason: str = "pickup_verified",
) -> dict:
    accepted = [_accepted_item()] if count else []
    return {
        "schema_version": "lift-roi-evidence.v1",
        "evidence_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "timestamp": OBSERVED_AT,
        "source": "global_cam_01",
        "robot_id": None,
        "frame_id": "global_camera_frame",
        "operation": operation,
        "task_id": "TASK-001",
        "image": {"width": 200, "height": 160},
        "roi": {
            "roi_id": "GLOBAL_LIFT_ROI",
            "kind": "LIFT",
            "polygon_xy": [[0, 0], [200, 0], [200, 160], [0, 160]],
        },
        "expected_count": expected_count,
        "stable_frames": 3,
        "count_stable": count_stable,
        "lift_sensor": {
            "lift_up": True,
            "lift_down_complete": None,
            "backoff_complete": None,
        },
        "load": {
            "count": count,
            "empty": count == 0,
            "accepted_items": accepted,
            "rejected_items": [],
        },
        "dropped_item_count": dropped_item_count,
        "verification": {
            "status": verification_status,
            "reason": verification_reason,
        },
        "policy": {
            "policy_version": "mvp1-lift-roi",
            "load_classes": ["box", "pallet"],
            "min_confidence": 0.5,
            "min_overlap_ratio": 0.6,
        },
        "metadata": {
            "model": "provided-bbox",
            "latency_ms": 1.23,
        },
    }


def _vision_event(**overrides) -> dict:
    event = {
        "schema_version": "vision-event.v1",
        "event_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        "timestamp": OBSERVED_AT,
        "source": "global_cam_01",
        "robot_id": None,
        "frame_id": "global_camera_frame",
        "event_kind": "CANDIDATE",
        "class_name": "dropped_item",
        "confidence": 0.82,
        "bbox_xyxy": [40.0, 50.0, 80.0, 90.0],
        "track_id": "drop-1",
        "marker_id": None,
        "zone": None,
        "roi_id": None,
        "pose_estimate": None,
        "depth_median_m": None,
        "wms_hint": "DROPPED_ITEM_CANDIDATE",
        "metadata": {
            "n_frame_count": 2,
            "policy_version": "mvp1",
            "model": "fake-detector",
            "image_width": 200,
            "image_height": 160,
            "latency_ms": 2.5,
        },
    }
    event.update(overrides)
    return event


def _assert_valid_advisory(payload: dict) -> None:
    validate_evidence_evaluation(payload)
    assert payload["schema_version"] == "evidence-evaluation.v1"
    assert payload["trusted"] is False
    assert (
        payload["data_json"]["ai_judgement"]["verification_status"]
        == payload["verification_status"]
    )
    assert payload["data_json"]["ai_judgement"]["validity"] == payload["validity"]
    assert payload["data_json"]["ai_judgement"]["reason_code"] == payload["reason_code"]


def test_lift_roi_mapper_returns_pass_with_original_payload_preserved():
    original = _lift_roi_evidence()

    evaluation = map_lift_roi_evidence_to_evaluation(
        original,
        view="lift_roi",
        expected_evidence_type="ITEM_PICKED",
        task_ref={"task_id": 101, "command_id": 202, "location_id": "A01"},
        image_uri="/api/v1/evidence/images/global_cam_01/lift_roi/2026-06-24/proof.jpg",
        evaluation_id="11111111-1111-4111-8111-111111111111",
    )

    _assert_valid_advisory(evaluation)
    assert evaluation["verification_status"] == "PASS"
    assert evaluation["validity"] == "VALID_CANDIDATE"
    assert evaluation["reason_code"] == "COUNT_MATCH_AND_STABLE"
    assert evaluation["proposed_event_type"] == "ITEM_PICKED"
    assert evaluation["confidence"] == 0.91
    assert evaluation["task_ref"]["task_id"] == 101
    assert evaluation["data_json"]["original_contract"] == "lift-roi-evidence.v1"
    assert evaluation["data_json"]["original_payload"] == original
    assert evaluation["data_json"]["mapper_version"] == "evidence-evaluation-mapper.v1"


def test_lift_roi_mapper_marks_count_mismatch_as_invalid_candidate_fail():
    original = _lift_roi_evidence(
        expected_count=2,
        count=1,
        verification_status="CANDIDATE",
        verification_reason="load_count_mismatch",
    )

    evaluation = map_lift_roi_evidence_to_evaluation(
        original,
        view="lift_roi",
        expected_evidence_type="ITEM_PICKED",
    )

    _assert_valid_advisory(evaluation)
    assert evaluation["verification_status"] == "FAIL"
    assert evaluation["validity"] == "INVALID_CANDIDATE"
    assert evaluation["reason_code"] == "COUNT_MISMATCH"
    assert evaluation["proposed_event_type"] == "ERROR"
    assert evaluation["data_json"]["ai_judgement"]["expected_count"] == 2
    assert evaluation["data_json"]["ai_judgement"]["observed_count"] == 1


def test_vision_event_mapper_handles_expected_dropped_item_candidate():
    original = _vision_event()

    evaluation = map_vision_event_to_evaluation(
        original,
        expected_evidence_type="ITEM_DROPPED_CANDIDATE",
        operation="MONITOR",
        task_ref={"task_id": "TASK-001"},
    )

    _assert_valid_advisory(evaluation)
    assert evaluation["verification_status"] == "PASS"
    assert evaluation["reason_code"] == "DROPPED_ITEM_DETECTED"
    assert evaluation["proposed_event_type"] == "ITEM_DROPPED_CANDIDATE"
    assert evaluation["data_json"]["original_payload"] == original
    assert evaluation["data_json"]["ai_judgement"]["stable_frames"] == 2
    assert evaluation["data_json"]["alert_window"]["trigger_reason_code"] == (
        "DROPPED_ITEM_DETECTED"
    )


def test_vision_event_mapper_marks_stale_event_uncertain():
    original = _vision_event(
        event_kind="STALE",
        class_name="unknown",
        confidence=None,
        bbox_xyxy=None,
        wms_hint="VISION_STALE",
    )

    evaluation = map_vision_event_to_evaluation(
        original,
        expected_evidence_type="STATUS",
        operation="UNKNOWN",
    )

    _assert_valid_advisory(evaluation)
    assert evaluation["verification_status"] == "UNCERTAIN"
    assert evaluation["validity"] == "NEEDS_REVIEW"
    assert evaluation["reason_code"] == "SOURCE_STALE"
    assert evaluation["proposed_event_type"] == "STATUS"
    assert evaluation["confidence"] is None


def test_no_frame_evaluation_is_uncertain_without_original_payload():
    evaluation = build_no_frame_evaluation(
        source="global_cam_01",
        view="lift_roi",
        operation="PICKUP",
        expected_evidence_type="ITEM_PICKED",
        expected_count=1,
        task_ref={"task_id": 101},
        observed_at=OBSERVED_AT,
        evaluation_id="33333333-3333-4333-8333-333333333333",
    )

    _assert_valid_advisory(evaluation)
    assert evaluation["verification_status"] == "UNCERTAIN"
    assert evaluation["reason_code"] == "NO_FRAME"
    assert evaluation["image_uri"] is None
    assert evaluation["data_json"]["original_contract"] is None
    assert evaluation["data_json"]["original_payload"] is None


def test_quality_review_evaluation_is_uncertain_and_carries_alert_window_metadata():
    evaluation = build_quality_review_evaluation(
        source="global_cam_01",
        view="full",
        operation="MONITOR",
        expected_evidence_type="ITEM_DROPPED_CANDIDATE",
        task_ref={"task_id": "TASK-LOW-PIXEL"},
        reason_code="LOW_PIXEL_BUDGET",
        observed_at=OBSERVED_AT,
        evaluation_id="55555555-5555-4555-8555-555555555555",
        quality_details={
            "object_size_m": 0.04,
            "effective_object_px": 12.8,
            "min_object_px": 16.0,
        },
    )

    _assert_valid_advisory(evaluation)
    assert evaluation["verification_status"] == "UNCERTAIN"
    assert evaluation["validity"] == "NEEDS_REVIEW"
    assert evaluation["reason_code"] == "LOW_PIXEL_BUDGET"
    assert evaluation["data_json"]["ai_judgement"]["quality_details"]["effective_object_px"] == 12.8
    assert evaluation["data_json"]["alert_window"]["policy_version"] == (
        "gopro-sparse-alert-window.v1"
    )
    assert evaluation["data_json"]["alert_window"]["advisory_only"] is True


def test_evidence_image_location_is_sanitized_and_persisted(tmp_path: Path):
    location = build_evidence_image_location(
        source="../global_cam_01",
        view="lift roi",
        evaluation_id="11111111-1111-4111-8111-111111111111",
        observed_at=OBSERVED_AT,
        root=tmp_path,
        base_uri="/api/v1/evidence/images",
        filename_hint="../lift-up proof",
    )

    assert location.path == (
        tmp_path
        / "global_cam_01"
        / "lift-roi"
        / "2026-06-24"
        / "lift-up-proof-11111111-1111-4111-8111-111111111111.jpg"
    )
    assert location.image_uri.endswith(
        "/global_cam_01/lift-roi/2026-06-24/lift-up-proof-11111111-1111-4111-8111-111111111111.jpg"
    )

    saved = save_evidence_image(
        b"fake-jpeg",
        source="../global_cam_01",
        view="lift roi",
        evaluation_id="11111111-1111-4111-8111-111111111111",
        observed_at=OBSERVED_AT,
        root=tmp_path,
        filename_hint="../lift-up proof",
    )

    assert saved.path.read_bytes() == b"fake-jpeg"
    assert saved.image_uri == location.image_uri


def test_evidence_evaluation_observability_records_counter_and_structured_log(caplog):
    context = create_runtime_context()
    caplog.set_level(logging.INFO, logger="smartfactory.ai_server")
    evaluation = build_no_frame_evaluation(
        source="global_cam_01",
        view="lift_roi",
        operation="PICKUP",
        expected_evidence_type="ITEM_PICKED",
        reason_code="SOURCE_STALE",
        observed_at=OBSERVED_AT,
        evaluation_id="55555555-5555-4555-8555-555555555555",
    )

    record_evidence_evaluation_observability(context, evaluation)

    metrics = context.metrics.snapshot()["evidence_evaluation"]
    assert metrics["evaluations_total"] == 1
    assert metrics["verification_total"]["UNCERTAIN"] == 1
    assert metrics["reason_total"]["SOURCE_STALE"] == 1
    assert metrics["by_source"]["global_cam_01"]["UNCERTAIN"] == 1

    log_payloads = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "smartfactory.ai_server"
    ]
    assert log_payloads[-1]["event"] == "evidence_evaluation"
    assert log_payloads[-1]["evaluation_id"] == evaluation["evaluation_id"]
    assert log_payloads[-1]["trusted"] is False


def test_lift_roi_mapper_pre_dropoff_proposes_placement_ready():
    evidence = _lift_roi_evidence(
        operation="PRE_DROP_OFF",
        count=1,
        expected_count=1,
        count_stable=True,
        verification_status="CONFIRMED",
    )

    evaluation = map_lift_roi_evidence_to_evaluation(
        evidence,
        view="lift_roi",
        expected_evidence_type="ITEM_PLACEMENT_READY",
        expected_count=1,
    )

    assert evaluation["verification_status"] == "PASS"
    assert evaluation["proposed_event_type"] == "ITEM_PLACEMENT_READY"
    assert evaluation["trusted"] is False
