import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient
from generated_fixtures import aruco_png_bytes, blank_png_bytes

from app import runtime_routes as main_module
from app.config import get_settings
from app.main import app
from app.vision_interfaces import DetectionBox, InstanceMask

client = TestClient(app)

# Test-only contract oracle for endpoint-focused API tests. Keep this module
# limited to fixtures and expected read-model/policy dictionaries; production
# route behavior must stay in app modules, and each test remains responsible for
# resetting shared in-memory state before assertions that depend on it.

__all__ = [
    "DetectionBox",
    "InstanceMask",
    "aruco_png_bytes",
    "blank_png_bytes",
    "client",
    "cv2",
    "expected_ros_evidence_event_publish_policy",
    "expected_ros_ingest_readiness",
    "expected_ros_ingest_runtime_plan",
    "expected_ros_overlay_publish_policy",
    "expected_ros_overlay_publish_qos_policy",
    "expected_ros_publish_runtime_plan",
    "expected_ros_topic_exposure_policy",
    "expected_rosbridge_subscription_hints",
    "expected_source_topic_exposure",
    "expected_topic_exposure_summary",
    "get_settings",
    "main_module",
    "np",
    "pytest",
    "source_definition",
]


def expected_ros_overlay_publish_qos_policy() -> dict:
    return {
        "reliability": "BEST_EFFORT",
        "history": "KEEP_LAST",
        "depth": 1,
        "durability": "VOLATILE",
    }


def expected_ros_overlay_publish_policy() -> dict:
    return {
        "message_type": "sensor_msgs/msg/CompressedImage",
        "encoding": "jpeg",
        "publish_when": "publish_payload_preview.payload_available_true",
        "drop_when": ["no_frame", "no_overlay", "overlay_lag"],
        "max_publish_fps": 10,
        "queue_policy": "keep_last_1_drop_old_overlay",
        "include_stale_warning_band": True,
        "publish_lagging_overlay": False,
        "publish_control_topics": False,
        "http_handlers_may_publish": False,
    }


def expected_ros_evidence_event_publish_policy() -> dict:
    return {
        "topic": "/sf/vision/events",
        "message_type": "smartfactory_msgs/msg/VisionEvent or JSON bridge payload",
        "schema_version": "vision-event.v1",
        "qos_profile": {
            "reliability": "RELIABLE",
            "history": "KEEP_LAST",
            "depth": 10,
            "durability": "VOLATILE",
        },
        "publish_when": "worker_tick_or_detector_emits_schema_valid_vision_event",
        "dedup_key": "event_id",
        "source_of_truth": "Main/WMS remains authoritative; Vision publishes evidence only",
        "publish_control_topics": False,
        "http_handlers_may_publish": False,
        "payload_contains_image_bytes": False,
    }


def source_definition(source: str):
    return get_settings().source_registry.get(source)


def expected_ros_ingest_runtime_plan(source: str) -> dict:
    definition = source_definition(source)
    return {
        "node_name": "smartfactory_vision_gateway",
        "executor": "MultiThreadedExecutor",
        "spin_location": "background_thread",
        "source_registry_path": str(get_settings().vision_sources_registry_path),
        "physical_input_topic": definition.physical_input.topic,
        "physical_input_message_type": definition.physical_input.message_type,
        "physical_input_content_type": definition.physical_input.content_type,
        "physical_input_transport": definition.physical_input.preferred_transport,
        "subscription_callback": "registry_source_image_message_to_latest_frame_store_put",
        "ingest_adapter": "_store_latest_frame_from_bytes",
        "ingest_adapter_contract": {
            "input": "registry source plus encoded image bytes plus content_type from HTTP or future ROS callback",
            "output": "StoredFrame in LatestFrameStore",
            "updates_source_health": True,
            "runs_detection_inline": False,
            "renders_overlay_inline": False,
            "safe_for_http_handlers": True,
            "raw_image_requires_callback_encoding": True,
        },
        "shared_state": "LatestFrameStore",
        "shared_state_guard": "threading.Lock inside frame store",
        "http_handler_role": "read_latest_state_only_never_spin_ros2",
        "backpressure": "overwrite_latest_frame_per_source",
        "target_frame_store_source": source,
        "startup_owner": "process_startup_or_launch_file_not_http_request",
        "shutdown_owner": "process_signal_handler_or_lifespan_cleanup",
    }


