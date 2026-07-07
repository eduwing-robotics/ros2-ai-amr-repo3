"""Vision worker status/tick and debug source API tests."""

import json

from api_test_helpers import (
    DetectionBox,
    aruco_png_bytes,
    blank_png_bytes,
    client,
    expected_ros_evidence_event_publish_policy,
    expected_ros_ingest_readiness,
    expected_ros_publish_runtime_plan,
    expected_ros_topic_exposure_policy,
    expected_rosbridge_subscription_hints,
    expected_source_topic_exposure,
    expected_topic_exposure_summary,
    get_settings,
    main_module,
)


def test_worker_tick_includes_pretrained_model_candidates_for_ros_overlay(monkeypatch):
    main_module.store.reset()
    main_module.source_health.reset()
    main_module.metrics.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()
    main_module._parse_vision_model_class_map.cache_clear()

    settings = get_settings()
    monkeypatch.setattr(settings, "vision_model_worker_enabled", True)
    monkeypatch.setattr(settings, "vision_model_path", "yolov8n.pt")
    monkeypatch.setattr(settings, "vision_model_task", "detect")
    monkeypatch.setattr(
        settings, "vision_model_class_map_json", '{"bottle":"box","person":"person"}'
    )
    monkeypatch.setattr(settings, "vision_model_unmapped_class", "unknown")

    class FakePretrainedModel:
        detector_name = "fake-yolov8n"

        def detect(self, image):
            assert image.shape[:2] == (160, 200)
            return (
                DetectionBox(
                    class_name="bottle",
                    bbox_xyxy=(20.0, 30.0, 80.0, 120.0),
                    confidence=0.88,
                    detector=self.detector_name,
                ),
            )

    monkeypatch.setattr(main_module, "_get_lift_roi_segmenter", lambda **_: FakePretrainedModel())

    ingest = client.post(
        "/api/v1/vision/frame",
        data={"source": "tb3_1_picam"},
        files={"image": ("frame.png", blank_png_bytes(width=200, height=160), "image/png")},
    )
    assert ingest.status_code == 200

    tick = client.post("/api/v1/vision/worker/tick", json={"source": "tb3_1_picam"})

    assert tick.status_code == 200
    body = tick.json()
    assert body["summary"]["event_count_total"] == 1
    assert body["results"][0]["overlay"]["event_count"] == 1

    latest = client.get("/api/v1/detections/latest", params={"source": "tb3_1_picam", "limit": 1})
    event = latest.json()["events"][0]
    assert event["event_kind"] == "CANDIDATE"
    assert event["class_name"] == "box"
    assert event["wms_hint"] == "ITEM_CANDIDATE"
    assert event["metadata"]["model"] == "fake-yolov8n"

    ros = client.get("/api/v1/vision/ros/topics", params={"source": "tb3_1_picam"})
    assert ros.status_code == 200
    source = ros.json()["sources"][0]
    assert source["publish_readiness"]["readiness_state"] == "ready_fresh"
    assert source["publish_readiness"]["publish_payload_preview"]["topic"] == (
        "/sf/vision/sources/tb3_1_picam/overlay/compressed"
    )
    assert source["evidence_event_publish_readiness"]["publish_ready"] is True


def test_worker_tick_routes_source_specific_model_config(monkeypatch):
    main_module.store.reset()
    main_module.source_health.reset()
    main_module.metrics.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()
    main_module._parse_vision_model_class_map.cache_clear()
    main_module._parse_vision_model_source_config.cache_clear()

    settings = get_settings()
    monkeypatch.setattr(settings, "vision_model_worker_enabled", True)
    monkeypatch.setattr(settings, "vision_model_path", "default-det.pt")
    monkeypatch.setattr(settings, "vision_model_task", "detect")
    monkeypatch.setattr(settings, "vision_model_imgsz", 224)
    monkeypatch.setattr(
        settings, "vision_model_class_map_json", '{"bottle":"box","person":"person"}'
    )
    monkeypatch.setattr(
        settings,
        "vision_model_source_config_json",
        json.dumps(
            {
                "global_cam_01": {
                    "model_path": "global-seg.pt",
                    "task": "segment",
                    "imgsz": 640,
                    "class_map": {"bottle": "box", "person": "person"},
                },
                "tb3_1_picam": {
                    "model_path": "picam-det.pt",
                    "task": "detect",
                    "imgsz": 320,
                    "class_map": {"person": "person"},
                },
            }
        ),
    )

    calls = []

    class FakePersonDetector:
        detector_name = "fake-source-detector"

        def detect(self, image):
            return (
                DetectionBox(
                    class_name="person",
                    bbox_xyxy=(10.0, 20.0, 70.0, 120.0),
                    confidence=0.77,
                    detector=self.detector_name,
                ),
            )

    def fake_model_factory(**kwargs):
        calls.append(kwargs)
        return FakePersonDetector()

    monkeypatch.setattr(main_module, "_get_lift_roi_segmenter", fake_model_factory)

    ingest = client.post(
        "/api/v1/vision/frame",
        data={"source": "tb3_1_picam"},
        files={"image": ("frame.png", blank_png_bytes(width=200, height=160), "image/png")},
    )
    assert ingest.status_code == 200

    tick = client.post("/api/v1/vision/worker/tick", json={"source": "tb3_1_picam"})

    assert tick.status_code == 200
    assert calls
    assert calls[0]["model_path"] == "picam-det.pt"
    assert calls[0]["task"] == "detect"
    assert calls[0]["image_size"] == 320
    assert calls[0]["class_map_json"] == '{"person": "person"}'
    event = client.get(
        "/api/v1/detections/latest",
        params={"source": "tb3_1_picam", "limit": 1},
    ).json()["events"][0]
    assert event["class_name"] == "person"
    assert event["wms_hint"] == "PERSON_CANDIDATE"


