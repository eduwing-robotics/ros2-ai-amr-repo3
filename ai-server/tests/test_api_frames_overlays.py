"""Frame ingest, overlay, synthetic frame, metrics, and Lane B API tests."""

from datetime import datetime, timedelta

from api_test_helpers import (
    aruco_png_bytes,
    client,
    cv2,
    get_settings,
    main_module,
    np,
    pytest,
)


def test_overlay_latest_reports_sync_lag_after_newer_raw_frame():
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
    decoded = main_module.generate_synthetic_aruco_frame(marker_id=8)
    frame = main_module.frame_store.put_decoded(source="tb3_2_picam", image_bgr=decoded)
    main_module.source_health.record_frame("tb3_2_picam", at=main_module._now_dt())
    assert frame.frame_seq == 2

    response = client.get("/api/v1/vision/overlay/latest", params={"source": "tb3_2_picam"})

    assert response.status_code == 200
    body = response.json()
    assert body["requested_source"] == "tb3_2_picam"
    assert body["overlay"]["frame_seq"] == 1
    assert body["sync"] == {
        "latest_frame_seq": 2,
        "latest_overlay_frame_seq": 1,
        "overlay_lag_frames": 1,
        "overlay_visual_state": "fresh",
    }


def test_overlay_latest_returns_404_before_any_frame():
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    response = client.get("/api/v1/vision/overlay/latest", params={"source": "tb3_1_picam"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "NOT_FOUND"


def test_latest_overlay_fails_closed_when_cached_frame_ages_out(monkeypatch):
    from app.api import vision as vision_api

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
    frame = main_module.frame_store.latest("tb3_1_picam")
    assert frame is not None
    future = datetime.fromisoformat(frame.timestamp) + timedelta(
        seconds=get_settings().source_stale_after_s + 1.0
    )
    monkeypatch.setattr(vision_api, "_now_dt", lambda: future)

    metadata = client.get(
        "/api/v1/vision/overlay/latest",
        params={"source": "tb3_1_picam"},
    )
    image = client.get(
        "/api/v1/vision/overlay/latest/image",
        params={"source": "tb3_1_picam"},
    )

    assert metadata.status_code == 200
    assert metadata.json()["overlay"]["stale"] is True
    assert metadata.json()["overlay"]["visual_state"] == "stale"
    assert metadata.json()["sync"]["overlay_visual_state"] == "stale"
    assert image.status_code == 200
    decoded = cv2.imdecode(np.frombuffer(image.content, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    stale_header_pixel = decoded[3, decoded.shape[1] - 10]
    assert int(stale_header_pixel[2]) > 180
    assert int(stale_header_pixel[1]) > 100
    assert int(stale_header_pixel[0]) < 90


def test_overlay_metadata_returns_canvas_layer_events_without_image_bytes():
    main_module.store.reset()
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

    response = client.get(
        "/api/v1/vision/overlay/metadata",
        params={"source": "tb3_1_picam", "view": "full", "limit": 5},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["requested_source"] == "tb3_1_picam"
    assert body["requested_view"] == "full"
    assert body["metadata_plane"] == {
        "kind": "vision_event_canvas_layer_diagnostic",
        "render_target": "diagnostic_canvas_only_public_stream_is_burned_overlay",
        "refresh_fps": 5.0,
        "client_rendering": "diagnostic_only_not_required_for_main_streaming",
        "recommended_for_main_streaming": False,
        "motion_command_allowed": False,
        "db_writes": False,
        "evidence_truth_mutation": False,
    }
    assert body["overlay"]["frame_seq"] == 1
    assert body["events"]
    assert body["events"][0]["source"] == "tb3_1_picam"
    assert body["events"][0]["metadata"]["frame_seq"] == body["overlay"]["frame_seq"]
    assert "jpeg" not in body


def test_overlay_metadata_returns_only_events_for_current_overlay_frame():
    main_module.store.reset()
    main_module.source_health.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    first = client.post(
        "/api/v1/vision/synthetic/frame",
        json={"source": "tb3_1_picam", "marker_id": 7},
    )
    second = client.post(
        "/api/v1/vision/synthetic/frame",
        json={"source": "tb3_1_picam", "marker_id": 8},
    )
    assert first.status_code == 200
    assert second.status_code == 200

    response = client.get(
        "/api/v1/vision/overlay/metadata",
        params={"source": "tb3_1_picam", "view": "full", "limit": 50},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["overlay"]["frame_seq"] == 2
    assert body["events"]
    assert {event["metadata"]["frame_seq"] for event in body["events"]} == {
        body["overlay"]["frame_seq"]
    }


def test_overlay_metadata_for_roi_view_does_not_fallback_to_full_frame_events():
    main_module.store.reset()
    main_module.source_health.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    ingest = client.post(
        "/api/v1/vision/synthetic/frame",
        json={"source": "global_cam_01", "marker_id": 7},
    )
    assert ingest.status_code == 200

    response = client.get(
        "/api/v1/vision/overlay/metadata",
        params={"source": "global_cam_01", "view": "lift_roi", "limit": 50},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["requested_view"] == "lift_roi"
    assert body["events"] == []


def test_lane_b_robot_free_e2e_surfaces_stay_consistent_across_stream_debug_ros_and_metrics():
    main_module.store.reset()
    main_module.source_health.reset()
    main_module.metrics.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    source = "tb3_1_picam"

    initial_stream = client.get("/api/v1/vision/streams", params={"source": source})
    assert initial_stream.status_code == 200
    assert initial_stream.json()["debug_only"] is False
    assert initial_stream.json()["motion_command_allowed"] is False
    assert initial_stream.json()["control_topics_published"] == []
    assert initial_stream.json()["runtime_policy"]["ros2_started_by_http_request"] is False
    assert initial_stream.json()["summary"]["ros_ingest_contract_ready_count"] == 1
    assert initial_stream.json()["summary"]["ros_publish_status_counts"] == {"no_frame": 1}

    ingest = client.post(
        "/api/v1/vision/frame",
        data={"source": source},
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )
    assert ingest.status_code == 200
    assert ingest.json()["processed"] is False
    assert ingest.json()["ingest_context"]["ros_callback_compatible"] is True
    assert ingest.json()["frame"]["frame_seq"] == 1

    pending = client.get("/api/v1/vision/worker/status", params={"source": source})
    assert pending.status_code == 200
    assert pending.json()["summary"]["pending_count"] == 1
    assert pending.json()["summary"]["status_counts"]["processed"] == 1

    before_tick = client.get("/api/v1/vision/streams", params={"source": source})
    assert before_tick.status_code == 200
    before_body = before_tick.json()
    before_source = before_body["sources"][0]
    assert before_body["summary"]["with_frame_count"] == 1
    assert before_body["summary"]["with_overlay_count"] == 0
    assert before_body["summary"]["ros_publish_status_counts"] == {"no_overlay": 1}
    assert before_source["latest_frame_seq"] == 1
    assert before_source["latest_overlay_frame_seq"] is None
    assert before_source["ros_publish_readiness"]["readiness_state"] == "no_overlay"
    assert before_source["evidence_event_publish_readiness"]["publish_ready"] is False

    tick = client.post("/api/v1/vision/worker/tick", json={"source": source})
    assert tick.status_code == 200
    assert tick.json()["summary"]["status_counts"]["processed"] == 1
    assert tick.json()["summary"]["event_count_total"] == 1
    assert tick.json()["results"][0]["overlay"]["frame_seq"] == 1

    latest_events = client.get("/api/v1/detections/latest", params={"source": source, "limit": 1})
    assert latest_events.status_code == 200
    assert latest_events.json()["events"][0]["schema_version"] == "vision-event.v1"
    assert latest_events.json()["events"][0]["source"] == source

    frame_image = client.get("/api/v1/vision/frame/latest/image", params={"source": source})
    overlay = client.get("/api/v1/vision/overlay/latest", params={"source": source})
    overlay_image = client.get("/api/v1/vision/overlay/latest/image", params={"source": source})
    assert frame_image.status_code == 200
    assert frame_image.headers["content-type"] == "image/png"
    assert frame_image.content.startswith(b"\x89PNG")
    assert overlay.status_code == 200
    assert overlay.json()["overlay"]["frame_seq"] == 1
    assert overlay.json()["overlay"]["event_count"] == 1
    assert overlay_image.status_code == 200
    assert overlay_image.content.startswith(b"\xff\xd8")

    stream = client.get("/api/v1/vision/streams", params={"source": source})
    debug = client.get("/api/v1/vision/debug/sources", params={"source": source})
    ros = client.get("/api/v1/vision/ros/topics", params={"source": source})
    metrics_response = client.get("/api/v1/metrics", params={"source": source})
    assert (
        stream.status_code
        == debug.status_code
        == ros.status_code
        == metrics_response.status_code
        == 200
    )

    stream_body = stream.json()
    debug_body = debug.json()
    ros_body = ros.json()
    metrics_body = metrics_response.json()
    stream_source = stream_body["sources"][0]
    debug_source = debug_body["sources"][0]
    ros_source = ros_body["sources"][0]

    assert stream_body["primary_stream_plane"] == ros_body["primary_stream_plane"] == "webrtc"
    assert (
        stream_body["fallback_stream_plane"]
        == ros_body["fallback_stream_plane"]
        == "http_mjpeg_gateway"
    )
    assert (
        stream_body["stream_base_url"] == ros_body["stream_base_url"] == "http://<vision-host>:8090"
    )
    assert (
        stream_body["fallback_stream_base_url"]
        == ros_body["fallback_stream_base_url"]
        == "http://<vision-host>:8090"
    )
    assert stream_body["debug_only"] is False
    assert ros_body["debug_only"] is True
    assert stream_body["motion_command_allowed"] is False
    assert ros_body["motion_command_allowed"] is False
    assert stream_body["control_topics_published"] == ros_body["control_topics_published"] == []
    assert stream_body["runtime_policy"] == ros_body["runtime_policy"]
    assert stream_body["topic_exposure_summary"] == ros_body["topic_exposure_summary"]
    assert debug_body["topic_exposure_summary"] == ros_body["topic_exposure_summary"]

    assert stream_source["latest_frame_seq"] == debug_source["latest_frame"]["frame_seq"] == 1
    assert (
        stream_source["latest_overlay_frame_seq"]
        == debug_source["latest_overlay"]["frame_seq"]
        == 1
    )
    assert stream_source["overlay_lag_frames"] == debug_source["overlay_lag_frames"] == 0
    assert stream_source["ros_ingest_readiness"] == debug_source["ros_ingest_readiness"]
    assert stream_source["ros_ingest_readiness"] == ros_source["ingest_readiness"]

    def without_frame_age(readiness: dict) -> dict:
        return {key: value for key, value in readiness.items() if key != "frame_age_s"}

    assert without_frame_age(stream_source["ros_publish_readiness"]) == without_frame_age(
        debug_source["ros_publish_readiness"]
    )
    assert without_frame_age(stream_source["ros_publish_readiness"]) == without_frame_age(
        ros_source["publish_readiness"]
    )
    assert (
        stream_source["evidence_event_publish_readiness"]
        == debug_source["evidence_event_publish_readiness"]
    )
    assert (
        stream_source["evidence_event_publish_readiness"]
        == ros_source["evidence_event_publish_readiness"]
    )

    assert stream_body["summary"]["ros_publish_payload_available_count"] == 1
    assert debug_body["summary"]["ros_publish_payload_available_count"] == 1
    assert ros_body["publish_readiness_summary"]["publish_payload_available_count"] == 1
    assert stream_body["summary"]["evidence_event_publish_ready_count"] == 1
    assert debug_body["summary"]["evidence_event_publish_ready_count"] == 1
    assert ros_body["evidence_event_publish_readiness_summary"]["publish_ready_count"] == 1
    assert metrics_body["metrics"]["worker"]["tick_total"] == {"processed": 1}
    assert metrics_body["frame_store"]["frame_seq_by_source"] == {source: 1}

    newer_frame = client.post(
        "/api/v1/vision/frame",
        data={"source": source},
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )
    assert newer_frame.status_code == 200
    assert newer_frame.json()["frame"]["frame_seq"] == 2

    lag_stream = client.get("/api/v1/vision/streams", params={"source": source})
    lag_debug = client.get("/api/v1/vision/debug/sources", params={"source": source})
    lag_ros = client.get("/api/v1/vision/ros/topics", params={"source": source})
    assert lag_stream.status_code == lag_debug.status_code == lag_ros.status_code == 200
    lag_stream_source = lag_stream.json()["sources"][0]
    lag_debug_source = lag_debug.json()["sources"][0]
    lag_ros_source = lag_ros.json()["sources"][0]
    assert (
        lag_stream_source["latest_frame_seq"] == lag_debug_source["latest_frame"]["frame_seq"] == 2
    )
    assert (
        lag_stream_source["latest_overlay_frame_seq"]
        == lag_debug_source["latest_overlay"]["frame_seq"]
        == 1
    )
    assert lag_stream_source["overlay_lag_frames"] == lag_debug_source["overlay_lag_frames"] == 1
    assert lag_stream_source["ros_publish_readiness"]["readiness_state"] == "overlay_lag"
    assert lag_debug_source["ros_publish_readiness"]["readiness_state"] == "overlay_lag"
    assert lag_ros_source["publish_readiness"]["readiness_state"] == "overlay_lag"
    assert lag_stream.json()["summary"]["ros_publish_payload_available_count"] == 0
    assert lag_debug.json()["summary"]["ros_publish_payload_available_count"] == 0
    assert lag_ros.json()["publish_readiness_summary"]["publish_payload_available_count"] == 0


def test_lane_b_multi_source_e2e_keeps_frame_overlay_event_and_metrics_isolated():
    main_module.store.reset()
    main_module.source_health.reset()
    main_module.metrics.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    processed_source = "tb3_1_picam"
    waiting_source = "tb3_2_picam"

    first = client.post(
        "/api/v1/vision/frame",
        data={"source": processed_source},
        files={"image": ("tb3_1.png", aruco_png_bytes(), "image/png")},
    )
    second = client.post(
        "/api/v1/vision/frame",
        data={"source": waiting_source},
        files={"image": ("tb3_2.png", aruco_png_bytes(), "image/png")},
    )
    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["frame"]["frame_seq"] == 1
    assert second.json()["frame"]["frame_seq"] == 1

    tick_one = client.post("/api/v1/vision/worker/tick", json={"source": processed_source})
    assert tick_one.status_code == 200
    assert tick_one.json()["summary"]["status_counts"]["processed"] == 1
    assert tick_one.json()["results"][0]["source"] == processed_source
    assert tick_one.json()["results"][0]["overlay"]["frame_seq"] == 1

    stream = client.get("/api/v1/vision/streams")
    debug = client.get("/api/v1/vision/debug/sources")
    ros = client.get("/api/v1/vision/ros/topics")
    assert stream.status_code == debug.status_code == ros.status_code == 200

    stream_body = stream.json()
    debug_body = debug.json()
    ros_body = ros.json()
    stream_by_source = {item["source"]: item for item in stream_body["sources"]}
    debug_by_source = {item["source"]: item for item in debug_body["sources"]}
    ros_by_source = {item["source"]: item for item in ros_body["sources"]}

    assert stream_body["summary"]["sources_total"] == 3
    assert stream_body["summary"]["with_frame_count"] == 2
    assert stream_body["summary"]["with_overlay_count"] == 1
    assert stream_body["summary"]["ros_publish_payload_available_count"] == 1
    assert stream_body["summary"]["ros_publish_payload_blocked_count"] == 2
    assert stream_body["summary"]["evidence_event_publish_ready_count"] == 1
    assert stream_body["summary"]["ros_publish_status_counts"] == {
        "no_frame": 1,
        "no_overlay": 1,
        "ready_fresh": 1,
    }
    assert debug_body["summary"]["with_frame_count"] == 2
    assert debug_body["summary"]["with_overlay_count"] == 1
    assert debug_body["summary"]["ros_publish_payload_available_count"] == 1
    assert debug_body["summary"]["evidence_event_publish_ready_count"] == 1
    assert ros_body["publish_readiness_summary"]["publish_payload_available_count"] == 1
    assert ros_body["publish_readiness_summary"]["publish_payload_blocked_count"] == 2
    assert ros_body["evidence_event_publish_readiness_summary"]["publish_ready_count"] == 1

    processed_stream = stream_by_source[processed_source]
    processed_debug = debug_by_source[processed_source]
    processed_ros = ros_by_source[processed_source]
    waiting_stream = stream_by_source[waiting_source]
    waiting_debug = debug_by_source[waiting_source]
    waiting_ros = ros_by_source[waiting_source]
    empty_stream = stream_by_source["global_cam_01"]

    assert processed_stream["latest_frame_seq"] == processed_debug["latest_frame"]["frame_seq"] == 1
    assert (
        processed_stream["latest_overlay_frame_seq"]
        == processed_debug["latest_overlay"]["frame_seq"]
        == 1
    )
    assert processed_stream["ros_publish_readiness"]["readiness_state"] == "ready_fresh"
    assert processed_debug["ros_publish_readiness"]["readiness_state"] == "ready_fresh"
    assert processed_ros["publish_readiness"]["readiness_state"] == "ready_fresh"
    assert processed_stream["evidence_event_publish_readiness"]["publish_ready"] is True
    assert processed_debug["evidence_event_publish_readiness"]["publish_ready"] is True
    assert processed_ros["evidence_event_publish_readiness"]["publish_ready"] is True

    assert waiting_stream["latest_frame_seq"] == waiting_debug["latest_frame"]["frame_seq"] == 1
    assert waiting_stream["latest_overlay_frame_seq"] is None
    assert waiting_debug["latest_overlay"] is None
    assert waiting_stream["ros_publish_readiness"]["readiness_state"] == "no_overlay"
    assert waiting_debug["ros_publish_readiness"]["readiness_state"] == "no_overlay"
    assert waiting_ros["publish_readiness"]["readiness_state"] == "no_overlay"
    assert waiting_stream["evidence_event_publish_readiness"]["publish_ready"] is False
    assert waiting_debug["evidence_event_publish_readiness"]["publish_ready"] is False
    assert waiting_ros["evidence_event_publish_readiness"]["publish_ready"] is False

    assert empty_stream["has_frame"] is False
    assert empty_stream["has_overlay"] is False
    assert empty_stream["ros_publish_readiness"]["readiness_state"] == "no_frame"
    assert empty_stream["evidence_event_publish_readiness"]["publish_ready"] is False

    processed_metrics = client.get("/api/v1/metrics", params={"source": processed_source})
    waiting_metrics = client.get("/api/v1/metrics", params={"source": waiting_source})
    assert processed_metrics.status_code == 200
    assert waiting_metrics.status_code == 200
    assert processed_metrics.json()["metrics"]["worker"]["tick_total"] == {"processed": 1}
    assert waiting_metrics.json()["metrics"]["worker"]["tick_total"] == {}
    assert processed_metrics.json()["frame_store"]["frame_seq_by_source"] == {processed_source: 1}
    assert waiting_metrics.json()["frame_store"]["frame_seq_by_source"] == {waiting_source: 1}

    tick_waiting = client.post("/api/v1/vision/worker/tick", json={"source": waiting_source})
    assert tick_waiting.status_code == 200
    assert tick_waiting.json()["summary"]["status_counts"]["processed"] == 1
    final_ros = client.get("/api/v1/vision/ros/topics")
    assert final_ros.status_code == 200
    assert final_ros.json()["publish_readiness_summary"]["publish_payload_available_count"] == 2
    assert final_ros.json()["evidence_event_publish_readiness_summary"]["publish_ready_count"] == 2


def test_lane_b_multi_source_latest_only_backpressure_drops_old_frames_per_source():
    main_module.store.reset()
    main_module.source_health.reset()
    main_module.metrics.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    first_source = "tb3_1_picam"
    second_source = "tb3_2_picam"

    for expected_seq in (1, 2, 3):
        response = client.post(
            "/api/v1/vision/frame",
            data={"source": first_source},
            files={"image": (f"{first_source}-{expected_seq}.png", aruco_png_bytes(), "image/png")},
        )
        assert response.status_code == 200
        assert response.json()["frame"]["frame_seq"] == expected_seq

    for expected_seq in (1, 2):
        response = client.post(
            "/api/v1/vision/frame",
            data={"source": second_source},
            files={
                "image": (f"{second_source}-{expected_seq}.png", aruco_png_bytes(), "image/png")
            },
        )
        assert response.status_code == 200
        assert response.json()["frame"]["frame_seq"] == expected_seq

    all_metrics_before = client.get("/api/v1/metrics")
    first_metrics_before = client.get("/api/v1/metrics", params={"source": first_source})
    second_metrics_before = client.get("/api/v1/metrics", params={"source": second_source})
    assert all_metrics_before.status_code == 200
    assert first_metrics_before.status_code == 200
    assert second_metrics_before.status_code == 200
    assert all_metrics_before.json()["frame_store"]["sources_with_frames"] == 2
    assert all_metrics_before.json()["frame_store"]["frame_seq_by_source"] == {
        first_source: 3,
        second_source: 2,
    }
    assert all_metrics_before.json()["frame_store"]["dropped_frames_by_source"] == {
        first_source: 2,
        second_source: 1,
    }
    assert all_metrics_before.json()["frame_store"]["dropped_frames_total"] == 3
    assert first_metrics_before.json()["frame_store"]["frame_seq_by_source"] == {first_source: 3}
    assert first_metrics_before.json()["frame_store"]["dropped_frames_by_source"] == {
        first_source: 2
    }
    assert first_metrics_before.json()["frame_store"]["dropped_frames_total"] == 2
    assert second_metrics_before.json()["frame_store"]["frame_seq_by_source"] == {second_source: 2}
    assert second_metrics_before.json()["frame_store"]["dropped_frames_by_source"] == {
        second_source: 1
    }
    assert second_metrics_before.json()["frame_store"]["dropped_frames_total"] == 1

    before_tick = client.get("/api/v1/vision/streams")
    assert before_tick.status_code == 200
    before_body = before_tick.json()
    assert before_body["summary"]["with_frame_count"] == 2
    assert before_body["summary"]["with_overlay_count"] == 0
    assert before_body["summary"]["ros_publish_status_counts"] == {
        "no_frame": 1,
        "no_overlay": 2,
    }
    assert before_body["summary"]["ros_publish_payload_available_count"] == 0

    tick = client.post("/api/v1/vision/worker/tick", json={})
    assert tick.status_code == 200
    tick_body = tick.json()
    assert tick_body["summary"]["status_counts"]["processed"] == 2
    assert tick_body["summary"]["status_counts"]["no_frame"] == 1
    assert tick_body["summary"]["event_count_total"] == 2
    tick_by_source = {item["source"]: item for item in tick_body["results"]}
    assert tick_by_source[first_source]["frame_seq"] == 3
    assert tick_by_source[first_source]["overlay"]["frame_seq"] == 3
    assert tick_by_source[second_source]["frame_seq"] == 2
    assert tick_by_source[second_source]["overlay"]["frame_seq"] == 2
    assert tick_by_source["global_cam_01"]["status"] == "no_frame"

    stream = client.get("/api/v1/vision/streams")
    debug = client.get("/api/v1/vision/debug/sources")
    ros = client.get("/api/v1/vision/ros/topics")
    assert stream.status_code == debug.status_code == ros.status_code == 200
    stream_body = stream.json()
    debug_body = debug.json()
    ros_body = ros.json()
    stream_by_source = {item["source"]: item for item in stream_body["sources"]}
    debug_by_source = {item["source"]: item for item in debug_body["sources"]}
    ros_by_source = {item["source"]: item for item in ros_body["sources"]}

    assert stream_body["summary"]["ros_publish_payload_available_count"] == 2
    assert stream_body["summary"]["evidence_event_publish_ready_count"] == 2
    assert debug_body["summary"]["ros_publish_payload_available_count"] == 2
    assert debug_body["summary"]["evidence_event_publish_ready_count"] == 2
    assert ros_body["publish_readiness_summary"]["publish_payload_available_count"] == 2
    assert ros_body["evidence_event_publish_readiness_summary"]["publish_ready_count"] == 2
    assert stream_body["summary"]["ros_publish_status_counts"] == {
        "no_frame": 1,
        "ready_fresh": 2,
    }

    for source, expected_seq in ((first_source, 3), (second_source, 2)):
        assert stream_by_source[source]["latest_frame_seq"] == expected_seq
        assert stream_by_source[source]["latest_overlay_frame_seq"] == expected_seq
        assert debug_by_source[source]["latest_frame"]["frame_seq"] == expected_seq
        assert debug_by_source[source]["latest_overlay"]["frame_seq"] == expected_seq
        assert stream_by_source[source]["ros_publish_readiness"]["readiness_state"] == "ready_fresh"
        assert debug_by_source[source]["ros_publish_readiness"]["readiness_state"] == "ready_fresh"
        assert ros_by_source[source]["publish_readiness"]["readiness_state"] == "ready_fresh"
        assert stream_by_source[source]["evidence_event_publish_readiness"]["publish_ready"] is True
        assert debug_by_source[source]["evidence_event_publish_readiness"]["publish_ready"] is True
        assert ros_by_source[source]["evidence_event_publish_readiness"]["publish_ready"] is True

    assert (
        stream_by_source["global_cam_01"]["ros_publish_readiness"]["readiness_state"] == "no_frame"
    )

    newer_first = client.post(
        "/api/v1/vision/frame",
        data={"source": first_source},
        files={"image": ("tb3_1-newer.png", aruco_png_bytes(), "image/png")},
    )
    assert newer_first.status_code == 200
    assert newer_first.json()["frame"]["frame_seq"] == 4

    lag_stream = client.get("/api/v1/vision/streams")
    lag_metrics = client.get("/api/v1/metrics", params={"source": first_source})
    assert lag_stream.status_code == 200
    assert lag_metrics.status_code == 200
    lag_body = lag_stream.json()
    lag_by_source = {item["source"]: item for item in lag_body["sources"]}
    assert lag_metrics.json()["frame_store"]["frame_seq_by_source"] == {first_source: 4}
    assert lag_metrics.json()["frame_store"]["dropped_frames_by_source"] == {first_source: 3}
    assert lag_metrics.json()["frame_store"]["dropped_frames_total"] == 3
    assert lag_by_source[first_source]["latest_frame_seq"] == 4
    assert lag_by_source[first_source]["latest_overlay_frame_seq"] == 3
    assert lag_by_source[first_source]["overlay_lag_frames"] == 1
    assert lag_by_source[first_source]["ros_publish_readiness"]["readiness_state"] == "overlay_lag"
    assert (
        lag_by_source[first_source]["ros_publish_readiness"]["publish_payload_preview"][
            "payload_available"
        ]
        is False
    )
    assert lag_by_source[second_source]["latest_frame_seq"] == 2
    assert lag_by_source[second_source]["latest_overlay_frame_seq"] == 2
    assert lag_by_source[second_source]["ros_publish_readiness"]["readiness_state"] == "ready_fresh"
    assert lag_body["summary"]["ros_publish_payload_available_count"] == 1
    assert lag_body["summary"]["ros_publish_payload_blocked_count"] == 2
    assert lag_body["summary"]["ros_publish_status_counts"] == {
        "no_frame": 1,
        "overlay_lag": 1,
        "ready_fresh": 1,
    }


def test_lane_b_worker_tick_is_idempotent_and_does_not_duplicate_evidence_events():
    main_module.store.reset()
    main_module.source_health.reset()
    main_module.metrics.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    sources = ("tb3_1_picam", "tb3_2_picam")
    for source in sources:
        response = client.post(
            "/api/v1/vision/frame",
            data={"source": source},
            files={"image": (f"{source}.png", aruco_png_bytes(), "image/png")},
        )
        assert response.status_code == 200
        assert response.json()["frame"]["frame_seq"] == 1

    first_tick = client.post("/api/v1/vision/worker/tick", json={})
    assert first_tick.status_code == 200
    first_body = first_tick.json()
    assert first_body["summary"]["status_counts"]["processed"] == 2
    assert first_body["summary"]["status_counts"]["no_frame"] == 1
    assert first_body["summary"]["event_count_total"] == 2
    assert first_body["summary"]["new_event_count_total"] == 2
    assert first_body["summary"]["reused_event_count_total"] == 0
    first_by_source = {item["source"]: item for item in first_body["results"]}
    for source in sources:
        assert first_by_source[source]["status"] == "processed"
        assert first_by_source[source]["evidence_action"] == "created"
        assert first_by_source[source]["new_event_count"] == 1
        assert first_by_source[source]["overlay"]["frame_seq"] == 1

    events_after_first = client.get("/api/v1/detections/latest", params={"limit": 10})
    metrics_after_first = client.get("/api/v1/metrics")
    assert events_after_first.status_code == 200
    assert metrics_after_first.status_code == 200
    first_events = events_after_first.json()["events"]
    first_event_ids = {event["event_id"] for event in first_events}
    assert len(first_events) == 2
    assert {event["source"] for event in first_events} == set(sources)
    assert metrics_after_first.json()["event_store"]["current_size"] == 2

    second_tick = client.post("/api/v1/vision/worker/tick", json={})
    assert second_tick.status_code == 200
    second_body = second_tick.json()
    assert second_body["summary"]["status_counts"]["processed"] == 0
    assert second_body["summary"]["status_counts"]["skipped"] == 2
    assert second_body["summary"]["status_counts"]["no_frame"] == 1
    # event_count_total still describes the events represented by the tick
    # response, while new_event_count_total is the idempotency guard.
    assert second_body["summary"]["event_count_total"] == 2
    assert second_body["summary"]["new_event_count_total"] == 0
    assert second_body["summary"]["reused_event_count_total"] == 2
    second_by_source = {item["source"]: item for item in second_body["results"]}
    for source in sources:
        assert second_by_source[source]["status"] == "skipped"
        assert second_by_source[source]["evidence_action"] == "reused"
        assert second_by_source[source]["new_event_count"] == 0
        assert second_by_source[source]["overlay"]["frame_seq"] == 1

    events_after_second = client.get("/api/v1/detections/latest", params={"limit": 10})
    metrics_after_second = client.get("/api/v1/metrics")
    stream_after_second = client.get("/api/v1/vision/streams")
    ros_after_second = client.get("/api/v1/vision/ros/topics")
    assert events_after_second.status_code == 200
    assert metrics_after_second.status_code == 200
    assert stream_after_second.status_code == 200
    assert ros_after_second.status_code == 200
    second_events = events_after_second.json()["events"]
    assert {event["event_id"] for event in second_events} == first_event_ids
    assert metrics_after_second.json()["event_store"]["current_size"] == 2
    assert metrics_after_second.json()["metrics"]["worker"]["tick_total"] == {
        "no_frame": 2,
        "processed": 2,
        "skipped": 2,
    }
    assert stream_after_second.json()["summary"]["ros_publish_payload_available_count"] == 2
    assert stream_after_second.json()["summary"]["evidence_event_publish_ready_count"] == 2
    assert (
        ros_after_second.json()["publish_readiness_summary"]["publish_payload_available_count"] == 2
    )
    assert (
        ros_after_second.json()["evidence_event_publish_readiness_summary"]["publish_ready_count"]
        == 2
    )


def test_frame_ingest_stores_raw_frame_without_processing_then_worker_tick_processes():
    main_module.source_health.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    ingest = client.post(
        "/api/v1/vision/frame",
        data={"source": "tb3_1_picam"},
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )

    assert ingest.status_code == 200
    body = ingest.json()
    assert body["source"] == "tb3_1_picam"
    assert body["processed"] is False
    assert body["overlay"] is None
    assert body["ingest_context"] == {
        "transport": "http_debug",
        "topic": None,
        "stored_in_latest_frame_cache": True,
        "processed_inline": False,
        "source_health_updated": True,
        "ros_callback_compatible": True,
    }
    assert body["worker_tick_path"] == "/api/v1/vision/worker/tick"
    assert body["frame"]["frame_seq"] == 1
    assert body["frame"]["content_type"] == "image/png"
    assert body["frame"]["size_bytes"] > 0

    overlay_before_tick = client.get(
        "/api/v1/vision/overlay/latest",
        params={"source": "tb3_1_picam"},
    )
    assert overlay_before_tick.status_code == 404

    tick = client.post(
        "/api/v1/vision/worker/tick",
        json={"source": "tb3_1_picam"},
    )
    assert tick.status_code == 200
    tick_result = tick.json()["results"][0]
    assert tick_result["status"] == "processed"
    assert tick_result["frame_seq"] == 1
    assert tick_result["event_count"] == 1
    assert tick_result["overlay"]["frame_seq"] == 1


def test_frame_process_ingests_and_updates_overlay_in_one_request():
    main_module.store.reset()
    main_module.source_health.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    response = client.post(
        "/api/v1/vision/frame/process",
        data={"source": "tb3_1_picam", "force": "true", "stale": "false"},
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "tb3_1_picam"
    assert body["processed"] is True
    assert body["status"] == "processed"
    assert body["frame_seq"] == 1
    assert body["frame"]["frame_seq"] == 1
    assert body["overlay"]["frame_seq"] == 1
    assert body["event_count"] >= 1
    assert body["new_event_count"] == body["event_count"]
    assert body["ingest_context"] == {
        "transport": "http_debug",
        "topic": None,
        "stored_in_latest_frame_cache": True,
        "processed_inline": True,
        "source_health_updated": True,
        "ros_callback_compatible": True,
    }

    latest_overlay = client.get(
        "/api/v1/vision/overlay/latest",
        params={"source": "tb3_1_picam"},
    )
    assert latest_overlay.status_code == 200
    assert latest_overlay.json()["overlay"]["frame_seq"] == 1

    latest_image = client.get(
        "/api/v1/vision/overlay/latest/image",
        params={"source": "tb3_1_picam"},
    )
    assert latest_image.status_code == 200
    assert latest_image.headers["content-type"] == "image/jpeg"
    assert latest_image.content.startswith(b"\xff\xd8")


def test_store_latest_frame_from_bytes_is_ros_callback_ready_without_processing():
    main_module.source_health.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()

    frame = main_module._store_latest_frame_from_bytes(
        source="tb3_2_picam",
        payload=aruco_png_bytes(),
        content_type="image/png",
    )

    assert frame.source == "tb3_2_picam"
    assert frame.frame_seq == 1
    assert frame.content_type == "image/png"
    assert main_module.overlay_cache.latest("tb3_2_picam") is None
    health = main_module.source_health.snapshot(
        "tb3_2_picam",
        now=main_module._now_dt(),
        stale_after_s=get_settings().source_stale_after_s,
        offline_after_s=get_settings().source_offline_after_s,
    )
    assert health.frame_count == 1
    assert health.event_count == 0

    with pytest.raises(ValueError, match="decodable image"):
        main_module._store_latest_frame_from_bytes(
            source="tb3_2_picam",
            payload=b"not-an-image",
            content_type="text/plain",
        )


def test_frame_ingest_rejects_bad_image_and_unknown_source():
    bad_image = client.post(
        "/api/v1/vision/frame",
        data={"source": "tb3_2_picam"},
        files={"image": ("bad.txt", b"not-an-image", "text/plain")},
    )
    bad_source = client.post(
        "/api/v1/vision/frame",
        data={"source": "bad_cam"},
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )

    assert bad_image.status_code == 400
    assert bad_image.json()["error"]["code"] == "BAD_REQUEST"
    assert bad_source.status_code == 400
    assert bad_source.json()["error"]["code"] == "BAD_REQUEST"


def test_latest_frame_metadata_and_image_follow_synthetic_ingest():
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

    metadata_response = client.get(
        "/api/v1/vision/frame/latest",
        params={"source": "tb3_1_picam"},
    )
    assert metadata_response.status_code == 200
    frame = metadata_response.json()["frame"]
    assert frame["source"] == "tb3_1_picam"
    assert frame["frame_seq"] == 1
    assert frame["content_type"] == "image/jpeg"
    assert frame["size_bytes"] > 0
    assert frame["image"]["width"] > 0
    assert frame["image"]["height"] > 0

    image_response = client.get(
        "/api/v1/vision/frame/latest/image",
        params={"source": "tb3_1_picam"},
    )
    assert image_response.status_code == 200
    assert image_response.headers["content-type"] == "image/jpeg"
    assert image_response.content.startswith(b"\xff\xd8")


def test_latest_frame_returns_404_before_any_frame():
    main_module.frame_store.reset()

    metadata_response = client.get(
        "/api/v1/vision/frame/latest",
        params={"source": "tb3_2_picam"},
    )
    image_response = client.get(
        "/api/v1/vision/frame/latest/image",
        params={"source": "tb3_2_picam"},
    )

    assert metadata_response.status_code == 404
    assert metadata_response.json()["error"]["code"] == "NOT_FOUND"
    assert image_response.status_code == 404
    assert image_response.json()["error"]["code"] == "NOT_FOUND"


def test_overlay_publish_payload_preview_only_allows_synced_overlay():
    main_module.source_health.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    no_frame = main_module._overlay_publish_payload_preview_for_source("tb3_1_picam")
    assert no_frame["payload_available"] is False
    assert no_frame["topic"] == "/sf/vision/sources/tb3_1_picam/overlay/compressed"
    assert no_frame["message_type"] == "sensor_msgs/msg/CompressedImage"
    assert no_frame["size_bytes"] == 0

    ingest = client.post(
        "/api/v1/vision/frame",
        data={"source": "tb3_1_picam"},
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )
    assert ingest.status_code == 200
    no_overlay = main_module._overlay_publish_payload_preview_for_source("tb3_1_picam")
    assert no_overlay["payload_available"] is False
    assert no_overlay["frame_seq"] == 1
    assert no_overlay["size_bytes"] == 0

    tick = client.post("/api/v1/vision/worker/tick", json={"source": "tb3_1_picam"})
    assert tick.status_code == 200
    ready = main_module._overlay_publish_payload_preview_for_source("tb3_1_picam")
    assert ready["payload_available"] is True
    assert ready["frame_seq"] == 1
    assert ready["content_type"] == "image/jpeg"
    assert ready["size_bytes"] > 0

    newer = client.post(
        "/api/v1/vision/frame",
        data={"source": "tb3_1_picam"},
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )
    assert newer.status_code == 200
    lagging = main_module._overlay_publish_payload_preview_for_source("tb3_1_picam")
    assert lagging["payload_available"] is False
    assert lagging["frame_seq"] == 1
    assert lagging["size_bytes"] > 0
    assert "does not match" in lagging["reason"]


def test_debug_overlay_mjpeg_rejects_invalid_max_fps_before_streaming():
    too_low = client.get("/api/v1/vision/stream/tb3_1_picam.mjpeg", params={"max_fps": 0})
    too_high = client.get("/api/v1/vision/stream/tb3_1_picam.mjpeg", params={"max_fps": 31})

    assert too_low.status_code == 422
    assert too_low.json()["error"]["code"] == "VALIDATION_ERROR"
    assert too_high.status_code == 422
    assert too_high.json()["error"]["code"] == "VALIDATION_ERROR"


def test_synthetic_frame_ingest_uses_latest_frame_overlay_path():
    main_module.source_health.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    response = client.post(
        "/api/v1/vision/synthetic/frame",
        json={"source": "tb3_2_picam", "marker_id": 9, "stale": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "tb3_2_picam"
    assert body["emitted"] is False
    assert body["emit_disabled"] is False
    assert len(body["events"]) == 1
    assert body["events"][0]["marker_id"] == "ARUCO_4X4_50_9"
    assert body["overlay"]["source"] == "tb3_2_picam"
    assert body["overlay"]["frame_seq"] == 1
    assert body["overlay"]["event_count"] == 1
    assert body["overlay"]["stale"] is True

    latest = client.get("/api/v1/vision/overlay/latest", params={"source": "tb3_2_picam"})
    assert latest.status_code == 200
    assert latest.json()["overlay"]["frame_seq"] == 1


def test_lane_b_api_served_overlay_visual_qa_distinguishes_fresh_and_stale_warning_band():
    main_module.store.reset()
    main_module.source_health.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    fresh = client.post(
        "/api/v1/vision/synthetic/frame",
        json={"source": "tb3_1_picam", "marker_id": 7, "stale": False},
    )
    assert fresh.status_code == 200
    fresh_image = client.get(
        "/api/v1/vision/overlay/latest/image",
        params={"source": "tb3_1_picam"},
    )
    assert fresh_image.status_code == 200
    fresh_decoded = cv2.imdecode(
        np.frombuffer(fresh_image.content, dtype=np.uint8), cv2.IMREAD_COLOR
    )
    assert fresh_decoded is not None

    stale = client.post(
        "/api/v1/vision/synthetic/frame",
        json={"source": "tb3_1_picam", "marker_id": 8, "stale": True},
    )
    assert stale.status_code == 200
    stale_metadata = client.get(
        "/api/v1/vision/overlay/latest",
        params={"source": "tb3_1_picam"},
    )
    stale_image = client.get(
        "/api/v1/vision/overlay/latest/image",
        params={"source": "tb3_1_picam"},
    )
    assert stale_metadata.status_code == 200
    assert stale_metadata.json()["overlay"]["visual_state"] == "stale"
    assert stale_metadata.json()["sync"]["overlay_visual_state"] == "stale"
    assert stale_image.status_code == 200
    stale_decoded = cv2.imdecode(
        np.frombuffer(stale_image.content, dtype=np.uint8), cv2.IMREAD_COLOR
    )
    assert stale_decoded is not None

    # API-served stale overlay must contain the same unmistakable amber header
    # as the renderer unit contract. Sample away from text to avoid anti-aliasing.
    stale_header_pixel = stale_decoded[3, stale_decoded.shape[1] - 10]
    fresh_header_pixel = fresh_decoded[3, fresh_decoded.shape[1] - 10]
    assert int(stale_header_pixel[2]) > 180
    assert int(stale_header_pixel[1]) > 100
    assert int(stale_header_pixel[0]) < 90
    assert np.linalg.norm(stale_header_pixel.astype(float) - fresh_header_pixel.astype(float)) > 100
    assert stale_image.content.startswith(b"\xff\xd8")


def test_synthetic_frame_rejects_unknown_source():
    response = client.post(
        "/api/v1/vision/synthetic/frame",
        json={"source": "bad_cam", "marker_id": 7},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "BAD_REQUEST"


def test_metrics_can_filter_lane_b_source_counters_and_rejects_unknown_source():
    main_module.metrics.reset()
    main_module.frame_store.reset()

    frame = main_module.frame_store.put_decoded(
        source="tb3_1_picam",
        image_bgr=main_module.generate_synthetic_aruco_frame(marker_id=7),
    )
    assert frame.frame_seq == 1
    main_module.frame_store.put_decoded(
        source="tb3_1_picam",
        image_bgr=main_module.generate_synthetic_aruco_frame(marker_id=8),
    )
    main_module.metrics.record_stream_client_opened(source="tb3_1_picam")
    main_module.metrics.record_stream_frame_sent(source="tb3_1_picam")
    main_module.metrics.record_stream_stale_poll(source="tb3_2_picam")
    main_module.metrics.record_worker_tick(source="tb3_1_picam", status="processed")
    main_module.metrics.record_worker_tick(source="tb3_2_picam", status="no_frame")

    response = client.get("/api/v1/metrics", params={"source": "tb3_1_picam"})

    assert response.status_code == 200
    body = response.json()
    assert body["requested_source"] == "tb3_1_picam"
    assert set(body["metrics"]["stream"]["by_source"]) == {"tb3_1_picam"}
    assert body["metrics"]["stream"]["frames_sent_total"] == 1
    assert body["metrics"]["stream"]["stale_polls_total"] == 0
    assert body["metrics"]["worker"]["by_source"] == {"tb3_1_picam": {"processed": 1}}
    assert body["metrics"]["worker"]["tick_total"] == {"processed": 1}
    assert body["frame_store"]["sources_with_frames"] == 1
    assert body["frame_store"]["frame_seq_by_source"] == {"tb3_1_picam": 2}
    assert body["frame_store"]["dropped_frames_by_source"] == {"tb3_1_picam": 1}
    assert body["frame_store"]["dropped_frames_total"] == 1

    empty = client.get("/api/v1/metrics", params={"source": "tb3_2_picam"})
    assert empty.status_code == 200
    assert empty.json()["requested_source"] == "tb3_2_picam"
    assert empty.json()["metrics"]["stream"]["by_source"]["tb3_2_picam"]["frames_sent_total"] == 0
    assert empty.json()["metrics"]["stream"]["stale_polls_total"] == 1
    assert empty.json()["frame_store"]["sources_with_frames"] == 0

    bad = client.get("/api/v1/metrics", params={"source": "bad_cam"})
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "BAD_REQUEST"
