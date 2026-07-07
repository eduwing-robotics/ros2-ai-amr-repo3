"""Vision stream and ROS handoff read-model API tests."""

import json
import time
from pathlib import Path

from api_test_helpers import (
    aruco_png_bytes,
    client,
    expected_ros_evidence_event_publish_policy,
    expected_ros_ingest_readiness,
    expected_ros_overlay_publish_policy,
    expected_ros_overlay_publish_qos_policy,
    expected_ros_publish_runtime_plan,
    expected_ros_topic_exposure_policy,
    expected_rosbridge_subscription_hints,
    expected_source_topic_exposure,
    expected_topic_exposure_summary,
    get_settings,
    main_module,
    source_definition,
)

from app.api.vision_read_model_streams import webrtc_sidecar_descriptor
from app.config import REPO_ROOT


def _transport(source: dict, *, kind: str, view: str) -> dict:
    for item in source["stream_transports"]:
        if item["kind"] == kind and item["view"] == view:
            return item
    raise AssertionError(f"missing {kind} transport for view={view}")


def _mark_compositor_alive(monkeypatch, tmp_path, source: str, view: str = "full") -> None:
    """Make the compositor heartbeat gate pass for WebRTC readiness tests."""

    settings = get_settings()
    monkeypatch.setattr(settings, "vision_webrtc_compositor_metrics_dir", tmp_path)
    monkeypatch.setattr(
        settings,
        "vision_webrtc_compositor_publisher_streams",
        f"{source}/{view}",
    )
    (tmp_path / f"{source}_{view}.json").write_text(
        json.dumps({"status": "running", "updated_at_epoch_s": time.time()}),
        encoding="utf-8",
    )


def test_webrtc_compositor_metrics_path_resolves_relative_env_to_repo_root(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(
        settings, "vision_webrtc_compositor_metrics_dir", Path(".run/vision/compositor-metrics")
    )
    monkeypatch.setattr(settings, "vision_webrtc_sidecar_streams", "global_cam_01/full")
    monkeypatch.setattr(
        settings, "vision_webrtc_compositor_publisher_streams", "global_cam_01/full"
    )
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_whep_url_template",
        "http://smartfactory-vision.local:8889/{source}_{view}/whep",
    )

    descriptor = webrtc_sidecar_descriptor("global_cam_01", "full")

    assert descriptor["compositor_metrics_path"] == str(
        REPO_ROOT / ".run" / "vision" / "compositor-metrics" / "global_cam_01_full.json"
    )


def test_vision_streams_declares_http_gateway_primary_and_internal_rosbridge_policy():
    main_module.store.reset()
    main_module.source_health.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    response = client.get("/api/v1/vision/streams")

    assert response.status_code == 200
    body = response.json()
    assert body["requested_source"] is None
    assert body["summary"]["sources_total"] == 3
    assert body["summary"]["ros_ingest_contract_ready_count"] == 3
    assert body["summary"]["ros_ingest_runtime_subscriber_active_count"] == 0
    assert body["summary"]["ros_ingest_status_counts"] == {"contract_ready": 3}
    assert body["summary"]["ros_publish_ready_count"] == 0
    assert body["summary"]["ros_publish_payload_available_count"] == 0
    assert body["summary"]["ros_publish_payload_blocked_count"] == 3
    assert body["summary"]["ros_publish_status_counts"] == {"no_frame": 3}
    assert body["summary"]["evidence_event_publish_ready_count"] == 0
    assert body["primary_stream_plane"] == "webrtc"
    assert body["fallback_stream_plane"] == "http_mjpeg_gateway"
    assert body["candidate_stream_plane"] == "webrtc"
    assert body["stream_base_url"] == "http://<vision-host>:8090"
    assert body["fallback_stream_base_url"] == "http://<vision-host>:8090"
    assert body["debug_only"] is False
    assert body["internal_rosbridge"] == {
        "scope": "operator_prototype_only",
        "url": "ws://<vision-host>:9090",
        "exposes_all_topics": False,
    }
    assert body["motion_command_allowed"] is False
    assert body["control_topics_published"] == []
    assert body["webrtc_policy"]["status"] == "primary_with_mjpeg_fallback"
    assert body["webrtc_policy"]["primary_until_parity"] == "raw_frame_compositor_h264_webrtc"
    assert body["webrtc_policy"]["production_compatible_fallback"] == "http_mjpeg_gateway"
    assert body["webrtc_policy"]["primary_stream_plane"] == "webrtc"
    assert body["webrtc_policy"]["fallback_stream_plane"] == "http_mjpeg_gateway"
    assert body["webrtc_policy"]["preferred_order"] == [
        "raw_frame_compositor_h264_webrtc",
        "http_mjpeg_gateway",
    ]
    assert body["webrtc_policy"]["legacy_or_internal_only"] == [
        "direct_clean_media_webrtc",
        "camera_input_h264_transcode_webrtc",
        "mjpeg_overlay_h264_transcode_webrtc",
        "client_canvas_metadata_overlay",
    ]
    assert body["webrtc_policy"]["transport_rank_order"] == "lower_is_preferred"
    assert body["webrtc_policy"]["promotion_gate"] == {
        "requires_backward_compatible_fields": True,
        "requires_health_check": True,
        "requires_latency_or_quality_evidence": True,
        "must_keep_mjpeg_fallback": True,
    }
    assert body["webrtc_policy"]["current_webrtc_transport_origin"] == (
        "vision_pc_compositor_publisher"
    )
    assert body["webrtc_policy"]["target_webrtc_transport_origin"] == (
        "vision_pc_compositor_publisher"
    )
    assert body["webrtc_policy"]["target_webrtc_video_composition"] == "burned_overlay_video"
    assert body["webrtc_policy"]["overlay_strategy"] == {
        "preferred": "burned_in_video",
        "metadata_endpoint": "/api/v1/vision/overlay/metadata?source={source}&view={view}",
        "metadata_endpoint_role": "diagnostic_only_not_required_for_main_streaming",
        "ai_refresh_fps": 5.0,
        "video_refresh_fps_target": 30,
        "fallback": "http_mjpeg_overlay",
    }
    assert body["webrtc_policy"]["media_only"] is True
    assert body["webrtc_policy"]["motion_command_allowed"] is False
    assert body["webrtc_policy"]["control_topics_published"] == []
    assert body["topic_exposure_policy"] == expected_ros_topic_exposure_policy()
    assert body["topic_exposure_summary"] == expected_topic_exposure_summary(
        ["global_cam_01", "tb3_1_picam", "tb3_2_picam"]
    )
    assert body["topic_exposure_summary"]["policy_status"] == "safe"
    assert body["runtime_policy"] == {
        "ros2_started_by_http_request": False,
        "recommended_executor": "MultiThreadedExecutor",
        "http_handlers_must_spin_ros2_executor": False,
        "threading_model": "ROS2 executor outside FastAPI request handlers with lock-protected latest-frame handoff",
    }
    assert body["debug_fallback"]["mjpeg_path_template"] == "/api/v1/vision/stream/{source}.mjpeg"
    assert body["debug_fallback"]["mjpeg_max_fps_default"] == 10
    assert body["debug_fallback"]["mjpeg_max_fps_limit"] == 30
    assert (
        body["debug_fallback"]["frame_metadata_path"]
        == "/api/v1/vision/frame/latest?source={source}"
    )
    assert (
        body["debug_fallback"]["frame_image_path"]
        == "/api/v1/vision/frame/latest/image?source={source}"
    )
    assert body["debug_fallback"]["ros_handoff_path"] == "/api/v1/vision/ros/topics"
    assert {item["source"] for item in body["sources"]} == {
        "global_cam_01",
        "tb3_1_picam",
        "tb3_2_picam",
    }
    sources = {item["source"]: item for item in body["sources"]}
    global_source = sources["global_cam_01"]
    assert global_source["available_views"] == list(source_definition("global_cam_01").view_ids)
    assert global_source["budgets"] == {
        "target_fps_semantics": "legacy_ai_ingest_default",
        "preview_media_fps": 30.0,
        "ai_monitor_fps": 5.0,
        "evidence_imgsz": 960,
        "browser_primary_transport_semantics": "legacy_internal_rosbridge_metadata",
    }
    assert len(global_source["stream_transports"]) == 2 * len(
        source_definition("global_cam_01").view_ids
    )
    mjpeg = _transport(global_source, kind="mjpeg", view="full")
    assert mjpeg["status"] == "fallback_stable"
    assert mjpeg["path"] == (
        "/api/v1/vision/overlay/stream?source=global_cam_01&view=full&max_fps=30"
    )
    assert mjpeg["url"] == (
        "http://<vision-host>:8090/api/v1/vision/overlay/stream?"
        "source=global_cam_01&view=full&max_fps=30"
    )
    assert mjpeg["transport_origin"] == "http_mjpeg_gateway"
    assert mjpeg["transport_class"] == "http_mjpeg_gateway"
    assert mjpeg["transport_rank"] == 2
    assert mjpeg["transport_rank_order"] == "lower_is_preferred"
    assert mjpeg["production_compatible_fallback"] is True
    webrtc = _transport(global_source, kind="webrtc", view="full")
    assert webrtc["status"] == "candidate"
    assert webrtc["offer_path"] == ("/api/v1/vision/streams/global_cam_01/webrtc/offer?view=full")
    assert webrtc["fallback_path"] == mjpeg["path"]
    assert webrtc["clean_video_path"] == (
        "/api/v1/vision/frame/stream?source=global_cam_01&view=full&max_fps=30"
    )
    assert webrtc["clean_video_url"] == (
        "http://<vision-host>:8090/api/v1/vision/frame/stream?"
        "source=global_cam_01&view=full&max_fps=30"
    )
    assert webrtc["clean_video_role"] == (
        "diagnostic_latest_frame_only_not_main_streaming_overlay_contract"
    )
    assert webrtc["transport_origin"] == "vision_pc_compositor_publisher"
    assert webrtc["transport_class"] == "raw_frame_compositor_h264_webrtc"
    assert webrtc["transport_rank"] == 1
    assert webrtc["transport_rank_order"] == "lower_is_preferred"
    assert webrtc["preferred_until_direct_media_ready"] is False
    assert webrtc["video_composition"] == "burned_overlay_video"
    assert webrtc["overlay_mode"] == "burned_in_video"
    assert webrtc["overlay_metadata"] == {
        "kind": "vision_event_canvas_layer_diagnostic",
        "path": "/api/v1/vision/overlay/metadata?source=global_cam_01&view=full&limit=20",
        "url": (
            "http://<vision-host>:8100/api/v1/vision/overlay/metadata?"
            "source=global_cam_01&view=full&limit=20"
        ),
        "events_path": "/api/v1/detections/latest?source=global_cam_01&limit=20",
        "events_url": (
            "http://<vision-host>:8100/api/v1/detections/latest?source=global_cam_01&limit=20"
        ),
        "recommended_refresh_fps": 5.0,
        "video_frame_reference": "latest_frame_seq",
        "client_rendering": "diagnostic_only_not_required_for_main_streaming",
        "recommended_for_main_streaming": False,
        "diagnostic_only": True,
    }
    assert webrtc["media_only"] is True
    assert webrtc["sidecar_required"] is True
    assert webrtc["sidecar"]["status"] == "not_configured"
    assert webrtc["sidecar"]["compositor_required"] is True
    assert webrtc["sidecar"]["compositor_runtime_health"] == "not_configured"
    assert webrtc["motion_command_allowed"] is False
    assert webrtc["control_topics_published"] == []