def test_vision_worker_tick_skips_current_overlay_by_default_and_force_reprocesses():
    main_module.source_health.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    ingest = client.post(
        "/api/v1/vision/synthetic/frame",
        json={"source": "tb3_1_picam", "marker_id": 7},
    )
    assert ingest.status_code == 200

    skipped = client.post(
        "/api/v1/vision/worker/tick",
        json={"source": "tb3_1_picam"},
    )
    assert skipped.status_code == 200
    assert skipped.json()["summary"]["status_counts"]["skipped"] == 1
    assert skipped.json()["summary"]["event_count_total"] == 1
    skipped_result = skipped.json()["results"][0]
    assert skipped_result["status"] == "skipped"
    assert skipped_result["frame_seq"] == 1
    assert skipped_result["overlay"]["frame_seq"] == 1

    forced = client.post(
        "/api/v1/vision/worker/tick",
        json={"source": "tb3_1_picam", "force": True, "stale": True},
    )
    assert forced.status_code == 200
    assert forced.json()["summary"]["processed_count"] == 1
    assert forced.json()["summary"]["event_count_total"] == 1
    forced_result = forced.json()["results"][0]
    assert forced_result["status"] == "processed"
    assert forced_result["frame_seq"] == 1
    assert forced_result["event_count"] == 1
    assert forced_result["overlay"]["stale"] is True


def test_vision_worker_tick_skips_stale_frame_unless_forced():
    main_module.source_health.reset()
    main_module.metrics.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    decoded = main_module.generate_synthetic_aruco_frame(marker_id=7)
    frame = main_module.frame_store.put_decoded(
        source="tb3_1_picam",
        image_bgr=decoded,
        timestamp="2000-01-01T00:00:00+00:00",
    )
    main_module.source_health.record_frame("tb3_1_picam", at=frame.timestamp)

    stale = client.post(
        "/api/v1/vision/worker/tick",
        json={"source": "tb3_1_picam", "max_frame_age_s": 0.001},
    )

    assert stale.status_code == 200
    assert stale.json()["summary"]["stale_frame_count"] == 1
    assert stale.json()["summary"]["event_count_total"] == 0
    stale_result = stale.json()["results"][0]
    assert stale_result["status"] == "stale_frame"
    assert stale_result["frame_seq"] == 1
    assert stale_result["event_count"] == 0
    assert stale_result["overlay"] is None
    assert stale_result["max_frame_age_s"] == 0.001

    forced = client.post(
        "/api/v1/vision/worker/tick",
        json={"source": "tb3_1_picam", "max_frame_age_s": 0.001, "force": True},
    )
    assert forced.status_code == 200
    forced_result = forced.json()["results"][0]
    assert forced_result["status"] == "processed"
    assert forced_result["frame_seq"] == 1
    assert forced_result["event_count"] == 1
    assert forced_result["overlay"]["frame_seq"] == 1


