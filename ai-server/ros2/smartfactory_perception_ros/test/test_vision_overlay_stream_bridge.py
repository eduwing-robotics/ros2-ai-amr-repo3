from __future__ import annotations

import json
import time
import urllib.request

import pytest
import rclpy
from rclpy.qos import ReliabilityPolicy
from sensor_msgs.msg import CompressedImage

from smartfactory_perception_ros.qos_profiles import build_bounded_image_qos_profile
from smartfactory_perception_ros.vision_overlay_stream_bridge import (
    BOUNDARY,
    FrameSnapshot,
    LatestCompressedFrameStore,
    VisionOverlayStreamBridge,
    build_qos_profile,
    clamp_max_fps,
    format_mjpeg_part,
    normalize_overlay_topic,
    parse_overlay_topics_json,
    parse_source_list,
)


def make_compressed_overlay(payload: bytes = b"\xff\xd8overlay") -> CompressedImage:
    msg = CompressedImage()
    msg.format = "jpeg"
    msg.header.frame_id = "tb3_1_pi_camera_optical_frame"
    msg.header.stamp.sec = 10
    msg.header.stamp.nanosec = 20
    msg.data = payload
    return msg


def test_source_and_topic_allowlists_reject_motion_or_non_vision_surfaces():
    assert parse_source_list("tb3_1_picam,tb3_2_picam") == ["tb3_1_picam", "tb3_2_picam"]
    assert normalize_overlay_topic("tb3_1_picam") == (
        "/sf/vision/sources/tb3_1_picam/overlay/compressed"
    )

    with pytest.raises(ValueError, match="not allowed"):
        parse_source_list("tb3_1_picam,/cmd_vel")
    with pytest.raises(ValueError, match="must stay under"):
        normalize_overlay_topic("tb3_1_picam", "/mission/tb3_1/camera/compressed")
    with pytest.raises(ValueError, match="unsafe overlay topic"):
        normalize_overlay_topic("tb3_1_picam", "/sf/vision/cmd_vel/sources/tb3_1_picam/overlay/compressed")
    with pytest.raises(ValueError, match="source-scoped"):
        normalize_overlay_topic("tb3_1_picam", "/sf/vision/sources/tb3_2_picam/overlay/compressed")


def test_overlay_topic_json_overrides_stay_source_scoped():
    topics = parse_overlay_topics_json(
        '{"tb3_1_picam": "/sf/vision/sources/tb3_1_picam/overlay/compressed"}',
        ["tb3_1_picam"],
    )

    assert topics == {"tb3_1_picam": "/sf/vision/sources/tb3_1_picam/overlay/compressed"}

    with pytest.raises(ValueError, match="valid JSON"):
        parse_overlay_topics_json("{", ["tb3_1_picam"])


def test_frame_store_tracks_latest_overlay_without_raw_image_encoding():
    store = LatestCompressedFrameStore()

    frame = store.put("tb3_1_picam", make_compressed_overlay())
    status = store.status_for("tb3_1_picam", now=frame.received_monotonic_s + 0.125)

    assert frame.sequence_id == 1
    assert frame.content_type == "image/jpeg"
    assert frame.data.startswith(b"\xff\xd8")
    assert status["has_frame"] is True
    assert status["latest_sequence_id"] == 1
    assert status["frame_age_s"] == 0.125


def test_mjpeg_part_has_boundary_headers_and_original_payload():
    frame = FrameSnapshot(
        source="tb3_1_picam",
        sequence_id=7,
        received_monotonic_s=time.monotonic(),
        stamp_sec=1,
        stamp_nanosec=2,
        frame_id="camera",
        format="jpeg",
        content_type="image/jpeg",
        data=b"\xff\xd8payload",
    )

    part = format_mjpeg_part(frame)

    assert part.startswith(f"--{BOUNDARY}\r\n".encode("ascii"))
    assert b"Content-Type: image/jpeg\r\n" in part
    assert b"X-Source: tb3_1_picam\r\n" in part
    assert part.endswith(b"\xff\xd8payload\r\n")


def test_clamp_max_fps_keeps_bridge_bounded():
    assert clamp_max_fps("120", default=15.0, maximum=30.0) == 30.0
    assert clamp_max_fps("0", default=15.0, maximum=30.0) == 15.0
    assert clamp_max_fps("bad", default=12.0, maximum=30.0) == 12.0


def test_overlay_stream_bridge_qos_profile_builder_is_configurable():
    reliable = build_qos_profile("reliable", depth=1, role="overlay subscribe")
    best_effort = build_qos_profile("best_effort", depth=1, role="overlay subscribe")
    shared_best_effort = build_bounded_image_qos_profile(
        "sensor_data", depth=1, role="shared overlay subscribe"
    )

    assert reliable.reliability == ReliabilityPolicy.RELIABLE
    assert best_effort.reliability == ReliabilityPolicy.BEST_EFFORT
    assert shared_best_effort.reliability == ReliabilityPolicy.BEST_EFFORT

    with pytest.raises(ValueError, match="QoS reliability"):
        build_qos_profile("bad", role="overlay subscribe")


def test_bridge_node_serves_read_only_status_and_creates_no_motion_publishers():
    rclpy.init(
        args=[
            "--ros-args",
            "-p",
            "host:=127.0.0.1",
            "-p",
            "port:=0",
            "-p",
            "sources:=tb3_1_picam",
        ]
    )
    node = VisionOverlayStreamBridge()
    try:
        node._on_overlay_image("tb3_1_picam", make_compressed_overlay())
        with urllib.request.urlopen(  # noqa: S310 - local test server on loopback only
            f"http://127.0.0.1:{node.port}/api/v1/vision/bridge/status",
            timeout=2.0,
        ) as response:
            payload = json.loads(response.read().decode("utf-8"))

        assert payload["read_only"] is True
        assert payload["motion_command_allowed"] is False
        assert payload["overlay_sub_qos_reliability"] == "reliable"
        assert payload["sources"][0]["source"] == "tb3_1_picam"
        assert payload["sources"][0]["has_frame"] is True
        assert payload["sources"][0]["stream_path"] == (
            "/api/v1/vision/overlay/stream?source=tb3_1_picam"
        )

        publishers = node.get_publisher_names_and_types_by_node(
            node.get_name(),
            node.get_namespace(),
        )
        publisher_names = {name for name, _types in publishers}
        assert "/cmd_vel" not in publisher_names
        assert all("nav2" not in name for name in publisher_names)
    finally:
        node.destroy_node()
        rclpy.shutdown()