def test_vision_streams_can_filter_one_source_and_rejects_unknown_source():
    main_module.store.reset()
    main_module.source_health.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    response = client.get("/api/v1/vision/streams", params={"source": "tb3_1_picam"})

    assert response.status_code == 200
    body = response.json()
    assert body["requested_source"] == "tb3_1_picam"
    assert body["summary"]["sources_total"] == 1
    assert body["summary"]["with_frame_count"] == 0
    assert body["summary"]["with_overlay_count"] == 0
    assert body["summary"]["ros_ingest_contract_ready_count"] == 1
    assert body["summary"]["ros_ingest_runtime_subscriber_active_count"] == 0
    assert body["summary"]["ros_ingest_status_counts"] == {"contract_ready": 1}
    assert body["summary"]["ros_publish_ready_count"] == 0
    assert body["summary"]["ros_publish_payload_available_count"] == 0
    assert body["summary"]["ros_publish_payload_blocked_count"] == 1
    assert body["summary"]["ros_publish_status_counts"] == {"no_frame": 1}
    assert body["summary"]["evidence_event_publish_ready_count"] == 0
    assert body["primary_stream_plane"] == "webrtc"
    assert body["fallback_stream_plane"] == "http_mjpeg_gateway"
    assert body["stream_base_url"] == "http://<vision-host>:8090"
    assert body["fallback_stream_base_url"] == "http://<vision-host>:8090"
    assert body["debug_only"] is False
    assert body["motion_command_allowed"] is False
    assert body["control_topics_published"] == []
    assert [item["source"] for item in body["sources"]] == ["tb3_1_picam"]
    source = body["sources"][0]
    assert source["mjpeg_path"] == "/api/v1/vision/stream/tb3_1_picam.mjpeg"
    assert source["default_view"] == "full"
    assert source["available_views"] == ["full"]
    assert source["budgets"] == {
        "target_fps_semantics": "legacy_ai_ingest_default",
        "preview_media_fps": 30.0,
        "ai_monitor_fps": 10.0,
        "evidence_imgsz": None,
        "browser_primary_transport_semantics": "legacy_internal_rosbridge_metadata",
    }
    assert source["frame_metadata_path"] == "/api/v1/vision/frame/latest?source=tb3_1_picam"
    assert source["overlay_metadata_path"] == "/api/v1/vision/overlay/latest?source=tb3_1_picam"
    assert source["metrics_path"] == "/api/v1/metrics?source=tb3_1_picam"
    assert source["ros_handoff_path"] == "/api/v1/vision/ros/topics"
    assert source["ros_handoff_source_path"] == "/api/v1/vision/ros/topics?source=tb3_1_picam"
    assert len(source["stream_transports"]) == 2
    mjpeg = _transport(source, kind="mjpeg", view="full")
    assert mjpeg == {
        "kind": "mjpeg",
        "status": "fallback_stable",
        "source": "tb3_1_picam",
        "view": "full",
        "url": (
            "http://<vision-host>:8090/api/v1/vision/overlay/stream?"
            "source=tb3_1_picam&view=full&max_fps=30"
        ),
        "path": "/api/v1/vision/overlay/stream?source=tb3_1_picam&view=full&max_fps=30",
        "fallback_path": ("/api/v1/vision/overlay/stream?source=tb3_1_picam&view=full&max_fps=30"),
        "transport_origin": "http_mjpeg_gateway",
        "transport_class": "http_mjpeg_gateway",
        "transport_rank": 2,
        "transport_rank_order": "lower_is_preferred",
        "production_compatible_fallback": True,
        "media_only": True,
        "db_writes": False,
        "evidence_truth_mutation": False,
        "motion_command_allowed": False,
        "control_topics_published": [],
    }
    webrtc = _transport(source, kind="webrtc", view="full")
    assert webrtc["configured"] is False
    assert webrtc["healthy"] is False
    assert webrtc["status"] == "candidate"
    assert webrtc["source"] == "tb3_1_picam"
    assert webrtc["view"] == "full"
    assert webrtc["signaling"] == "http-post-offer-or-sidecar-whep"
    assert webrtc["offer_path"] == "/api/v1/vision/streams/tb3_1_picam/webrtc/offer?view=full"
    assert webrtc["fallback_path"] == mjpeg["path"]
    assert webrtc["fallback_kind"] == "mjpeg"
    assert webrtc["clean_video_path"] == (
        "/api/v1/vision/frame/stream?source=tb3_1_picam&view=full&max_fps=30"
    )
    assert webrtc["clean_video_role"] == (
        "diagnostic_latest_frame_only_not_main_streaming_overlay_contract"
    )
    assert webrtc["transport_origin"] == "vision_pc_compositor_publisher"
    assert webrtc["transport_class"] == "raw_frame_compositor_h264_webrtc"
    assert webrtc["transport_rank"] == 1
    assert webrtc["video_composition"] == "burned_overlay_video"
    assert webrtc["overlay_mode"] == "burned_in_video"
    assert webrtc["legacy_clean_video_config_ignored"] is False
    assert webrtc["legacy_direct_media_config_ignored"] is False
    assert webrtc["overlay_metadata"] == {
        "kind": "vision_event_canvas_layer_diagnostic",
        "path": "/api/v1/vision/overlay/metadata?source=tb3_1_picam&view=full&limit=20",
        "url": (
            "http://<vision-host>:8100/api/v1/vision/overlay/metadata?"
            "source=tb3_1_picam&view=full&limit=20"
        ),
        "events_path": "/api/v1/detections/latest?source=tb3_1_picam&limit=20",
        "events_url": (
            "http://<vision-host>:8100/api/v1/detections/latest?source=tb3_1_picam&limit=20"
        ),
        "recommended_refresh_fps": 5.0,
        "video_frame_reference": "latest_frame_seq",
        "client_rendering": "diagnostic_only_not_required_for_main_streaming",
        "recommended_for_main_streaming": False,
        "diagnostic_only": True,
    }
    assert webrtc["media_only"] is True
    assert webrtc["sidecar_required"] is True
    assert webrtc["sidecar"] | {"compositor_metrics_path": "<path>"} == {
        "status": "not_configured",
        "path_id": "tb3_1_picam_full",
        "url_configured": False,
        "stream_configured": True,
        "configured_streams": [],
        "compositor_required": True,
        "compositor_configured_streams": [],
        "compositor_metrics_path": "<path>",
        "compositor_heartbeat_max_age_s": 5.0,
        "runtime_health": "not_configured",
        "runtime_health_url": None,
        "offer_url": None,
        "whep_url": None,
        "browser_url": None,
        "owner": "media_sidecar",
        "proxy_mode": "descriptor_only",
        "answer_capable": False,
        "path_runtime_health": "not_configured",
        "compositor_runtime_health": "not_configured",
    }
    assert webrtc["motion_command_allowed"] is False
    assert webrtc["control_topics_published"] == []
    assert body["topic_exposure_summary"] == expected_topic_exposure_summary(["tb3_1_picam"])
    assert body["runtime_policy"]["ros2_started_by_http_request"] is False
    assert body["runtime_policy"]["http_handlers_must_spin_ros2_executor"] is False
    assert source["topic_exposure"] == expected_source_topic_exposure("tb3_1_picam")
    assert source["rosbridge_subscription_hints"] == expected_rosbridge_subscription_hints(
        "tb3_1_picam"
    )
    assert source["ros_ingest_readiness"] == expected_ros_ingest_readiness("tb3_1_picam")
    assert source["ros_publish_readiness"]["readiness_state"] == "no_frame"
    assert source["ros_publish_readiness"]["overlay_ready"] is False
    assert source["ros_publish_readiness"]["publish_payload_preview"] == {
        "payload_available": False,
        "topic": "/sf/vision/sources/tb3_1_picam/overlay/compressed",
        "message_type": "sensor_msgs/msg/CompressedImage",
        "frame_seq": None,
        "content_type": None,
        "size_bytes": 0,
        "reason": "no latest frame has been ingested",
    }
    assert source["ros_publish_readiness"]["runtime_plan"] == (
        expected_ros_publish_runtime_plan("tb3_1_picam")
    )
    assert source["evidence_event_publish_readiness"] == {
        "event_available": False,
        "publish_ready": False,
        "topic": "/sf/vision/events",
        "message_type": "smartfactory_msgs/msg/VisionEvent or JSON bridge payload",
        "schema_version": None,
        "latest_event_id": None,
        "latest_event_kind": None,
        "latest_event_timestamp": None,
        "dedup_key": "event_id",
        "payload_contains_image_bytes": False,
        "policy": expected_ros_evidence_event_publish_policy(),
        "reason": "no VisionEvent is available for this source",
    }

    bad = client.get("/api/v1/vision/streams", params={"source": "bad_cam"})
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "BAD_REQUEST"


