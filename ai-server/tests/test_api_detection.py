"""Health, source, detection, and latest-detection API tests."""

from api_test_helpers import aruco_png_bytes, blank_png_bytes, client, get_settings, main_module


def test_health_exposes_canonical_sources():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["schema_version"] == "vision-event.v1"
    assert body["sources"] == ["global_cam_01", "tb3_1_picam", "tb3_2_picam"]
    assert body["event_retention"]["max_size"] == 200


def test_sources_include_robot_mapping():
    main_module.source_health.reset()
    response = client.get("/api/v1/sources")
    assert response.status_code == 200
    sources = {item["source"]: item for item in response.json()["sources"]}
    assert sources["global_cam_01"]["robot_id"] is None
    assert sources["tb3_1_picam"]["robot_id"] == "tb3_1"
    assert sources["tb3_2_picam"]["robot_id"] == "tb3_2"
    assert sources["tb3_1_picam"]["status"] == "offline"
    assert sources["tb3_1_picam"]["last_frame_at"] is None
    assert sources["tb3_1_picam"]["last_event_at"] is None
    assert sources["tb3_1_picam"]["frame_count"] == 0
    assert sources["tb3_1_picam"]["event_count"] == 0


def test_detect_image_updates_source_health_for_blank_frame():
    main_module.source_health.reset()

    response = client.post(
        "/api/v1/detect/image",
        data={"source": "tb3_1_picam"},
        files={"image": ("frame.png", blank_png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    sources_response = client.get("/api/v1/sources")
    sources = {item["source"]: item for item in sources_response.json()["sources"]}
    tb3_1 = sources["tb3_1_picam"]
    assert tb3_1["status"] == "online"
    assert tb3_1["last_frame_at"] is not None
    assert tb3_1["last_frame_age_s"] is not None
    assert tb3_1["last_event_at"] is None
    assert tb3_1["frame_count"] == 1
    assert tb3_1["event_count"] == 0

    health = client.get("/api/v1/health").json()["source_summary"]
    assert health["configured"] == 3
    assert health["online"] == 1
    assert health["offline"] == 2


def test_detect_image_updates_source_health_for_marker_event():
    main_module.source_health.reset()

    response = client.post(
        "/api/v1/detect/image",
        data={"source": "tb3_1_picam"},
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    event = response.json()["events"][0]
    sources = {item["source"]: item for item in client.get("/api/v1/sources").json()["sources"]}
    tb3_1 = sources["tb3_1_picam"]
    assert tb3_1["status"] == "online"
    assert tb3_1["frame_count"] == 1
    assert tb3_1["event_count"] == 1
    assert tb3_1["last_event_at"] == event["timestamp"]
    assert tb3_1["last_event_id"] == event["event_id"]
    assert tb3_1["last_event_kind"] == "CONFIRMED"
    assert tb3_1["last_marker_id"] == "ARUCO_4X4_50_7"


def test_detect_image_returns_empty_events_for_frame_without_markers():
    response = client.post(
        "/api/v1/detect/image",
        data={"source": "tb3_1_picam"},
        files={"image": ("frame.png", blank_png_bytes(), "image/png")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "tb3_1_picam"
    assert body["emitted"] is False
    assert body["emit_disabled"] is False
    assert body["emit_results"] == []
    assert body["events"] == []


def test_detect_image_returns_contract_valid_marker_event():
    response = client.post(
        "/api/v1/detect/image",
        data={"source": "tb3_1_picam"},
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )
    assert response.status_code == 200
    events = response.json()["events"]
    assert len(events) == 1
    event = events[0]
    assert event["schema_version"] == "vision-event.v1"
    assert event["event_kind"] == "CONFIRMED"
    assert event["class_name"] == "aruco_marker"
    assert event["marker_id"] == "ARUCO_4X4_50_7"
    assert event["source"] == "tb3_1_picam"
    assert event["robot_id"] == "tb3_1"
    assert event["depth_median_m"] is None


def test_detect_image_emit_flag_is_disabled_by_default(monkeypatch):
    async def fail_if_called(*_, **__):
        raise AssertionError("WMS emit should not be called when disabled")

    monkeypatch.setattr(main_module, "emit_vision_events", fail_if_called)
    response = client.post(
        "/api/v1/detect/image",
        data={"source": "tb3_2_picam", "emit": "true"},
        files={"image": ("aruco.png", aruco_png_bytes(9), "image/png")},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "tb3_2_picam"
    assert body["emitted"] is False
    assert body["emit_disabled"] is True
    assert body["emit_results"] == []
    assert len(body["events"]) == 1
    assert body["events"][0]["source"] == "tb3_2_picam"


def test_detect_image_emits_to_wms_when_enabled(monkeypatch):
    monkeypatch.setenv("WMS_EMIT_ENABLED", "true")
    get_settings.cache_clear()

    async def fake_emit(events, *, settings):
        assert settings.wms_emit_enabled is True
        return [
            {
                "event_id": event["event_id"],
                "attempted": True,
                "ok": True,
                "status_code": 202,
                "error": None,
                "response": {
                    "accepted": True,
                    "duplicate": False,
                    "wms_processing_status": "queued",
                },
            }
            for event in events
        ]

    monkeypatch.setattr(main_module, "emit_vision_events", fake_emit)
    try:
        response = client.post(
            "/api/v1/detect/image",
            data={"source": "tb3_1_picam", "emit": "true"},
            files={"image": ("aruco.png", aruco_png_bytes(11), "image/png")},
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    body = response.json()
    assert body["emitted"] is True
    assert body["emit_disabled"] is False
    assert len(body["events"]) == 1
    assert len(body["emit_results"]) == 1
    assert body["emit_results"][0]["event_id"] == body["events"][0]["event_id"]
    assert body["emit_results"][0]["status_code"] == 202


def test_detect_image_reports_wms_failure_without_failing_detection(monkeypatch):
    monkeypatch.setenv("WMS_EMIT_ENABLED", "true")
    get_settings.cache_clear()

    async def fake_emit(events, *, settings):
        return [
            {
                "event_id": event["event_id"],
                "attempted": True,
                "ok": False,
                "status_code": 503,
                "error": "WMS ingest returned HTTP 503",
                "response": None,
            }
            for event in events
        ]

    monkeypatch.setattr(main_module, "emit_vision_events", fake_emit)
    try:
        response = client.post(
            "/api/v1/detect/image",
            data={"source": "tb3_1_picam", "emit": "true"},
            files={"image": ("aruco.png", aruco_png_bytes(12), "image/png")},
        )
    finally:
        get_settings.cache_clear()

    assert response.status_code == 200
    body = response.json()
    assert body["emitted"] is False
    assert len(body["events"]) == 1
    assert body["emit_results"][0]["ok"] is False
    assert body["emit_results"][0]["status_code"] == 503


def test_detect_image_can_emit_aruco_pose_from_named_profile():
    response = client.post(
        "/api/v1/detect/image",
        data={"source": "tb3_1_picam", "pose_profile": "tb3_1_lab_marker_7"},
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    pose = response.json()["events"][0]["pose_estimate"]
    assert pose is not None
    assert pose["method"] == "ARUCO_POSE"
    assert abs(pose["x"]) < 0.02
    assert 0.45 < pose["y"] < 0.60


def test_detect_image_rejects_pose_profile_with_manual_calibration_mix():
    response = client.post(
        "/api/v1/detect/image",
        data={
            "source": "tb3_1_picam",
            "pose_profile": "tb3_1_lab_marker_7",
            "marker_size_m": "0.08",
        },
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )

    assert response.status_code == 400
    assert "pose_profile cannot be combined" in response.json()["error"]["message"]


def test_detect_image_unknown_pose_profile_is_bad_request():
    response = client.post(
        "/api/v1/detect/image",
        data={"source": "tb3_1_picam", "pose_profile": "missing_profile"},
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )

    assert response.status_code == 400
    assert "unknown pose_profile" in response.json()["error"]["message"]


def test_detect_image_pose_profile_marker_mismatch_keeps_pose_null():
    response = client.post(
        "/api/v1/detect/image",
        data={"source": "tb3_1_picam", "pose_profile": "tb3_1_picam_marker_0_placeholder"},
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["events"][0]["marker_id"] == "ARUCO_4X4_50_7"
    assert response.json()["events"][0]["pose_estimate"] is None


def test_detect_image_can_emit_optional_aruco_pose_estimate():
    response = client.post(
        "/api/v1/detect/image",
        data={
            "source": "tb3_1_picam",
            "marker_size_m": "0.08",
            "camera_fx": "600",
            "camera_fy": "600",
            "camera_cx": "80",
            "camera_cy": "80",
            "camera_dist_coeffs": "0,0,0,0,0",
        },
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    events = response.json()["events"]
    assert len(events) == 1
    pose = events[0]["pose_estimate"]
    assert pose is not None
    assert pose["method"] == "ARUCO_POSE"
    assert abs(pose["x"]) < 0.02
    assert 0.45 < pose["y"] < 0.60
    assert abs(pose["yaw"]) < 0.10
    assert 0.0 <= pose["confidence"] <= 1.0


def test_detect_image_rejects_partial_aruco_pose_calibration():
    response = client.post(
        "/api/v1/detect/image",
        data={"source": "tb3_1_picam", "marker_size_m": "0.08"},
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )

    assert response.status_code == 400
    assert "ArUco pose requires" in response.json()["error"]["message"]


def test_detect_image_rejects_invalid_pose_numbers():
    response = client.post(
        "/api/v1/detect/image",
        data={
            "source": "tb3_1_picam",
            "marker_size_m": "-0.08",
            "camera_fx": "600",
            "camera_fy": "600",
            "camera_cx": "80",
            "camera_cy": "80",
        },
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )

    assert response.status_code == 400
    assert response.json()["error"]["message"] == "marker_size_m must be positive"


def test_invalid_image_rejected():
    response = client.post(
        "/api/v1/detect/image",
        data={"source": "tb3_1_picam"},
        files={"image": ("frame.jpg", b"fake-image-bytes", "image/jpeg")},
    )
    assert response.status_code == 400


def test_latest_detections_can_filter_by_source():
    client.post(
        "/api/v1/detect/image",
        data={"source": "global_cam_01"},
        files={"image": ("aruco.png", aruco_png_bytes(8), "image/png")},
    )
    response = client.get(
        "/api/v1/detections/latest", params={"source": "global_cam_01", "limit": 5}
    )
    assert response.status_code == 200
    events = response.json()["events"]
    assert events
    assert all(event["source"] == "global_cam_01" for event in events)


def test_unknown_source_rejected():
    response = client.post(
        "/api/v1/detect/image",
        data={"source": "bad_cam"},
        files={"image": ("frame.png", blank_png_bytes(width=32, height=32), "image/png")},
    )
    assert response.status_code == 400


def test_detect_image_populates_overlay_metadata_and_image():
    main_module.source_health.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    response = client.post(
        "/api/v1/detect/image",
        data={"source": "tb3_1_picam"},
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    overlay_response = client.get("/api/v1/vision/overlay/latest", params={"source": "tb3_1_picam"})
    assert overlay_response.status_code == 200
    overlay_body = overlay_response.json()
    assert overlay_body["requested_source"] == "tb3_1_picam"
    assert overlay_body["sync"] == {
        "latest_frame_seq": 1,
        "latest_overlay_frame_seq": 1,
        "overlay_lag_frames": 0,
        "overlay_visual_state": "fresh",
    }
    overlay = overlay_body["overlay"]
    assert overlay["source"] == "tb3_1_picam"
    assert overlay["frame_seq"] == 1
    assert overlay["frame_timestamp"] is not None
    assert overlay["evidence_timestamp"] == response.json()["events"][0]["timestamp"]
    assert overlay["event_count"] == 1
    assert overlay["stale"] is False

    image_response = client.get(
        "/api/v1/vision/overlay/latest/image",
        params={"source": "tb3_1_picam"},
    )
    assert image_response.status_code == 200
    assert image_response.headers["content-type"] == "image/jpeg"
    assert image_response.content.startswith(b"\xff\xd8")