def test_vision_worker_status_reports_pending_skipped_and_stale_without_processing():
    main_module.source_health.reset()
    main_module.metrics.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    empty = client.get(
        "/api/v1/vision/worker/status",
        params={"source": "tb3_1_picam"},
    )
    assert empty.status_code == 200
    assert empty.json()["sources"][0]["next_tick_status"] == "no_frame"
    assert empty.json()["sources"][0]["would_create_new_evidence"] is False
    assert empty.json()["sources"][0]["evidence_action_if_ticked"] == "none"
    assert empty.json()["sources"][0]["expected_new_event_count"] == 0
    assert empty.json()["sources"][0]["reused_event_count_if_ticked"] == 0
    assert empty.json()["summary"]["sources_total"] == 1
    assert empty.json()["summary"]["status_counts"]["no_frame"] == 1
    assert empty.json()["summary"]["would_create_new_evidence_count"] == 0
    assert empty.json()["summary"]["expected_new_event_count_total"] == 0
    assert empty.json()["summary"]["reused_event_count_if_ticked_total"] == 0

    ingest = client.post(
        "/api/v1/vision/frame",
        data={"source": "tb3_1_picam"},
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )
    assert ingest.status_code == 200

    pending = client.get(
        "/api/v1/vision/worker/status",
        params={"source": "tb3_1_picam"},
    )
    assert pending.status_code == 200
    pending_source = pending.json()["sources"][0]
    assert pending_source["next_tick_status"] == "processed"
    assert pending_source["pending"] is True
    assert pending_source["latest_frame_seq"] == 1
    assert pending_source["latest_overlay_frame_seq"] is None
    assert pending_source["overlay_lag_frames"] is None
    assert pending_source["would_create_new_evidence"] is True
    assert pending_source["evidence_action_if_ticked"] == "created"
    assert pending_source["expected_new_event_count"] is None
    assert pending_source["reused_event_count_if_ticked"] == 0
    assert pending.json()["summary"]["pending_count"] == 1
    assert pending.json()["summary"]["status_counts"]["processed"] == 1
    assert pending.json()["summary"]["would_create_new_evidence_count"] == 1
    assert pending.json()["summary"]["expected_new_event_count_total"] == 0
    assert pending.json()["summary"]["reused_event_count_if_ticked_total"] == 0

    tick = client.post(
        "/api/v1/vision/worker/tick",
        json={"source": "tb3_1_picam"},
    )
    assert tick.status_code == 200

    skipped = client.get(
        "/api/v1/vision/worker/status",
        params={"source": "tb3_1_picam"},
    )
    assert skipped.status_code == 200
    skipped_source = skipped.json()["sources"][0]
    assert skipped_source["next_tick_status"] == "skipped"
    assert skipped_source["pending"] is False
    assert skipped_source["latest_overlay_frame_seq"] == 1
    assert skipped_source["overlay_lag_frames"] == 0
    assert skipped_source["would_create_new_evidence"] is False
    assert skipped_source["evidence_action_if_ticked"] == "reused"
    assert skipped_source["expected_new_event_count"] == 0
    assert skipped_source["reused_event_count_if_ticked"] == 1
    assert skipped.json()["summary"]["pending_count"] == 0
    assert skipped.json()["summary"]["status_counts"]["skipped"] == 1
    assert skipped.json()["summary"]["would_create_new_evidence_count"] == 0
    assert skipped.json()["summary"]["expected_new_event_count_total"] == 0
    assert skipped.json()["summary"]["reused_event_count_if_ticked_total"] == 1

    stale = client.get(
        "/api/v1/vision/worker/status",
        params={"source": "tb3_1_picam", "max_frame_age_s": 0},
    )
    assert stale.status_code == 200
    stale_source = stale.json()["sources"][0]
    assert stale_source["next_tick_status"] == "stale_frame"
    assert stale_source["pending"] is False
    assert stale_source["would_create_new_evidence"] is False
    assert stale_source["evidence_action_if_ticked"] == "none"
    assert stale_source["expected_new_event_count"] == 0
    assert stale_source["reused_event_count_if_ticked"] == 0
    assert stale.json()["summary"]["stale_frame_count"] == 1
    assert stale.json()["summary"]["status_counts"]["stale_frame"] == 1
    assert stale.json()["summary"]["would_create_new_evidence_count"] == 0
    assert stale.json()["summary"]["expected_new_event_count_total"] == 0
    assert stale.json()["summary"]["reused_event_count_if_ticked_total"] == 0


def test_vision_worker_tick_reports_no_frame_for_empty_source():
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    response = client.post(
        "/api/v1/vision/worker/tick",
        json={"source": "tb3_2_picam"},
    )

    assert response.status_code == 200
    assert response.json()["summary"]["status_counts"]["no_frame"] == 1
    assert response.json()["summary"]["event_count_total"] == 0
    result = response.json()["results"][0]
    assert result["status"] == "no_frame"
    assert result["frame_seq"] is None
    assert result["overlay"] is None