def test_stream_transport_ranking_metadata_is_policy_consistent():
    response = client.get("/api/v1/vision/streams", params={"source": "global_cam_01"})

    assert response.status_code == 200
    body = response.json()
    preferred_order = body["webrtc_policy"]["preferred_order"]
    assert body["webrtc_policy"]["transport_rank_order"] == "lower_is_preferred"
    expected_ranks = {name: index + 1 for index, name in enumerate(preferred_order)}
    source = body["sources"][0]

    fallback_seen = False
    for transport in source["stream_transports"]:
        transport_class = transport["transport_class"]
        assert transport_class in preferred_order
        assert transport["transport_rank_order"] == "lower_is_preferred"
        assert transport["transport_rank"] == expected_ranks[transport_class]
        if transport_class == "http_mjpeg_gateway":
            fallback_seen = True
            assert transport["production_compatible_fallback"] is True
    assert fallback_seen is True


def test_webrtc_offer_endpoint_is_media_only_and_forced_fallback_records_metrics():
    main_module.metrics.reset()
    main_module.store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    before_store_size = len(main_module.store)
    response = client.post(
        "/api/v1/vision/streams/global_cam_01/webrtc/offer",
        params={"view": "full"},
        json={"type": "offer", "sdp": "v=0", "force_fallback": True},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == "global_cam_01"
    assert body["view"] == "full"
    assert body["status"] == "fallback_required"
    assert body["reason"] == "forced_fallback"
    assert body["selected_transport"] == "mjpeg"
    assert body["media_only"] is True
    assert body["motion_command_allowed"] is False
    assert body["control_topics_published"] == []
    assert body["fallback"] == {
        "kind": "mjpeg",
        "path": "/api/v1/vision/overlay/stream?source=global_cam_01&view=full&max_fps=30",
        "url": (
            "http://<vision-host>:8090/api/v1/vision/overlay/stream?"
            "source=global_cam_01&view=full&max_fps=30"
        ),
    }
    assert body["side_effects"] == {
        "db_writes": False,
        "evidence_truth_mutated": False,
        "ros_control_published": False,
        "ros_topics_started_by_http_request": False,
    }
    assert len(main_module.store) == before_store_size
    assert main_module.overlay_cache.latest("global_cam_01") is None

    metrics = client.get(
        "/api/v1/metrics",
        params={"source": "global_cam_01"},
    ).json()["metrics"]["webrtc"]
    assert metrics["offers_total"] == 1
    assert metrics["offer_status_total"] == {"fallback_required": 1}
    assert metrics["selected_transport_total"] == {"mjpeg": 1}
    assert metrics["fallback_total"] == 1
    assert metrics["fallback_reason_total"] == {"forced_fallback": 1}
    assert metrics["connection_drop_total"] == 0


def test_webrtc_offer_endpoint_selects_webrtc_when_sidecar_descriptor_is_configured(
    monkeypatch, tmp_path
):
    from app.api import vision as vision_api

    main_module.metrics.reset()
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_whep_url_template",
        "http://media-sidecar.local/{source}/{view}/whep",
    )
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_browser_url_template",
        "http://media-sidecar.local/{source}_{view}",
    )
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_assume_healthy_without_health_url",
        True,
    )
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_paths_api_url",
        "http://media-sidecar.local/v3/paths/list",
    )
    _mark_compositor_alive(monkeypatch, tmp_path, "global_cam_01")

    path_payload = {
        "items": [
            {
                "name": "global_cam_01_full",
                "ready": True,
                "available": True,
                "online": True,
            }
        ]
    }

    answer_sdp = "v=0\r\ns=answer\r\nt=0 0\r\n"

    def fake_urlopen(request, timeout):
        url = getattr(request, "full_url", str(request))
        if url.endswith("/whep"):
            assert getattr(request, "data", b"") == b"v=0"
            return _FakeUrlResponse(
                answer_sdp.encode("utf-8"),
                status=201,
                headers={
                    "Content-Type": "application/sdp",
                    "Location": "/global_cam_01/full/whep/session/test",
                },
            )
        return _FakeUrlResponse(json.dumps(path_payload).encode("utf-8"))

    monkeypatch.setattr(vision_api, "urlopen", fake_urlopen)

    response = client.post(
        "/api/v1/vision/streams/global_cam_01/webrtc/offer",
        params={"view": "full"},
        json={"type": "offer", "sdp": "v=0"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "sidecar_configured"
    assert body["reason"] == "sidecar_path_online_compositor_alive"
    assert body["selected_transport"] == "webrtc"
    assert body["type"] == "answer"
    assert body["sdp"] == answer_sdp
    assert body["whep_proxy"] == {
        "ok": True,
        "reason": "whep_answer_created",
        "status_code": 201,
        "session_url": "/global_cam_01/full/whep/session/test",
    }
    assert body["sidecar"]["status"] == "configured"
    assert body["sidecar"]["runtime_health"] == "assume_healthy"
    assert body["sidecar"]["path_runtime_health"] == "online"
    assert body["sidecar"]["compositor_runtime_health"] == "alive"
    assert body["sidecar"]["proxy_mode"] == "whep_proxy"
    assert body["sidecar"]["whep_url"] == ("http://media-sidecar.local/global_cam_01/full/whep")
    assert body["sidecar"]["browser_url"] == ("http://media-sidecar.local/global_cam_01_full")
    assert body["media_only"] is True
    assert body["motion_command_allowed"] is False
    assert body["control_topics_published"] == []
    assert body["side_effects"]["db_writes"] is False
    assert body["side_effects"]["evidence_truth_mutated"] is False
    assert body["side_effects"]["ros_control_published"] is False
    assert body["side_effects"]["ros_topics_started_by_http_request"] is False

    metrics = client.get(
        "/api/v1/metrics",
        params={"source": "global_cam_01"},
    ).json()["metrics"]["webrtc"]
    assert metrics["offers_total"] == 1
    assert metrics["offer_status_total"] == {"sidecar_configured": 1}
    assert metrics["selected_transport_total"] == {"webrtc": 1}
    assert metrics["fallback_total"] == 0


class _FakeUrlResponse:
    def __init__(
        self,
        payload: bytes = b"ok",
        status: int = 200,
        headers: dict[str, str] | None = None,
    ):
        self._payload = payload
        self.status = status
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._payload


def test_webrtc_offer_accepts_any_mediamtx_path_readiness_marker(monkeypatch, tmp_path):
    """MediaMTX readiness fields vary by version; any true marker is enough."""

    from app.api import vision as vision_api

    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_whep_url_template",
        "http://media-sidecar.local/{source}_{view}/whep",
    )
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_browser_url_template",
        "http://media-sidecar.local/{source}_{view}",
    )
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_assume_healthy_without_health_url",
        True,
    )
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_paths_api_url",
        "http://media-sidecar.local/v3/paths/list",
    )
    _mark_compositor_alive(monkeypatch, tmp_path, "global_cam_01")

    for marker in ("ready", "available", "online", "sourceReady"):
        main_module.metrics.reset()
        path_payload = {
            "items": [
                {
                    "name": "global_cam_01_full",
                    marker: True,
                }
            ]
        }

        def fake_urlopen(request, timeout):
            return _FakeUrlResponse(json.dumps(path_payload).encode("utf-8"))

        monkeypatch.setattr(vision_api, "urlopen", fake_urlopen)

        response = client.post(
            "/api/v1/vision/streams/global_cam_01/webrtc/offer",
            params={"view": "full"},
            json={"type": "offer"},
        )

        assert response.status_code == 200
        body = response.json()
        assert body["selected_transport"] == "webrtc", marker
        assert body["reason"] == "sidecar_path_online_compositor_alive", marker
        assert body["sidecar"]["path_runtime_health"] == "online", marker
        assert body["sidecar"]["compositor_runtime_health"] == "alive", marker