def expected_ros_ingest_readiness(source: str, *, topic_configured: bool = True) -> dict:
    definition = source_definition(source)
    return {
        "readiness_state": "contract_ready" if topic_configured else "missing_physical_topic",
        "physical_input_topic_configured": topic_configured,
        "physical_input_message_type": definition.physical_input.message_type,
        "physical_input_content_type": definition.physical_input.content_type,
        "physical_input_transport": definition.physical_input.preferred_transport,
        "runtime_subscriber_active": False,
        "http_debug_ingest_path": "/api/v1/vision/frame",
        "required_qos_profile": {
            "reliability": "BEST_EFFORT",
            "history": "KEEP_LAST",
            "depth": 1,
        },
        "frame_drop_policy": {
            "cache": "latest_only",
            "drop_stale_frames": True,
            "stale_after_s": get_settings().source_stale_after_s,
            "offline_after_s": get_settings().source_offline_after_s,
            "backpressure": "overwrite_latest_frame_per_source",
        },
        "runtime_plan": expected_ros_ingest_runtime_plan(source),
        "reason": (
            "source registry has a physical ROS image topic; Lane C can attach a background subscriber"
            if topic_configured
            else "no physical ROS image topic is configured for this source"
        ),
    }


def expected_ros_publish_runtime_plan(source: str) -> dict:
    return {
        "node_name": "smartfactory_vision_gateway",
        "executor": "MultiThreadedExecutor",
        "spin_location": "background_thread",
        "publisher_callback": "read_latest_overlay_then_publish_compressed_image_when_ready",
        "publish_adapter": "_overlay_publish_payload_preview_for_source",
        "publish_adapter_contract": {
            "input": "source plus latest frame and overlay cache state",
            "output": "publishable compressed overlay metadata when overlay is ready",
            "reads_latest_overlay_cache": True,
            "requires_frame_overlay_seq_match": True,
            "publishes_lagging_overlay": False,
            "publishes_control_topics": False,
            "safe_for_http_handlers": True,
        },
        "shared_state": "LatestEvidenceCache plus overlay image cache",
        "shared_state_guard": "threading.Lock around overlay image cache",
        "publish_topic": f"/sf/vision/sources/{source}/overlay/compressed",
        "publish_message_type": "sensor_msgs/msg/CompressedImage",
        "publish_qos_profile": expected_ros_overlay_publish_qos_policy(),
        "publish_policy": expected_ros_overlay_publish_policy(),
        "publish_condition": "overlay_ready_true_and_latest_overlay_frame_seq_matches_latest_frame_seq",
        "stale_behavior": "publish_ready_stale_overlay_with_visual_warning_band",
        "lag_behavior": "do_not_publish_lagging_overlay",
        "http_handler_role": "read_latest_state_only_never_publish_ros2",
        "control_publish_allowed": False,
        "startup_owner": "process_startup_or_launch_file_not_http_request",
        "shutdown_owner": "process_signal_handler_or_lifespan_cleanup",
    }