def test_vision_worker_tick_rejects_unknown_source():
    response = client.post(
        "/api/v1/vision/worker/tick",
        json={"source": "bad_cam"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"


def test_vision_debug_sources_returns_readiness_snapshot_for_one_source():
    main_module.source_health.reset()
    main_module.metrics.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    first = client.post(
        "/api/v1/vision/synthetic/frame",
        json={"source": "tb3_1_picam", "marker_id": 7},
    )
    assert first.status_code == 200
    second = client.post(
        "/api/v1/vision/synthetic/frame",
        json={"source": "tb3_1_picam", "marker_id": 8},
    )
    assert second.status_code == 200
    main_module.metrics.record_stream_frame_sent(source="tb3_1_picam")

    response = client.get("/api/v1/vision/debug/sources", params={"source": "tb3_1_picam"})

    assert response.status_code == 200
    body = response.json()
    assert body["primary_stream_plane"] == "webrtc"
    assert body["fallback_stream_plane"] == "http_mjpeg_gateway"
    assert body["stream_base_url"] == "http://<vision-host>:8090"
    assert body["fallback_stream_base_url"] == "http://<vision-host>:8090"
    assert body["requested_source"] == "tb3_1_picam"
    assert body["debug_only"] is True
    assert body["topic_exposure_policy"] == expected_ros_topic_exposure_policy()
    assert body["topic_exposure_summary"] == expected_topic_exposure_summary(["tb3_1_picam"])
    assert body["topic_exposure_summary"]["policy_status"] == "safe"
    assert body["topic_exposure_summary"]["policy_violation_count"] == 0
    assert body["summary"] == {
        "sources_total": 1,
        "with_frame_count": 1,
        "with_overlay_count": 1,
        "overlay_lag_count": 0,
        "ros_ingest_contract_ready_count": 1,
        "ros_publish_ready_count": 1,
        "ros_publish_payload_available_count": 1,
        "evidence_event_publish_ready_count": 1,
        "stale_overlay_count": 0,
        "health_status_counts": {"online": 1},
        "ros_ingest_status_counts": {"contract_ready": 1},
        "ros_publish_status_counts": {"ready_fresh": 1},
    }
    assert len(body["sources"]) == 1
    source = body["sources"][0]
    assert source["source"] == "tb3_1_picam"
    assert source["health"]["status"] == "online"
    assert source["latest_frame"]["frame_seq"] == 2
    assert source["latest_frame"]["size_bytes"] > 0
    assert source["latest_overlay"]["frame_seq"] == 2
    assert source["overlay_lag_frames"] == 0
    assert source["topic_exposure"] == expected_source_topic_exposure("tb3_1_picam")
    assert source["topic_exposure"]["control_topics_allowed"] == []
    assert source["topic_exposure"]["client_publish_allowed"] is False
    assert source["rosbridge_subscription_hints"] == expected_rosbridge_subscription_hints(
        "tb3_1_picam"
    )
    assert source["evidence_event_publish_readiness"]["event_available"] is True
    assert source["evidence_event_publish_readiness"]["publish_ready"] is True
    assert source["evidence_event_publish_readiness"]["topic"] == "/sf/vision/events"
    assert source["evidence_event_publish_readiness"]["message_type"] == (
        "smartfactory_msgs/msg/VisionEvent or JSON bridge payload"
    )
    assert source["evidence_event_publish_readiness"]["schema_version"] == "vision-event.v1"
    assert source["evidence_event_publish_readiness"]["latest_event_id"] is not None
    assert source["evidence_event_publish_readiness"]["latest_event_kind"] == "CONFIRMED"
    assert source["evidence_event_publish_readiness"]["latest_event_timestamp"] is not None
    assert source["evidence_event_publish_readiness"]["dedup_key"] == "event_id"
    assert source["evidence_event_publish_readiness"]["payload_contains_image_bytes"] is False
    assert source["evidence_event_publish_readiness"]["policy"] == (
        expected_ros_evidence_event_publish_policy()
    )
    assert source["evidence_event_publish_readiness"]["reason"] == (
        "latest schema-valid VisionEvent is available for future ROS evidence publisher"
    )
    assert source["rosbridge_subscription_hints"]["recommended_overlay_topic"] == (
        "/sf/vision/sources/tb3_1_picam/overlay/compressed"
    )
    assert source["ros_ingest_readiness"] == expected_ros_ingest_readiness("tb3_1_picam")
    assert source["ros_publish_readiness"]["readiness_state"] == "ready_fresh"
    assert source["ros_publish_readiness"]["overlay_ready"] is True
    assert source["ros_publish_readiness"]["latest_frame_seq"] == 2
    assert source["ros_publish_readiness"]["latest_overlay_frame_seq"] == 2
    assert source["ros_publish_readiness"]["overlay_visual_state"] == "fresh"
    assert source["ros_publish_readiness"]["runtime_plan"] == (
        expected_ros_publish_runtime_plan("tb3_1_picam")
    )
    assert source["evidence_event_publish_readiness"]["publish_ready"] is True
    assert source["evidence_event_publish_readiness"]["topic"] == "/sf/vision/events"
    assert source["evidence_event_publish_readiness"]["schema_version"] == "vision-event.v1"
    assert source["evidence_event_publish_readiness"]["latest_event_kind"] == "CONFIRMED"
    assert source["evidence_event_publish_readiness"]["dedup_key"] == "event_id"
    assert source["evidence_event_publish_readiness"]["payload_contains_image_bytes"] is False
    assert source["evidence_event_publish_readiness"]["policy"] == (
        expected_ros_evidence_event_publish_policy()
    )
    assert source["stream_metrics"]["frames_sent_total"] == 1
    assert source["drop_metrics"]["dropped_frames"] == 1
    assert source["default_view"] == "full"
    assert source["available_views"] == ["full"]
    assert source["debug_paths"]["frame_metadata"] == (
        "/api/v1/vision/frame/latest?source=tb3_1_picam"
    )
    assert source["debug_paths"]["frame_image"] == (
        "/api/v1/vision/frame/latest/image?source=tb3_1_picam"
    )
    assert source["debug_paths"]["metrics"] == "/api/v1/metrics?source=tb3_1_picam"
    assert source["debug_paths"]["metrics_all"] == "/api/v1/metrics"
    assert source["debug_paths"]["ros_handoff"] == "/api/v1/vision/ros/topics?source=tb3_1_picam"
    assert source["debug_paths"]["ros_handoff_all"] == "/api/v1/vision/ros/topics"


def test_vision_debug_sources_reports_overlay_lag_before_worker_tick():
    main_module.source_health.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    first = client.post(
        "/api/v1/vision/synthetic/frame",
        json={"source": "tb3_2_picam", "marker_id": 7},
    )
    assert first.status_code == 200
    # Store a newer raw latest frame without rendering a new overlay.
    decoded = main_module.generate_synthetic_aruco_frame(marker_id=8)
    frame = main_module.frame_store.put_decoded(source="tb3_2_picam", image_bgr=decoded)
    main_module.source_health.record_frame("tb3_2_picam", at=main_module._now_dt())
    assert frame.frame_seq == 2

    response = client.get("/api/v1/vision/debug/sources", params={"source": "tb3_2_picam"})

    assert response.status_code == 200
    body = response.json()
    assert body["requested_source"] == "tb3_2_picam"
    assert body["topic_exposure_summary"] == expected_topic_exposure_summary(["tb3_2_picam"])
    assert body["sources"][0]["topic_exposure"] == expected_source_topic_exposure("tb3_2_picam")
    assert body["sources"][0][
        "rosbridge_subscription_hints"
    ] == expected_rosbridge_subscription_hints("tb3_2_picam")
    assert body["summary"]["sources_total"] == 1
    assert body["summary"]["with_frame_count"] == 1
    assert body["summary"]["with_overlay_count"] == 1
    assert body["summary"]["overlay_lag_count"] == 1
    assert body["summary"]["ros_publish_ready_count"] == 0
    assert body["summary"]["ros_publish_payload_available_count"] == 0
    assert body["summary"]["evidence_event_publish_ready_count"] == 1
    assert body["summary"]["health_status_counts"] == {"online": 1}
    assert body["summary"]["ros_ingest_status_counts"] == {"contract_ready": 1}
    assert body["summary"]["ros_publish_status_counts"] == {"overlay_lag": 1}
    source = body["sources"][0]
    assert source["latest_frame"]["frame_seq"] == 2
    assert source["latest_overlay"]["frame_seq"] == 1
    assert source["overlay_lag_frames"] == 1
    assert source["ros_publish_readiness"]["readiness_state"] == "overlay_lag"
    assert source["ros_publish_readiness"]["overlay_ready"] is False
    assert source["ros_publish_readiness"]["latest_frame_seq"] == 2
    assert source["ros_publish_readiness"]["latest_overlay_frame_seq"] == 1
    assert source["evidence_event_publish_readiness"]["publish_ready"] is True


def test_vision_debug_sources_rejects_unknown_source():
    response = client.get("/api/v1/vision/debug/sources", params={"source": "bad_cam"})

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"