def test_webrtc_offer_checks_mediamtx_path_before_selecting_webrtc(monkeypatch, tmp_path):
    from app.api import vision as vision_api

    main_module.metrics.reset()
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_whep_url_template",
        "http://media-sidecar.local/{source}_{view}/whep",
    )
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_browser_url_template",
        "http://media-sidecar.local/{source}_{view}",
    )
    monkeypatch.setattr(settings, "vision_webrtc_sidecar_health_url", "http://media-sidecar.local/")
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_paths_api_url",
        "http://media-sidecar.local/v3/paths/list",
    )
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_streams",
        "tb3_1_picam/full,tb3_2_picam/full",
    )
    _mark_compositor_alive(monkeypatch, tmp_path, "tb3_1_picam")

    path_payload = {
        "items": [
            {
                "name": "tb3_1_picam_full",
                "ready": True,
                "available": True,
                "online": True,
            }
        ]
    }

    def fake_urlopen(request, timeout):
        url = getattr(request, "full_url", str(request))
        if url.endswith("/v3/paths/list"):
            return _FakeUrlResponse(json.dumps(path_payload).encode("utf-8"))
        return _FakeUrlResponse()

    monkeypatch.setattr(vision_api, "urlopen", fake_urlopen)

    online = client.post(
        "/api/v1/vision/streams/tb3_1_picam/webrtc/offer",
        params={"view": "full"},
        json={"type": "offer"},
    ).json()
    missing = client.post(
        "/api/v1/vision/streams/tb3_2_picam/webrtc/offer",
        params={"view": "full"},
        json={"type": "offer"},
    ).json()

    assert online["selected_transport"] == "webrtc"
    assert online["reason"] == "sidecar_path_online_compositor_alive"
    assert online["sidecar"]["path_runtime_health"] == "online"
    assert online["sidecar"]["compositor_runtime_health"] == "alive"
    assert online["sidecar"]["path_id"] == "tb3_1_picam_full"
    assert missing["selected_transport"] == "mjpeg"
    assert missing["reason"] == "sidecar_path_missing"
    assert missing["sidecar"]["path_runtime_health"] == "missing"


