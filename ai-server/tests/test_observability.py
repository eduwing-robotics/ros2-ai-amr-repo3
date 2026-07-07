from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient
from generated_fixtures import aruco_png_bytes, blank_png_bytes

from app import runtime_routes as main_module
from app.main import app

client = TestClient(app)


def test_request_id_is_echoed_and_written_to_structured_log(caplog):
    main_module.metrics.reset()
    caplog.set_level(logging.INFO, logger="smartfactory.ai_server")

    response = client.get("/api/v1/health", headers={"X-Request-ID": "req-test-001"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] == "req-test-001"
    log_payloads = [
        json.loads(record.message)
        for record in caplog.records
        if record.name == "smartfactory.ai_server"
    ]
    assert log_payloads
    assert log_payloads[-1]["event"] == "http_request"
    assert log_payloads[-1]["request_id"] == "req-test-001"
    assert log_payloads[-1]["method"] == "GET"
    assert log_payloads[-1]["path"] == "/api/v1/health"
    assert log_payloads[-1]["status_code"] == 200


def test_metrics_endpoint_reports_http_detection_and_retention_counters():
    main_module.metrics.reset()
    main_module.store.reset()
    main_module.frame_store.reset()

    response = client.post(
        "/api/v1/detect/image",
        data={"source": "tb3_1_picam"},
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )
    assert response.status_code == 200

    metrics_response = client.get("/api/v1/metrics")
    assert metrics_response.status_code == 200
    body = metrics_response.json()

    assert body["event_store"]["current_size"] == 1
    assert body["event_store"]["max_size"] == 200
    assert body["frame_store"]["sources_with_frames"] == 1
    assert body["frame_store"]["dropped_frames_total"] == 0
    assert body["metrics"]["http"]["request_total"] == 1
    assert body["metrics"]["http"]["status_total"]["200"] == 1
    assert {
        "method": "POST",
        "path": "/api/v1/detect/image",
        "count": 1,
    } in body["metrics"]["http"]["route_total"]
    assert body["metrics"]["detect_image"]["calls_total"] == 1
    assert body["metrics"]["detect_image"]["events_total"] == 1


def test_metrics_counts_blank_detection_without_legacy_lift_roi_route():
    main_module.metrics.reset()
    main_module.store.reset()

    detect_response = client.post(
        "/api/v1/detect/image",
        data={"source": "tb3_1_picam"},
        files={"image": ("blank.png", blank_png_bytes(), "image/png")},
    )
    assert detect_response.status_code == 200

    body = client.get("/api/v1/metrics").json()
    assert body["metrics"]["http"]["request_total"] == 1
    assert body["metrics"]["detect_image"] == {"calls_total": 1, "events_total": 0}
    assert body["metrics"]["lift_roi"]["evaluations_total"] == 0


def test_metrics_report_lane_b_worker_stream_and_drop_counters():
    main_module.metrics.reset()
    main_module.store.reset()
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

    skipped = client.post(
        "/api/v1/vision/worker/tick",
        json={"source": "tb3_1_picam"},
    )
    assert skipped.status_code == 200
    assert skipped.json()["results"][0]["status"] == "skipped"

    main_module.metrics.record_stream_client_opened(source="tb3_1_picam")
    main_module.metrics.record_stream_frame_sent(source="tb3_1_picam")
    main_module.metrics.record_stream_frame_sent(source="tb3_1_picam")
    main_module.metrics.record_stream_stale_poll(source="tb3_1_picam")
    main_module.metrics.record_stream_client_closed(source="tb3_1_picam")

    body = client.get("/api/v1/metrics").json()
    frame_store = body["frame_store"]
    assert frame_store["frame_seq_by_source"]["tb3_1_picam"] == 2
    assert frame_store["dropped_frames_by_source"]["tb3_1_picam"] == 1
    assert frame_store["dropped_frames_total"] == 1

    stream = body["metrics"]["stream"]["by_source"]["tb3_1_picam"]
    assert stream["clients_total"] == 1
    assert stream["active_clients"] == 0
    assert stream["frames_sent_total"] == 2
    assert stream["stale_polls_total"] == 1
    assert "approx_fps" in stream

    worker = body["metrics"]["worker"]
    assert worker["tick_total"]["skipped"] == 1
    assert worker["by_source"]["tb3_1_picam"]["skipped"] == 1


def test_streams_endpoint_includes_debug_stream_metrics_pointer_and_snapshot():
    main_module.metrics.reset()
    main_module.metrics.record_stream_client_opened(source="tb3_2_picam")
    main_module.metrics.record_stream_frame_sent(source="tb3_2_picam")

    response = client.get("/api/v1/vision/streams")

    assert response.status_code == 200
    body = response.json()
    assert body["debug_fallback"]["metrics_path"] == "/api/v1/metrics"
    sources = {item["source"]: item for item in body["sources"]}
    assert sources["tb3_2_picam"]["stream_metrics"]["clients_total"] == 1
    assert sources["tb3_2_picam"]["stream_metrics"]["frames_sent_total"] == 1
    main_module.metrics.record_stream_client_closed(source="tb3_2_picam")


def test_metrics_endpoint_reports_webrtc_offer_fallback_and_drop_counters():
    main_module.metrics.reset()

    main_module.metrics.record_webrtc_offer(
        source="global_cam_01",
        status="fallback_required",
        reason="sidecar_not_configured",
    )
    main_module.metrics.record_webrtc_selected_transport(
        source="global_cam_01",
        transport="mjpeg",
    )
    main_module.metrics.record_webrtc_fallback(
        source="global_cam_01",
        reason="sidecar_not_configured",
    )
    main_module.metrics.record_webrtc_connection_drop(source="global_cam_01")

    body = client.get("/api/v1/metrics").json()
    webrtc = body["metrics"]["webrtc"]
    assert webrtc["offers_total"] == 1
    assert webrtc["offer_status_total"] == {"fallback_required": 1}
    assert webrtc["offer_reason_total"] == {"sidecar_not_configured": 1}
    assert webrtc["selected_transport_total"] == {"mjpeg": 1}
    assert webrtc["fallback_total"] == 1
    assert webrtc["fallback_reason_total"] == {"sidecar_not_configured": 1}
    assert webrtc["connection_drop_total"] == 1
    assert webrtc["connection_drop_by_source"] == {"global_cam_01": 1}