def expected_ros_topic_exposure_policy() -> dict:
    return {
        "policy": "explicit_allowlist_only",
        "rosbridge_exposes_all_topics": False,
        "browser_primary_transport": "webrtc",
        "rosbridge_scope": "internal_operator_allowlist_only",
        "allowed_message_types": [
            "sensor_msgs/msg/CompressedImage",
            "smartfactory_msgs/msg/VisionEvent or JSON bridge payload",
        ],
        "forbidden_topic_globs": [
            "/cmd_vel",
            "*/cmd_vel",
            "/navigate_to_pose",
            "/follow_path",
            "/parameter_events",
            "/rosout",
            "/tf",
            "/tf_static",
        ],
        "forbidden_capabilities": [
            "motion_command_publish",
            "nav2_action_call",
            "parameter_mutation",
            "raw_dds_forwarding",
        ],
        "client_publish_allowed": False,
        "server_publish_control_allowed": False,
        "auth_required_when_exposed_beyond_private_network": True,
        "notes": [
            "Main-facing browser video uses WebRTC primary with the source-selected HTTP/MJPEG :8090 gateway as fallback.",
            "Expose only camera/overlay/evidence topics needed by operator/internal ROS tooling.",
            "Do not expose all DDS topics through rosbridge.",
            "Motion and parameter mutation remain outside Vision Gateway.",
        ],
    }


def expected_source_topic_exposure(source: str) -> dict:
    robot_topic = {
        "tb3_1_picam": "/mission/tb3_1/camera/compressed",
        "tb3_2_picam": "/mission/tb3_2/camera/compressed",
    }.get(source)
    physical_topic = source_definition(source).physical_input.topic
    browser_topics = [
        item
        for item in (
            robot_topic,
            f"/sf/vision/sources/{source}/image/compressed",
            f"/sf/vision/sources/{source}/overlay/compressed",
        )
        if item is not None
    ]
    return {
        "allowed_browser_topics": browser_topics,
        "allowed_ingest_topics": [physical_topic],
        "allowed_publish_topics": [
            f"/sf/vision/sources/{source}/image/compressed",
            f"/sf/vision/sources/{source}/overlay/compressed",
            "/sf/vision/events",
        ],
        "client_publish_allowed": False,
        "control_topics_allowed": [],
        "forbidden_topic_globs": expected_ros_topic_exposure_policy()["forbidden_topic_globs"],
    }


def expected_rosbridge_subscription_hints(source: str) -> dict:
    return {
        "scope": "internal_operator_prototype_only",
        "main_facing_video_transport": "webrtc",
        "main_facing_fallback_video_transport": "http_mjpeg_gateway",
        "allowed_browser_topics": expected_source_topic_exposure(source)["allowed_browser_topics"],
        "recommended_image_topic": f"/sf/vision/sources/{source}/image/compressed",
        "recommended_overlay_topic": f"/sf/vision/sources/{source}/overlay/compressed",
        "legacy_browser_topic": {
            "tb3_1_picam": "/mission/tb3_1/camera/compressed",
            "tb3_2_picam": "/mission/tb3_2/camera/compressed",
        }.get(source),
        "client_publish_allowed": False,
        "control_topics_allowed": [],
    }


def expected_topic_exposure_summary(sources: list[str]) -> dict:
    exposures = [expected_source_topic_exposure(source) for source in sources]
    browser_topics = {
        topic for exposure in exposures for topic in exposure["allowed_browser_topics"]
    }
    ingest_topics = {topic for exposure in exposures for topic in exposure["allowed_ingest_topics"]}
    publish_topics = {
        topic for exposure in exposures for topic in exposure["allowed_publish_topics"]
    }
    control_topics = {
        topic for exposure in exposures for topic in exposure["control_topics_allowed"]
    }
    policy = expected_ros_topic_exposure_policy()
    return {
        "sources_total": len(sources),
        "allowed_browser_topic_count": len(browser_topics),
        "allowed_ingest_topic_count": len(ingest_topics),
        "allowed_publish_topic_count": len(publish_topics),
        "control_topic_allowed_count": len(control_topics),
        "client_publish_allowed_source_count": sum(
            1 for exposure in exposures if exposure["client_publish_allowed"]
        ),
        "forbidden_topic_glob_count": len(policy["forbidden_topic_globs"]),
        "forbidden_capability_count": len(policy["forbidden_capabilities"]),
        "explicit_allowlist_only": True,
        "rosbridge_exposes_all_topics": False,
        "server_publish_control_allowed": False,
        "policy_status": "safe",
        "policy_violation_count": 0,
        "policy_violations": [],
    }