def test_webrtc_offer_falls_back_when_whep_proxy_rejects_offer(monkeypatch, tmp_path):
    from urllib.error import HTTPError

    from app.api import vision as vision_api

    main_module.metrics.reset()
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_whep_url_template",
        "http://media-sidecar.local/{source}_{view}/whep",
    )
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_browser_url_template",
        "http://media-sidecar.local/{source}_{view}",
    )
    monkeypatch.setattr(settings, "vision_webrtc_sidecar_health_url", "http://media-sidecar.local/")
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_paths_api_url",
        "http://media-sidecar.local/v3/paths/list",
    )
    _mark_compositor_alive(monkeypatch, tmp_path, "global_cam_01")

    path_payload = {
        "items": [
            {
                "name": "global_cam_01_full",
                "ready": True,
                "available": True,
                "online": True,
            }
        ]
    }

    def fake_urlopen(request, timeout):
        url = getattr(request, "full_url", str(request))
        if url.endswith("/v3/paths/list"):
            return _FakeUrlResponse(json.dumps(path_payload).encode("utf-8"))
        if url.endswith("/whep"):
            raise HTTPError(url, 400, "invalid SDP", {}, None)
        return _FakeUrlResponse()

    monkeypatch.setattr(vision_api, "urlopen", fake_urlopen)

    response = client.post(
        "/api/v1/vision/streams/global_cam_01/webrtc/offer",
        params={"view": "full"},
        json={"type": "offer", "sdp": "not-a-valid-offer"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "fallback_required"
    assert body["reason"] == "whep_proxy_http_400"
    assert body["selected_transport"] == "mjpeg"
    assert body["sidecar"]["proxy_mode"] == "whep_proxy_failed"
    assert body["sidecar"]["whep_proxy_status_code"] == 400
    assert "whep_proxy_error" not in body["sidecar"]
    assert "sdp" not in body


def test_webrtc_offer_falls_back_when_whep_returns_non_sdp_success(monkeypatch, tmp_path):
    from app.api import vision as vision_api

    main_module.metrics.reset()
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_whep_url_template",
        "http://media-sidecar.local/{source}_{view}/whep",
    )
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_browser_url_template",
        "http://media-sidecar.local/{source}_{view}",
    )
    monkeypatch.setattr(settings, "vision_webrtc_sidecar_health_url", "http://media-sidecar.local/")
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_paths_api_url",
        "http://media-sidecar.local/v3/paths/list",
    )
    _mark_compositor_alive(monkeypatch, tmp_path, "global_cam_01")

    path_payload = {
        "items": [
            {
                "name": "global_cam_01_full",
                "ready": True,
                "available": True,
                "online": True,
            }
        ]
    }

    def fake_urlopen(request, timeout):
        url = getattr(request, "full_url", str(request))
        if url.endswith("/v3/paths/list"):
            return _FakeUrlResponse(json.dumps(path_payload).encode("utf-8"))
        if url.endswith("/whep"):
            return _FakeUrlResponse(
                b"<html>not sdp</html>",
                status=200,
                headers={"Content-Type": "text/html"},
            )
        return _FakeUrlResponse()

    monkeypatch.setattr(vision_api, "urlopen", fake_urlopen)

    response = client.post(
        "/api/v1/vision/streams/global_cam_01/webrtc/offer",
        params={"view": "full"},
        json={"type": "offer", "sdp": "v=0"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "fallback_required"
    assert body["reason"] == "whep_proxy_unexpected_status_200"
    assert body["selected_transport"] == "mjpeg"
    assert body["sidecar"]["proxy_mode"] == "whep_proxy_failed"
    assert body["sidecar"]["whep_proxy_status_code"] == 200
    assert "whep_proxy_error" not in body["sidecar"]
    assert "sdp" not in body


def test_webrtc_offer_falls_back_when_whep_returns_empty_or_invalid_sdp(monkeypatch, tmp_path):
    from app.api import vision as vision_api

    main_module.metrics.reset()
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_whep_url_template",
        "http://media-sidecar.local/{source}_{view}/whep",
    )
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_browser_url_template",
        "http://media-sidecar.local/{source}_{view}",
    )
    monkeypatch.setattr(settings, "vision_webrtc_sidecar_health_url", "http://media-sidecar.local/")
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_paths_api_url",
        "http://media-sidecar.local/v3/paths/list",
    )
    _mark_compositor_alive(monkeypatch, tmp_path, "global_cam_01")

    path_payload = {
        "items": [
            {
                "name": "global_cam_01_full",
                "ready": True,
                "available": True,
                "online": True,
            }
        ]
    }
    whep_calls = 0

    def fake_urlopen(request, timeout):
        nonlocal whep_calls
        url = getattr(request, "full_url", str(request))
        if url.endswith("/v3/paths/list"):
            return _FakeUrlResponse(json.dumps(path_payload).encode("utf-8"))
        if url.endswith("/whep"):
            whep_calls += 1
            if whep_calls == 1:
                return _FakeUrlResponse(
                    b"",
                    status=201,
                    headers={"Content-Type": "application/sdp"},
                )
            return _FakeUrlResponse(
                b"not sdp",
                status=201,
                headers={"Content-Type": "application/sdp"},
            )
        return _FakeUrlResponse()

    monkeypatch.setattr(vision_api, "urlopen", fake_urlopen)

    empty = client.post(
        "/api/v1/vision/streams/global_cam_01/webrtc/offer",
        params={"view": "full"},
        json={"type": "offer", "sdp": "v=0"},
    ).json()
    invalid = client.post(
        "/api/v1/vision/streams/global_cam_01/webrtc/offer",
        params={"view": "full"},
        json={"type": "offer", "sdp": "v=0"},
    ).json()

    assert empty["status"] == "fallback_required"
    assert empty["reason"] == "whep_proxy_empty_answer"
    assert "sdp" not in empty
    assert "whep_proxy_error" not in empty["sidecar"]
    assert invalid["status"] == "fallback_required"
    assert invalid["reason"] == "whep_proxy_invalid_answer"
    assert "sdp" not in invalid
    assert "whep_proxy_error" not in invalid["sidecar"]


def test_webrtc_offer_endpoint_falls_back_when_sidecar_health_is_unknown(monkeypatch):
    main_module.metrics.reset()
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_whep_url_template",
        "http://media-sidecar.local/{source}_{view}/whep",
    )
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_browser_url_template",
        "http://media-sidecar.local/{source}_{view}",
    )

    response = client.post(
        "/api/v1/vision/streams/global_cam_01/webrtc/offer",
        params={"view": "full"},
        json={"type": "offer", "sdp": "v=0"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "fallback_required"
    assert body["reason"] == "sidecar_health_unknown"
    assert body["selected_transport"] == "mjpeg"
    assert body["sidecar"]["url_configured"] is True
    assert body["sidecar"]["runtime_health"] == "unknown"


def test_stream_discovery_exposes_sidecar_browser_url_when_configured(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_whep_url_template",
        "http://media-sidecar.local/{source}_{view}/whep",
    )
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_browser_url_template",
        "http://media-sidecar.local/{source}_{view}",
    )

    response = client.get("/api/v1/vision/streams", params={"source": "global_cam_01"})

    assert response.status_code == 200
    webrtc = _transport(response.json()["sources"][0], kind="webrtc", view="full")
    assert webrtc["sidecar"]["status"] == "configured"
    assert webrtc["sidecar"]["whep_url"] == "http://media-sidecar.local/global_cam_01_full/whep"
    assert webrtc["sidecar"]["browser_url"] == "http://media-sidecar.local/global_cam_01_full"
    assert webrtc["sidecar"]["answer_capable"] is True
    assert webrtc["media_only"] is True
    assert webrtc["motion_command_allowed"] is False
    assert webrtc["control_topics_published"] == []


def test_stream_discovery_ignores_legacy_clean_or_direct_media_overlay_configs(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_whep_url_template",
        "http://media-sidecar.local/{source}_{view}/whep",
    )
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_browser_url_template",
        "http://media-sidecar.local/{source}_{view}",
    )
    monkeypatch.setattr(
        settings,
        "vision_webrtc_clean_video_streams",
        "global_cam_01/full,tb3_1_picam/full",
    )
    monkeypatch.setattr(
        settings,
        "vision_webrtc_direct_media_streams",
        "global_cam_01/full",
    )

    global_response = client.get("/api/v1/vision/streams", params={"source": "global_cam_01"})
    tb3_response = client.get("/api/v1/vision/streams", params={"source": "tb3_1_picam"})

    assert global_response.status_code == 200
    assert tb3_response.status_code == 200
    global_webrtc = _transport(global_response.json()["sources"][0], kind="webrtc", view="full")
    tb3_webrtc = _transport(tb3_response.json()["sources"][0], kind="webrtc", view="full")

    assert global_webrtc["transport_origin"] == "vision_pc_compositor_publisher"
    assert global_webrtc["transport_class"] == "raw_frame_compositor_h264_webrtc"
    assert global_webrtc["transport_rank"] == 1
    assert global_webrtc["video_composition"] == "burned_overlay_video"
    assert global_webrtc["overlay_mode"] == "burned_in_video"
    assert global_webrtc["legacy_clean_video_config_ignored"] is True
    assert global_webrtc["legacy_direct_media_config_ignored"] is True
    assert global_webrtc["overlay_metadata"]["path"] == (
        "/api/v1/vision/overlay/metadata?source=global_cam_01&view=full&limit=20"
    )
    assert global_webrtc["overlay_metadata"]["recommended_refresh_fps"] == 5.0
    assert global_webrtc["overlay_metadata"]["diagnostic_only"] is True

    assert tb3_webrtc["transport_origin"] == "vision_pc_compositor_publisher"
    assert tb3_webrtc["transport_class"] == "raw_frame_compositor_h264_webrtc"
    assert tb3_webrtc["transport_rank"] == 1
    assert tb3_webrtc["video_composition"] == "burned_overlay_video"
    assert tb3_webrtc["overlay_mode"] == "burned_in_video"
    assert tb3_webrtc["legacy_clean_video_config_ignored"] is True
    assert tb3_webrtc["legacy_direct_media_config_ignored"] is False


