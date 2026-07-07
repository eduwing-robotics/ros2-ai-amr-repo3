from __future__ import annotations

from pathlib import Path

from api_test_helpers import client, main_module, np

from app.config import get_settings
from app.contracts import validate_evidence_evaluation

OBSERVED_AT = "2026-06-24T17:30:00+09:00"


def _reset_runtime_state() -> None:
    main_module.metrics.reset()
    main_module.store.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()


def _lift_roi_evidence_count_mismatch() -> dict:
    return {
        "schema_version": "lift-roi-evidence.v1",
        "evidence_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "timestamp": OBSERVED_AT,
        "source": "global_cam_01",
        "robot_id": None,
        "frame_id": "global_camera_frame",
        "operation": "PICKUP",
        "task_id": "MAIN-TASK-001",
        "image": {"width": 200, "height": 160},
        "roi": {
            "roi_id": "GLOBAL_LIFT_ROI",
            "kind": "LIFT",
            "polygon_xy": [[0, 0], [200, 0], [200, 160], [0, 160]],
        },
        "expected_count": 2,
        "stable_frames": 3,
        "count_stable": True,
        "lift_sensor": {
            "lift_up": True,
            "lift_down_complete": None,
            "backoff_complete": None,
        },
        "load": {
            "count": 1,
            "empty": False,
            "accepted_items": [
                {
                    "class_name": "box",
                    "bbox_xyxy": [10.0, 20.0, 50.0, 80.0],
                    "confidence": 0.74,
                    "track_id": "item-1",
                    "evidence_type": "bbox",
                    "mask_area_px": None,
                    "center_inside_roi": True,
                    "overlap_ratio": 1.0,
                    "reason": "accepted",
                }
            ],
            "rejected_items": [],
        },
        "dropped_item_count": 0,
        "verification": {
            "status": "CANDIDATE",
            "reason": "load_count_mismatch",
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


def test_evidence_evaluate_accepts_lift_roi_payload_and_preserves_main_ids():
    _reset_runtime_state()
    response = client.post(
        "/api/v1/evidence/evaluate",
        json={
            "source": "global_cam_01",
            "view": "lift_roi",
            "operation": "PICKUP",
            "expected_evidence_type": "ITEM_PICKED",
            "expected_count": 2,
            "task_ref": {
                "task_id": 123,
                "command_id": "CMD-456",
                "location_id": "STORAGE_A_01",
            },
            "lift_roi_evidence": _lift_roi_evidence_count_mismatch(),
        },
    )

    assert response.status_code == 200
    body = response.json()
    validate_evidence_evaluation(body)
    assert body["verification_status"] == "FAIL"
    assert body["validity"] == "INVALID_CANDIDATE"
    assert body["reason_code"] == "COUNT_MISMATCH"
    assert body["trusted"] is False
    assert body["task_ref"] == {
        "task_id": 123,
        "command_id": "CMD-456",
        "location_id": "STORAGE_A_01",
    }
    assert body["data_json"]["original_contract"] == "lift-roi-evidence.v1"

    metrics = client.get("/api/v1/metrics").json()["metrics"]["evidence_evaluation"]
    assert metrics["evaluations_total"] == 1
    assert metrics["verification_total"]["FAIL"] == 1
    assert metrics["reason_total"]["COUNT_MISMATCH"] == 1


def test_evidence_evaluate_missing_frame_is_uncertain_no_frame():
    _reset_runtime_state()

    response = client.post(
        "/api/v1/evidence/evaluate",
        json={
            "source": "global_cam_01",
            "view": "lift_roi",
            "operation": "PICKUP",
            "expected_evidence_type": "ITEM_PICKED",
            "expected_count": 1,
            "task_ref": {"task_id": "TASK-NO-FRAME"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    validate_evidence_evaluation(body)
    assert body["verification_status"] == "UNCERTAIN"
    assert body["validity"] == "NEEDS_REVIEW"
    assert body["reason_code"] == "NO_FRAME"
    assert body["image_uri"] is None
    assert body["task_ref"]["task_id"] == "TASK-NO-FRAME"


def test_evidence_evaluate_quality_flag_returns_needs_review_before_payload_promotion():
    _reset_runtime_state()

    response = client.post(
        "/api/v1/evidence/evaluate",
        json={
            "source": "global_cam_01",
            "view": "full",
            "operation": "MONITOR",
            "expected_evidence_type": "ITEM_DROPPED_CANDIDATE",
            "task_ref": {"task_id": "TASK-QUALITY-REVIEW"},
            "quality_flags": {
                "low_pixel_budget": True,
                "details": {
                    "object_size_m": 0.04,
                    "effective_object_px": 12.8,
                    "min_object_px": 16.0,
                },
            },
        },
    )

    assert response.status_code == 200
    body = response.json()
    validate_evidence_evaluation(body)
    assert body["verification_status"] == "UNCERTAIN"
    assert body["validity"] == "NEEDS_REVIEW"
    assert body["reason_code"] == "LOW_PIXEL_BUDGET"
    assert body["data_json"]["ai_judgement"]["quality_details"]["effective_object_px"] == 12.8
    assert body["data_json"]["alert_window"]["max_frames"] == 30

    metrics = client.get("/api/v1/metrics").json()["metrics"]["evidence_evaluation"]
    assert metrics["reason_total"]["LOW_PIXEL_BUDGET"] == 1


def test_evidence_evaluate_rejects_unknown_quality_flag_key():
    _reset_runtime_state()

    response = client.post(
        "/api/v1/evidence/evaluate",
        json={
            "source": "global_cam_01",
            "view": "full",
            "quality_flags": {"raise_fps_now": True},
        },
    )

    assert response.status_code == 400
    assert "unknown quality_flags keys" in response.json()["error"]["message"]


def test_evidence_evaluate_rejects_unknown_expected_evidence_type():
    _reset_runtime_state()

    response = client.post(
        "/api/v1/evidence/evaluate",
        json={
            "source": "global_cam_01",
            "view": "full",
            "expected_evidence_type": "TYPO_EVENT",
        },
    )

    assert response.status_code == 400
    assert "unknown expected_evidence_type" in response.json()["error"]["message"]


def test_evidence_evaluate_rejects_request_supplied_image_uri():
    _reset_runtime_state()

    response = client.post(
        "/api/v1/evidence/evaluate",
        json={
            "source": "global_cam_01",
            "view": "full",
            "operation": "MONITOR",
            "expected_evidence_type": "STATUS",
            "image_uri": "/api/v1/evidence/images/global_cam_01/full/2026-06-24/proof.jpg",
        },
    )

    assert response.status_code == 400
    assert "image_uri is response-only" in response.json()["error"]["message"]


def test_evidence_evaluate_rejects_malformed_lift_roi_evidence_as_bad_request():
    _reset_runtime_state()
    malformed = _lift_roi_evidence_count_mismatch()
    malformed["dropped_item_count"] = "abc"

    response = client.post(
        "/api/v1/evidence/evaluate",
        json={
            "source": "global_cam_01",
            "view": "lift_roi",
            "operation": "PICKUP",
            "expected_evidence_type": "ITEM_PICKED",
            "expected_count": 2,
            "lift_roi_evidence": malformed,
        },
    )

    assert response.status_code == 400
    assert "dropped_item_count" in response.json()["error"]["message"]


def test_evidence_evaluate_stale_latest_frame_is_uncertain_source_stale():
    _reset_runtime_state()
    image = np.zeros((20, 30, 3), dtype=np.uint8)
    main_module.frame_store.put_decoded(
        source="global_cam_01",
        image_bgr=image,
        timestamp="2026-01-01T00:00:00+00:00",
    )

    response = client.post(
        "/api/v1/evidence/evaluate",
        json={
            "source": "global_cam_01",
            "view": "full",
            "operation": "MONITOR",
            "expected_evidence_type": "STATUS",
            "max_frame_age_s": 0.1,
        },
    )

    assert response.status_code == 200
    body = response.json()
    validate_evidence_evaluation(body)
    assert body["verification_status"] == "UNCERTAIN"
    assert body["reason_code"] == "SOURCE_STALE"


def test_evidence_evaluate_latest_synthetic_event_can_store_proof_image(
    monkeypatch,
    tmp_path: Path,
):
    _reset_runtime_state()
    monkeypatch.setattr(get_settings(), "evidence_image_root", tmp_path)

    synthetic = client.post(
        "/api/v1/vision/synthetic/frame",
        json={"source": "global_cam_01", "marker_id": 7},
    )
    assert synthetic.status_code == 200
    assert synthetic.json()["events"]

    response = client.post(
        "/api/v1/evidence/evaluate",
        json={
            "source": "global_cam_01",
            "view": "full",
            "operation": "MONITOR",
            "expected_evidence_type": "ARUCO_DETECTED",
            "task_ref": {"task_id": "TASK-SYNTH", "command_id": "CMD-SYNTH"},
            "image_policy": {"save_proof": True, "proof_label": "aruco-proof"},
        },
    )

    assert response.status_code == 200
    body = response.json()
    validate_evidence_evaluation(body)
    assert body["verification_status"] == "PASS"
    assert body["proposed_event_type"] == "ARUCO_DETECTED"
    assert body["image_uri"]
    assert body["data_json"]["proof_image"] == {
        "image_uri": body["image_uri"],
        "content_type": "image/jpeg",
    }
    assert str(tmp_path) not in str(body["data_json"]["proof_image"])

    image_response = client.get(body["image_uri"])
    assert image_response.status_code == 200
    assert image_response.content


def test_evidence_evaluate_rejects_legacy_image_policy_aliases():
    _reset_runtime_state()

    response = client.post(
        "/api/v1/evidence/evaluate",
        json={
            "source": "global_cam_01",
            "view": "full",
            "operation": "MONITOR",
            "expected_evidence_type": "STATUS",
            "image_policy": {"store_image": True, "filename_hint": "legacy-proof"},
        },
    )

    assert response.status_code == 400
    assert "unknown image_policy keys" in response.json()["error"]["message"]


def test_evidence_image_route_rejects_encoded_traversal_segments():
    _reset_runtime_state()

    response = client.get("/api/v1/evidence/images/global_cam_01/%2E%2E/2026-06-24/proof.jpg")

    assert response.status_code == 400
    assert "unsafe path segment" in response.json()["error"]["message"]

    response = client.get("/api/v1/evidence/images/global_cam_01/full/%2E%2E/proof.jpg")

    assert response.status_code == 400
    assert "unsafe path segment" in response.json()["error"]["message"]


def test_mock_connector_calls_only_evaluate_api_and_gets_schema_valid_response():
    _reset_runtime_state()

    def mock_connector_evaluate(task_id: int, command_id: int) -> dict:
        response = client.post(
            "/api/v1/evidence/evaluate",
            json={
                "source": "global_cam_01",
                "view": "lift_roi",
                "operation": "PICKUP",
                "expected_evidence_type": "ITEM_PICKED",
                "expected_count": 1,
                "task_ref": {
                    "task_id": task_id,
                    "command_id": command_id,
                    "location_id": "STORAGE_A_01",
                },
            },
        )
        assert response.status_code == 200
        return response.json()

    body = mock_connector_evaluate(task_id=321, command_id=654)

    validate_evidence_evaluation(body)
    assert body["trusted"] is False
    assert body["task_ref"] == {
        "task_id": 321,
        "command_id": 654,
        "location_id": "STORAGE_A_01",
    }
    assert body["verification_status"] == "UNCERTAIN"
    assert body["reason_code"] == "NO_FRAME"