def test_stream_discovery_marks_webrtc_ready_when_sidecar_path_is_online(monkeypatch, tmp_path):
    from app.api import vision_read_model_streams as streams_api

    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_whep_url_template",
        "http://media-sidecar.local/{source}_{view}/whep",
    )
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_browser_url_template",
        "http://media-sidecar.local/{source}_{view}",
    )
    monkeypatch.setattr(settings, "vision_webrtc_sidecar_health_url", "http://media-sidecar.local/")
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_paths_api_url",
        "http://media-sidecar.local/v3/paths/list",
    )
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_streams",
        "global_cam_01/full",
    )
    _mark_compositor_alive(monkeypatch, tmp_path, "global_cam_01")

    path_payload = {
        "items": [
            {
                "name": "global_cam_01_full",
                "ready": True,
                "available": True,
                "online": True,
            }
        ]
    }

    def fake_urlopen(request, timeout):
        url = getattr(request, "full_url", str(request))
        if url.endswith("/v3/paths/list"):
            return _FakeUrlResponse(json.dumps(path_payload).encode("utf-8"))
        return _FakeUrlResponse()

    monkeypatch.setattr(streams_api, "urlopen", fake_urlopen)

    response = client.get(
        "/api/v1/vision/streams",
        params={"source": "global_cam_01", "view": "full"},
    )

    assert response.status_code == 200
    webrtc = _transport(response.json()["sources"][0], kind="webrtc", view="full")
    assert webrtc["configured"] is True
    assert webrtc["healthy"] is True
    assert webrtc["status"] == "ready"
    assert webrtc["sidecar"]["status"] == "healthy"
    assert webrtc["sidecar"]["answer_capable"] is True
    assert webrtc["sidecar"]["runtime_health"] == "healthy"
    assert webrtc["sidecar"]["path_runtime_health"] == "online"
    assert webrtc["sidecar"]["compositor_runtime_health"] == "alive"


def test_stream_discovery_accepts_mediamtx_source_ready_marker(monkeypatch, tmp_path):
    from app.api import vision_read_model_streams as streams_api

    settings = get_settings()
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_whep_url_template",
        "http://media-sidecar.local/{source}_{view}/whep",
    )
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_browser_url_template",
        "http://media-sidecar.local/{source}_{view}",
    )
    monkeypatch.setattr(settings, "vision_webrtc_sidecar_health_url", "http://media-sidecar.local/")
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_paths_api_url",
        "http://media-sidecar.local/v3/paths/list",
    )
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_streams",
        "tb3_1_picam/full",
    )
    _mark_compositor_alive(monkeypatch, tmp_path, "tb3_1_picam")

    path_payload = {"items": [{"name": "tb3_1_picam_full", "sourceReady": True}]}

    def fake_urlopen(request, timeout):
        url = getattr(request, "full_url", str(request))
        if url.endswith("/v3/paths/list"):
            return _FakeUrlResponse(json.dumps(path_payload).encode("utf-8"))
        return _FakeUrlResponse()

    monkeypatch.setattr(streams_api, "urlopen", fake_urlopen)

    response = client.get(
        "/api/v1/vision/streams",
        params={"source": "tb3_1_picam", "view": "full"},
    )

    assert response.status_code == 200
    webrtc = _transport(response.json()["sources"][0], kind="webrtc", view="full")
    assert webrtc["healthy"] is True
    assert webrtc["status"] == "ready"
    assert webrtc["sidecar"]["path_runtime_health"] == "online"
    assert webrtc["sidecar"]["compositor_runtime_health"] == "alive"


def test_stream_discovery_does_not_mark_browser_only_sidecar_ready(monkeypatch):
    from app.api import vision_read_model_streams as streams_api

    settings = get_settings()
    monkeypatch.setattr(settings, "vision_webrtc_sidecar_whep_url_template", "")
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_browser_url_template",
        "http://media-sidecar.local/{source}_{view}",
    )
    monkeypatch.setattr(settings, "vision_webrtc_sidecar_health_url", "http://media-sidecar.local/")
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_paths_api_url",
        "http://media-sidecar.local/v3/paths/list",
    )
    monkeypatch.setattr(
        settings,
        "vision_webrtc_sidecar_streams",
        "global_cam_01/full",
    )

    path_payload = {
        "items": [
            {
                "name": "global_cam_01_full",
                "ready": True,
                "available": True,
                "online": True,
            }
        ]
    }

    def fake_urlopen(request, timeout):
        url = getattr(request, "full_url", str(request))
        if url.endswith("/v3/paths/list"):
            return _FakeUrlResponse(json.dumps(path_payload).encode("utf-8"))
        return _FakeUrlResponse()

    monkeypatch.setattr(streams_api, "urlopen", fake_urlopen)

    response = client.get(
        "/api/v1/vision/streams",
        params={"source": "global_cam_01", "view": "full"},
    )

    assert response.status_code == 200
    webrtc = _transport(response.json()["sources"][0], kind="webrtc", view="full")
    assert webrtc["configured"] is False
    assert webrtc["healthy"] is False
    assert webrtc["status"] == "candidate"
    assert webrtc["sidecar"]["status"] == "configured"
    assert webrtc["sidecar"]["answer_capable"] is False
    assert webrtc["sidecar"]["runtime_health"] == "healthy"
    assert webrtc["sidecar"]["path_runtime_health"] == "online"


def test_webrtc_demo_page_prefers_webrtc_and_contains_mjpeg_fallback_path():
    response = client.get(
        "/api/v1/vision/webrtc/demo",
        params={"source": "global_cam_01", "view": "full", "force_fallback": True},
    )

    assert response.status_code == 200
    assert "RTCPeerConnection" in response.text
    assert "/api/v1/vision/streams/global_cam_01/webrtc/offer?view=full" in response.text
    assert (
        "/api/v1/vision/overlay/metadata?source=global_cam_01&view=full&limit=20" in response.text
    )
    assert "overlayCanvas" in response.text
    assert "burned-overlay WebRTC" in response.text
    assert "Canvas metadata is diagnostic-only" in response.text
    assert (
        "/api/v1/vision/overlay/stream?source=global_cam_01&amp;view=full&amp;max_fps=30"
        not in response.text
    )
    assert (
        "/api/v1/vision/overlay/stream?source=global_cam_01&view=full&max_fps=30" in response.text
    )


def test_vision_streams_reports_frame_overlay_lag_status():
    main_module.store.reset()
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

    before_tick = client.get("/api/v1/vision/streams", params={"source": "tb3_1_picam"})
    assert before_tick.status_code == 200
    source_before = before_tick.json()["sources"][0]
    assert source_before["latest_frame_seq"] == 1
    assert source_before["latest_overlay_frame_seq"] is None
    assert source_before["overlay_lag_frames"] is None
    assert source_before["overlay_visual_state"] is None
    assert before_tick.json()["summary"]["with_frame_count"] == 1
    assert before_tick.json()["summary"]["with_overlay_count"] == 0
    assert before_tick.json()["summary"]["overlay_lag_count"] == 0
    assert before_tick.json()["summary"]["ros_ingest_contract_ready_count"] == 1
    assert before_tick.json()["summary"]["ros_ingest_runtime_subscriber_active_count"] == 0
    assert before_tick.json()["summary"]["ros_ingest_status_counts"] == {"contract_ready": 1}
    assert source_before["ros_ingest_readiness"]["readiness_state"] == "contract_ready"
    assert source_before["ros_ingest_readiness"]["runtime_subscriber_active"] is False
    assert before_tick.json()["summary"]["ros_publish_ready_count"] == 0
    assert before_tick.json()["summary"]["ros_publish_payload_available_count"] == 0
    assert before_tick.json()["summary"]["ros_publish_payload_blocked_count"] == 1
    assert before_tick.json()["summary"]["ros_publish_status_counts"] == {"no_overlay": 1}
    assert source_before["ros_publish_readiness"]["readiness_state"] == "no_overlay"
    assert source_before["ros_publish_readiness"]["overlay_ready"] is False
    assert (
        source_before["ros_publish_readiness"]["publish_payload_preview"]["payload_available"]
        is False
    )

    tick = client.post("/api/v1/vision/worker/tick", json={"source": "tb3_1_picam"})
    assert tick.status_code == 200

    synced = client.get("/api/v1/vision/streams", params={"source": "tb3_1_picam"})
    assert synced.status_code == 200
    source_synced = synced.json()["sources"][0]
    assert source_synced["latest_frame_seq"] == 1
    assert source_synced["latest_overlay_frame_seq"] == 1
    assert source_synced["overlay_lag_frames"] == 0
    assert source_synced["overlay_visual_state"] == "fresh"
    assert synced.json()["summary"]["with_frame_count"] == 1
    assert synced.json()["summary"]["with_overlay_count"] == 1
    assert synced.json()["summary"]["synced_overlay_count"] == 1
    assert synced.json()["summary"]["ros_publish_ready_count"] == 1
    assert synced.json()["summary"]["ros_publish_payload_available_count"] == 1
    assert synced.json()["summary"]["ros_publish_payload_blocked_count"] == 0
    assert synced.json()["summary"]["ros_publish_status_counts"] == {"ready_fresh": 1}
    assert synced.json()["summary"]["evidence_event_publish_ready_count"] == 1
    assert source_synced["ros_publish_readiness"]["readiness_state"] == "ready_fresh"
    assert source_synced["ros_publish_readiness"]["overlay_ready"] is True
    assert (
        source_synced["ros_publish_readiness"]["publish_payload_preview"]["payload_available"]
        is True
    )
    assert source_synced["ros_publish_readiness"]["publish_payload_preview"]["topic"] == (
        "/sf/vision/sources/tb3_1_picam/overlay/compressed"
    )
    assert source_synced["ros_publish_readiness"]["runtime_plan"] == (
        expected_ros_publish_runtime_plan("tb3_1_picam")
    )
    assert source_synced["evidence_event_publish_readiness"]["publish_ready"] is True
    assert source_synced["evidence_event_publish_readiness"]["schema_version"] == "vision-event.v1"

    newer = client.post(
        "/api/v1/vision/frame",
        data={"source": "tb3_1_picam"},
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )
    assert newer.status_code == 200

    lagging = client.get("/api/v1/vision/streams", params={"source": "tb3_1_picam"})
    assert lagging.status_code == 200
    source_lagging = lagging.json()["sources"][0]
    assert source_lagging["latest_frame_seq"] == 2
    assert source_lagging["latest_overlay_frame_seq"] == 1
    assert source_lagging["overlay_lag_frames"] == 1
    assert source_lagging["overlay_visual_state"] == "fresh"
    assert lagging.json()["summary"]["overlay_lag_count"] == 1
    assert lagging.json()["summary"]["synced_overlay_count"] == 0
    assert lagging.json()["summary"]["ros_publish_ready_count"] == 0
    assert lagging.json()["summary"]["ros_publish_payload_available_count"] == 0
    assert lagging.json()["summary"]["ros_publish_payload_blocked_count"] == 1
    assert lagging.json()["summary"]["ros_publish_status_counts"] == {"overlay_lag": 1}
    assert source_lagging["ros_publish_readiness"]["readiness_state"] == "overlay_lag"
    assert source_lagging["ros_publish_readiness"]["overlay_ready"] is False
    assert (
        source_lagging["ros_publish_readiness"]["publish_payload_preview"]["payload_available"]
        is False
    )
    assert lagging.json()["summary"]["evidence_event_publish_ready_count"] == 1


def test_vision_ros_topics_declares_safe_domain_bridge_handoff_matrix():
    main_module.store.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    response = client.get("/api/v1/vision/ros/topics")

    assert response.status_code == 200
    body = response.json()
    assert body["primary_stream_plane"] == "webrtc"
    assert body["stream_base_url"] == "http://<vision-host>:8090"
    assert body["debug_only"] is True
    assert body["internal_rosbridge"] == {
        "scope": "operator_prototype_only",
        "url": "ws://<vision-host>:9090",
        "exposes_all_topics": False,
    }
    assert body["motion_command_allowed"] is False
    assert body["control_topics_published"] == []
    assert body["topic_exposure_policy"] == expected_ros_topic_exposure_policy()
    assert body["topic_exposure_policy"]["client_publish_allowed"] is False
    assert "/cmd_vel" in body["topic_exposure_policy"]["forbidden_topic_globs"]
    assert body["topic_exposure_summary"] == expected_topic_exposure_summary(
        ["global_cam_01", "tb3_1_picam", "tb3_2_picam"]
    )
    assert body["topic_exposure_summary"]["control_topic_allowed_count"] == 0
    assert body["topic_exposure_summary"]["rosbridge_exposes_all_topics"] is False
    assert body["topic_exposure_summary"]["policy_status"] == "safe"
    assert body["topic_exposure_summary"]["policy_violation_count"] == 0
    assert body["topic_exposure_summary"]["policy_violations"] == []
    assert body["image_ingest_qos"] == {
        "reliability": "BEST_EFFORT",
        "history": "KEEP_LAST",
        "depth": 1,
    }
    assert body["frame_drop_policy"]["cache"] == "latest_only"
    assert body["frame_drop_policy"]["drop_stale_frames"] is True
    assert body["overlay_publish_qos"] == expected_ros_overlay_publish_qos_policy()
    assert body["overlay_publish_policy"] == expected_ros_overlay_publish_policy()
    assert body["overlay_publish_policy"]["publish_control_topics"] is False
    assert body["overlay_publish_policy"]["http_handlers_may_publish"] is False
    assert body["evidence_event_publish_policy"] == expected_ros_evidence_event_publish_policy()
    assert body["evidence_event_publish_policy"]["publish_control_topics"] is False
    assert body["evidence_event_publish_policy"]["payload_contains_image_bytes"] is False
    assert body["runtime_policy"]["ros2_started_by_http_request"] is False
    assert body["runtime_policy"]["http_handlers_must_spin_ros2_executor"] is False
    assert body["ingest_readiness_summary"] == {
        "sources_total": 3,
        "contract_ready_count": 3,
        "missing_physical_topic_count": 0,
        "runtime_subscriber_active_count": 0,
        "status_counts": {"contract_ready": 3, "missing_physical_topic": 0},
    }
    assert body["publish_readiness_summary"]["sources_total"] == 3
    assert body["publish_readiness_summary"]["no_frame_count"] == 3
    assert body["publish_readiness_summary"]["overlay_ready_count"] == 0
    assert body["publish_readiness_summary"]["publish_payload_available_count"] == 0
    assert body["publish_readiness_summary"]["publish_payload_blocked_count"] == 3
    assert body["evidence_event_publish_readiness_summary"] == {
        "sources_total": 3,
        "publish_ready_count": 0,
        "no_event_count": 3,
    }
    assert "keep existing /mission" in body["migration_policy"]
    by_source = {item["source"]: item for item in body["sources"]}
    assert set(by_source) == {"global_cam_01", "tb3_1_picam", "tb3_2_picam"}
    assert (
        by_source["tb3_1_picam"]["physical_input_topic"]
        == source_definition("tb3_1_picam").physical_input.topic
    )
    assert (
        by_source["tb3_1_picam"]["physical_input_message_type"]
        == source_definition("tb3_1_picam").physical_input.message_type
    )
    assert (
        by_source["tb3_1_picam"]["physical_input_content_type"]
        == source_definition("tb3_1_picam").physical_input.content_type
    )
    assert (
        by_source["tb3_1_picam"]["physical_input_transport"]
        == source_definition("tb3_1_picam").physical_input.preferred_transport
    )
    assert by_source["tb3_1_picam"]["legacy_browser_topic"] == "/mission/tb3_1/camera/compressed"
    assert (
        by_source["tb3_1_picam"]["legacy_browser_message_type"] == "sensor_msgs/msg/CompressedImage"
    )
    assert by_source["tb3_1_picam"]["normalized_image_topic"] == (
        "/sf/vision/sources/tb3_1_picam/image/compressed"
    )
    assert by_source["tb3_1_picam"]["normalized_overlay_topic"] == (
        "/sf/vision/sources/tb3_1_picam/overlay/compressed"
    )
    assert (
        by_source["tb3_1_picam"]["normalized_image_message_type"]
        == "sensor_msgs/msg/CompressedImage"
    )
    assert (
        by_source["tb3_1_picam"]["normalized_overlay_message_type"]
        == "sensor_msgs/msg/CompressedImage"
    )
    assert by_source["tb3_1_picam"]["evidence_event_topic"] == "/sf/vision/events"
    assert (
        by_source["tb3_1_picam"]["evidence_event_publish_policy"]
        == body["evidence_event_publish_policy"]
    )
    assert by_source["tb3_1_picam"]["evidence_event_publish_policy"]["dedup_key"] == "event_id"
    assert by_source["tb3_1_picam"]["evidence_event_publish_readiness"] == {
        "event_available": False,
        "publish_ready": False,
        "topic": "/sf/vision/events",
        "message_type": "smartfactory_msgs/msg/VisionEvent or JSON bridge payload",
        "schema_version": None,
        "latest_event_id": None,
        "latest_event_kind": None,
        "latest_event_timestamp": None,
        "dedup_key": "event_id",
        "payload_contains_image_bytes": False,
        "policy": expected_ros_evidence_event_publish_policy(),
        "reason": "no VisionEvent is available for this source",
    }
    assert by_source["tb3_1_picam"]["topic_exposure"] == expected_source_topic_exposure(
        "tb3_1_picam"
    )
    assert by_source["tb3_1_picam"]["topic_exposure"]["client_publish_allowed"] is False
    assert by_source["tb3_1_picam"]["topic_exposure"]["control_topics_allowed"] == []
    assert by_source["tb3_1_picam"]["qos_profile"] == body["image_ingest_qos"]
    assert by_source["tb3_1_picam"]["frame_drop_policy"] == body["frame_drop_policy"]
    assert by_source["tb3_1_picam"]["overlay_publish_qos"] == body["overlay_publish_qos"]
    assert by_source["tb3_1_picam"]["overlay_publish_policy"] == body["overlay_publish_policy"]
    assert by_source["tb3_1_picam"]["ingest_readiness"] == expected_ros_ingest_readiness(
        "tb3_1_picam"
    )
    assert by_source["tb3_1_picam"]["publish_readiness"]["readiness_state"] == "no_frame"
    assert by_source["tb3_1_picam"]["publish_readiness"]["overlay_ready"] is False
    assert by_source["tb3_1_picam"]["publish_readiness"]["runtime_plan"] == (
        expected_ros_publish_runtime_plan("tb3_1_picam")
    )
    assert (
        by_source["tb3_1_picam"]["publish_readiness"]["runtime_plan"]["control_publish_allowed"]
        is False
    )
    assert by_source["global_cam_01"]["legacy_browser_topic"] is None
    assert by_source["global_cam_01"]["legacy_browser_message_type"] is None
    assert by_source["global_cam_01"]["topic_exposure"] == expected_source_topic_exposure(
        "global_cam_01"
    )
    assert "/mission" not in " ".join(
        by_source["global_cam_01"]["topic_exposure"]["allowed_browser_topics"]
    )
    assert all(item["ingest_status"] == "planned" for item in body["sources"])
    assert all(item["overlay_publish_status"] == "planned" for item in body["sources"])


def test_ros_ingest_readiness_marks_missing_physical_topic_without_starting_ros2():
    readiness = main_module._ros_ingest_readiness("tb3_1_picam", None)

    assert readiness["readiness_state"] == "missing_physical_topic"
    assert readiness["physical_input_topic_configured"] is False
    assert readiness["runtime_subscriber_active"] is False
    assert readiness["http_debug_ingest_path"] == "/api/v1/vision/frame"
    assert readiness["required_qos_profile"] == {
        "reliability": "BEST_EFFORT",
        "history": "KEEP_LAST",
        "depth": 1,
    }
    assert readiness == expected_ros_ingest_readiness("tb3_1_picam", topic_configured=False)
    assert readiness["runtime_plan"]["spin_location"] == "background_thread"
    assert (
        readiness["runtime_plan"]["http_handler_role"] == "read_latest_state_only_never_spin_ros2"
    )


def test_vision_ros_topics_can_filter_one_source_and_rejects_unknown_source():
    main_module.store.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    response = client.get("/api/v1/vision/ros/topics", params={"source": "tb3_2_picam"})

    assert response.status_code == 200
    body = response.json()
    assert body["requested_source"] == "tb3_2_picam"
    assert body["ingest_readiness_summary"]["sources_total"] == 1
    assert body["ingest_readiness_summary"]["contract_ready_count"] == 1
    assert body["publish_readiness_summary"]["sources_total"] == 1
    assert body["publish_readiness_summary"]["no_frame_count"] == 1
    assert body["publish_readiness_summary"]["publish_payload_available_count"] == 0
    assert body["publish_readiness_summary"]["publish_payload_blocked_count"] == 1
    assert body["evidence_event_publish_readiness_summary"] == {
        "sources_total": 1,
        "publish_ready_count": 0,
        "no_event_count": 1,
    }
    assert [item["source"] for item in body["sources"]] == ["tb3_2_picam"]
    assert body["sources"][0]["legacy_browser_topic"] == "/mission/tb3_2/camera/compressed"
    assert body["topic_exposure_policy"] == expected_ros_topic_exposure_policy()
    assert body["topic_exposure_summary"] == expected_topic_exposure_summary(["tb3_2_picam"])
    assert body["sources"][0]["topic_exposure"] == expected_source_topic_exposure("tb3_2_picam")
    assert body["control_topics_published"] == []
    assert body["motion_command_allowed"] is False

    bad = client.get("/api/v1/vision/ros/topics", params={"source": "bad_cam"})
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "BAD_REQUEST"


def test_vision_ros_topics_reports_publish_readiness_transitions():
    main_module.store.reset()
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

    before_tick = client.get("/api/v1/vision/ros/topics")
    assert before_tick.status_code == 200
    source_before = {item["source"]: item for item in before_tick.json()["sources"]}["tb3_1_picam"]
    assert source_before["publish_readiness"]["readiness_state"] == "no_overlay"
    assert source_before["publish_readiness"]["latest_frame_seq"] == 1
    assert source_before["publish_readiness"]["latest_overlay_frame_seq"] is None
    assert (
        source_before["publish_readiness"]["publish_payload_preview"]["payload_available"] is False
    )

    tick = client.post("/api/v1/vision/worker/tick", json={"source": "tb3_1_picam"})
    assert tick.status_code == 200

    ready = client.get("/api/v1/vision/ros/topics")
    assert ready.status_code == 200
    ready_body = ready.json()
    source_ready = {item["source"]: item for item in ready_body["sources"]}["tb3_1_picam"]
    assert source_ready["publish_readiness"]["readiness_state"] == "ready_fresh"
    assert source_ready["publish_readiness"]["overlay_ready"] is True
    assert source_ready["publish_readiness"]["latest_frame_seq"] == 1
    assert source_ready["publish_readiness"]["latest_overlay_frame_seq"] == 1
    assert source_ready["publish_readiness"]["publish_payload_preview"]["payload_available"] is True
    assert source_ready["publish_readiness"]["publish_payload_preview"]["topic"] == (
        "/sf/vision/sources/tb3_1_picam/overlay/compressed"
    )
    assert source_ready["publish_readiness"]["runtime_plan"] == (
        expected_ros_publish_runtime_plan("tb3_1_picam")
    )
    assert ready_body["publish_readiness_summary"]["overlay_ready_count"] == 1
    assert ready_body["publish_readiness_summary"]["publish_payload_available_count"] == 1
    assert ready_body["publish_readiness_summary"]["publish_payload_blocked_count"] == 2
    assert ready_body["evidence_event_publish_readiness_summary"]["publish_ready_count"] == 1
    assert source_ready["evidence_event_publish_readiness"]["publish_ready"] is True
    assert source_ready["evidence_event_publish_readiness"]["latest_event_kind"] == "CONFIRMED"
    assert source_ready["evidence_event_publish_readiness"]["schema_version"] == "vision-event.v1"

    newer_frame = client.post(
        "/api/v1/vision/frame",
        data={"source": "tb3_1_picam"},
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )
    assert newer_frame.status_code == 200

    lagging = client.get("/api/v1/vision/ros/topics")
    assert lagging.status_code == 200
    lagging_body = lagging.json()
    source_lagging = {item["source"]: item for item in lagging_body["sources"]}["tb3_1_picam"]
    assert source_lagging["publish_readiness"]["readiness_state"] == "overlay_lag"
    assert source_lagging["publish_readiness"]["overlay_ready"] is False
    assert source_lagging["publish_readiness"]["latest_frame_seq"] == 2
    assert source_lagging["publish_readiness"]["latest_overlay_frame_seq"] == 1
    assert (
        source_lagging["publish_readiness"]["publish_payload_preview"]["payload_available"] is False
    )
    assert source_lagging["publish_readiness"]["runtime_plan"]["lag_behavior"] == (
        "do_not_publish_lagging_overlay"
    )
    assert lagging_body["publish_readiness_summary"]["overlay_lag_count"] == 1
    assert lagging_body["publish_readiness_summary"]["publish_payload_available_count"] == 0
