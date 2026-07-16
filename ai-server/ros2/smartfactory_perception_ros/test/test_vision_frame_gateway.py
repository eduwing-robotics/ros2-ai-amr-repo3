from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np
import pytest
import rclpy
import requests
from rclpy.qos import ReliabilityPolicy
from sensor_msgs.msg import CompressedImage
from smartfactory_perception_ros.qos_profiles import build_bounded_image_qos_profile
from smartfactory_perception_ros.vision_frame_gateway import (
    PendingFrameWork,
    VisionFrameGateway,
    assert_safe_input_topic,
    assert_safe_publish_topic,
    build_ai_server_url,
    build_qos_profile,
    post_frame,
    post_frame_process,
)

GATEWAY_HMAC_SECRET = "fixture-vision-gateway-secret"
PACKAGE_ROOT = Path(__file__).resolve().parents[1]
AI_SERVER_ROOT = PACKAGE_ROOT.parents[1]


class FakeResponse:
    def __init__(self, status_code=200, payload=None, content=b"", headers=None):
        self.status_code = status_code
        self._payload = payload
        self.content = content
        self.headers = headers or {}

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    def __init__(self):
        self.post_calls = []
        self.get_calls = []
        self.post_responses = []
        self.get_responses = []
        self.post_exc = None
        self.get_exc = None
        self.closed = False

    def post(self, url, **kwargs):
        self.post_calls.append({"url": url, **kwargs})
        if self.post_exc:
            raise self.post_exc
        if self.post_responses:
            return self.post_responses.pop(0)
        return FakeResponse(200, {"ok": True})

    def send(self, request, **kwargs):
        self.post_calls.append(
            {
                "url": request.url,
                "headers": dict(request.headers),
                "body": request.body,
                **kwargs,
            }
        )
        if self.post_exc:
            raise self.post_exc
        if self.post_responses:
            return self.post_responses.pop(0)
        return FakeResponse(200, {"ok": True})

    def get(self, url, **kwargs):
        self.get_calls.append({"url": url, **kwargs})
        if self.get_exc:
            raise self.get_exc
        if self.get_responses:
            return self.get_responses.pop(0)
        return FakeResponse(404, {"detail": "missing"})

    def close(self):
        self.closed = True


def make_compressed_image_msg(width=16, height=12, image_format="jpeg") -> CompressedImage:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :, 1] = 255
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    msg = CompressedImage()
    msg.format = image_format
    msg.data = encoded.tobytes()
    return msg


def test_build_ai_server_url_normalizes_slashes():
    assert (
        build_ai_server_url("http://127.0.0.1:8100/", "/api/v1/vision/frame")
        == "http://127.0.0.1:8100/api/v1/vision/frame"
    )


def test_qos_profile_builder_supports_reliable_and_rejects_bad_values():
    reliable = build_qos_profile("reliable", depth=1, role="image input")
    best_effort = build_qos_profile("sensor_data", depth=1, role="image input")
    shared_reliable = build_bounded_image_qos_profile(
        "reliable", depth=1, role="shared image input"
    )

    assert reliable.reliability == ReliabilityPolicy.RELIABLE
    assert best_effort.reliability == ReliabilityPolicy.BEST_EFFORT
    assert shared_reliable.reliability == ReliabilityPolicy.RELIABLE

    with pytest.raises(ValueError, match="QoS reliability"):
        build_qos_profile("invalid", role="image input")


def test_safety_filters_reject_motion_and_non_sf_publish_topics():
    assert_safe_input_topic("/camera/image_raw/compressed")
    assert_safe_publish_topic("/sf/vision/sources/tb3_1_picam/overlay/compressed", role="overlay")

    with pytest.raises(ValueError, match="unsafe input topic"):
        assert_safe_input_topic("/cmd_vel")
    with pytest.raises(ValueError, match="must stay under"):
        assert_safe_publish_topic("/mission/tb3_1/camera/compressed", role="overlay")
    with pytest.raises(ValueError, match="unsafe evidence topic"):
        assert_safe_publish_topic("/sf/vision/cmd_vel", role="evidence")


def test_gateway_exposes_no_unsigned_worker_tick_path():
    checked_paths = [
        PACKAGE_ROOT / "smartfactory_perception_ros" / "vision_frame_gateway.py",
        PACKAGE_ROOT / "smartfactory_perception_ros" / "vision_frame_gateway_http.py",
        PACKAGE_ROOT / "launch" / "vision_frame_gateway.launch.py",
        PACKAGE_ROOT / "README.md",
        AI_SERVER_ROOT / "scripts" / "vision" / "run_d1_vision_bundle.sh",
        AI_SERVER_ROOT / "scripts" / "vision" / "run_d1_vision_domain_sidecar.sh",
        AI_SERVER_ROOT / "scripts" / "vision" / "run_d1_vision_multi_source_gateway_bundle.sh",
    ]
    obsolete_names = (
        "gateway_auth_" + "debug_enabled",
        "process_with_" + "worker_tick",
        "force_" + "worker_tick",
        "mark_worker_tick_" + "stale",
        "post_" + "worker_tick",
    )

    for path in checked_paths:
        source = path.read_text(encoding="utf-8")
        for name in obsolete_names:
            assert name not in source, f"{name} remains in {path}"


def test_post_frame_uses_latest_frame_ingest_endpoint_shape():
    session = FakeSession()
    session.post_responses.append(FakeResponse(200, {"frame": {"source": "tb3_1_picam"}}))

    result = post_frame(
        session=session,
        url="http://ai/api/v1/vision/frame",
        source_id="tb3_1_picam",
        image_file=("snapshot.jpg", "image/jpeg", b"jpeg-bytes"),
        timeout=0.5,
        gateway_hmac_secret=GATEWAY_HMAC_SECRET,
    )

    assert result.ok is True
    assert session.post_calls[0]["url"] == "http://ai/api/v1/vision/frame"
    assert "X-SF-Gateway-Signature" in session.post_calls[0]["headers"]
    assert b'tb3_1_picam' in session.post_calls[0]["body"]
    assert b'jpeg-bytes' in session.post_calls[0]["body"]


def test_post_frame_process_uses_inline_process_endpoint_shape():
    session = FakeSession()
    session.post_responses.append(FakeResponse(200, {"frame_seq": 1, "overlay": {"frame_seq": 1}}))

    result = post_frame_process(
        session=session,
        url="http://ai/api/v1/vision/frame/process",
        source_id="tb3_1_picam",
        image_file=("snapshot.jpg", "image/jpeg", b"jpeg-bytes"),
        timeout=0.5,
        gateway_hmac_secret=GATEWAY_HMAC_SECRET,
        force=True,
        stale=False,
    )

    assert result.ok is True
    assert session.post_calls[0]["url"] == "http://ai/api/v1/vision/frame/process"
    assert "X-SF-Gateway-Signature" in session.post_calls[0]["headers"]
    assert b'tb3_1_picam' in session.post_calls[0]["body"]
    assert b'true' in session.post_calls[0]["body"]
    assert b'false' in session.post_calls[0]["body"]


def test_post_frame_reports_timeout_without_raising():
    session = FakeSession()
    session.post_exc = requests.Timeout("slow")

    result = post_frame(
        session=session,
        url="http://ai/api/v1/vision/frame",
        source_id="tb3_1_picam",
        image_file=("snapshot.jpg", "image/jpeg", b"jpeg-bytes"),
        timeout=0.5,
        gateway_hmac_secret=GATEWAY_HMAC_SECRET,
    )

    assert result.ok is False
    assert result.status_code is None
    assert "timed out" in result.error


def test_gateway_posts_latest_compressed_frame_and_does_not_create_motion_publishers():
    rclpy.init(
        args=[
            "--ros-args",
            "-p",
            f"gateway_hmac_secret:={GATEWAY_HMAC_SECRET}",
            "-p",
            "source_id:=tb3_1_picam",
            "-p",
            "image_topic:=/camera/image_raw/compressed",
            "-p",
            "overlay_topic:=/sf/vision/sources/tb3_1_picam/overlay/compressed",
            "-p",
            "evidence_topic:=/sf/vision/events",
            "-p",
            "async_pipeline:=false",
            "-p",
            "process_frame_inline:=false",
        ]
    )
    session = FakeSession()
    session.post_responses.append(FakeResponse(200, {"frame": {"source": "tb3_1_picam"}}))
    node = VisionFrameGateway(session=session)
    try:
        node._on_compressed_image(make_compressed_image_msg())
        node._on_timer()

        assert len(session.post_calls) == 1
        assert session.post_calls[0]["url"].endswith("/api/v1/vision/frame")
        assert node.diagnostics["received_frames"] == 1
        assert node.diagnostics["frame_post_successes"] == 1
        publishers = node.get_publisher_names_and_types_by_node(
            node.get_name(), node.get_namespace()
        )
        publisher_names = {name for name, _types in publishers}
        assert "/cmd_vel" not in publisher_names
        assert all("nav2" not in name for name in publisher_names)
    finally:
        node.destroy_node()
        rclpy.shutdown()


def test_gateway_default_inline_processes_latest_compressed_frame():
    rclpy.init(
        args=[
            "--ros-args",
            "-p",
            f"gateway_hmac_secret:={GATEWAY_HMAC_SECRET}",
            "-p",
            "source_id:=tb3_1_picam",
            "-p",
            "image_topic:=/camera/image_raw/compressed",
            "-p",
            "async_pipeline:=false",
        ]
    )
    session = FakeSession()
    session.post_responses.append(
        FakeResponse(200, {"frame_seq": 7, "overlay": {"frame_seq": 7}})
    )
    node = VisionFrameGateway(session=session)
    try:
        node._on_compressed_image(make_compressed_image_msg())
        node._on_timer()

        assert len(session.post_calls) == 1
        call = session.post_calls[0]
        assert call["url"].endswith("/api/v1/vision/frame/process")
        assert "X-SF-Gateway-Signature" in call["headers"]
        assert b"tb3_1_picam" in call["body"]
        assert call["body"].count(b"false") >= 2
        assert node.diagnostics["process_frame_inline"] is True
        assert node.diagnostics["frame_post_attempts"] == 1
        assert node.diagnostics["frame_post_successes"] == 1
        assert node.diagnostics["work_processed"] == 1
    finally:
        node.destroy_node()
        rclpy.shutdown()


def test_gateway_diagnostics_shape_stays_stable():
    rclpy.init(
        args=[
            "--ros-args",
            "-p",
            f"gateway_hmac_secret:={GATEWAY_HMAC_SECRET}",
            "-p",
            "source_id:=tb3_1_picam",
            "-p",
            "image_topic:=/camera/image_raw/compressed",
            "-p",
            "async_pipeline:=false",
        ]
    )
    node = VisionFrameGateway(session=FakeSession())
    try:
        assert set(node.diagnostics) == {
            "source_id",
            "image_topic",
            "overlay_topic",
            "evidence_topic",
            "publish_overlay",
            "publish_evidence",
            "async_pipeline",
            "process_frame_inline",
            "image_qos_reliability",
            "overlay_pub_qos_reliability",
            "received_frames",
            "frame_post_attempts",
            "frame_post_successes",
            "frame_post_failures",
            "overlay_publish_attempts",
            "overlay_publish_successes",
            "overlay_publish_skips",
            "evidence_publish_attempts",
            "evidence_publish_successes",
            "work_enqueued",
            "work_replaced",
            "work_processed",
            "work_retries",
        }
    finally:
        node.destroy_node()
        rclpy.shutdown()


def test_gateway_async_shutdown_stops_worker_and_closes_session():
    rclpy.init(
        args=[
            "--ros-args",
            "-p",
            f"gateway_hmac_secret:={GATEWAY_HMAC_SECRET}",
            "-p",
            "source_id:=tb3_1_picam",
            "-p",
            "image_topic:=/camera/image_raw/compressed",
            "-p",
            "async_pipeline:=true",
        ]
    )
    session = FakeSession()
    node = VisionFrameGateway(session=session)
    worker_thread = node._worker_thread

    node.destroy_node()
    try:
        assert session.closed is True
        assert worker_thread is not None
        assert worker_thread.is_alive() is False
    finally:
        rclpy.shutdown()


def test_gateway_can_publish_safe_overlay_and_evidence_from_ai_server_state():
    rclpy.init(
        args=[
            "--ros-args",
            "-p",
            f"gateway_hmac_secret:={GATEWAY_HMAC_SECRET}",
            "-p",
            "source_id:=tb3_1_picam",
            "-p",
            "image_topic:=/camera/image_raw/compressed",
            "-p",
            "publish_overlay:=true",
            "-p",
            "publish_evidence:=true",
            "-p",
            "async_pipeline:=false",
        ]
    )
    session = FakeSession()
    session.post_responses.append(
        FakeResponse(
            200,
            {
                "frame_seq": 1,
                "processed": True,
                "events": [{"event_id": "evt-1"}],
                "overlay": {"frame_seq": 1},
            },
        )
    )
    session.get_responses.append(
        FakeResponse(200, content=b"\xff\xd8overlay", headers={"content-type": "image/jpeg"})
    )
    node = VisionFrameGateway(session=session)
    try:
        node._on_compressed_image(make_compressed_image_msg())
        node._on_timer()

        assert [call["url"].split("/api/v1/")[1] for call in session.post_calls] == [
            "vision/frame/process"
        ]
        assert session.get_calls[0]["url"].endswith("/api/v1/vision/overlay/latest/image")
        assert node.diagnostics["overlay_publish_successes"] == 1
        assert node.diagnostics["evidence_publish_successes"] == 1
    finally:
        node.destroy_node()
        rclpy.shutdown()


def test_async_pipeline_work_slot_is_bounded_and_drop_old():
    rclpy.init(
        args=[
            "--ros-args",
            "-p",
            f"gateway_hmac_secret:={GATEWAY_HMAC_SECRET}",
            "-p",
            "source_id:=tb3_1_picam",
            "-p",
            "image_topic:=/camera/image_raw/compressed",
            "-p",
            "async_pipeline:=false",
            "-p",
            "process_frame_inline:=false",
        ]
    )
    node = VisionFrameGateway(session=FakeSession())
    try:
        first = PendingFrameWork(
            frame_id=1,
            msg=make_compressed_image_msg(),
            header=None,
            enqueued_monotonic_s=1.0,
        )
        second = PendingFrameWork(
            frame_id=2,
            msg=make_compressed_image_msg(),
            header=None,
            enqueued_monotonic_s=2.0,
        )

        node._enqueue_frame_work(first)
        node._enqueue_frame_work(second)
        taken = node._take_pending_frame_work()

        assert taken is not None
        assert taken.frame_id == 2
        assert node.diagnostics["work_enqueued"] == 2
        assert node.diagnostics["work_replaced"] == 1
    finally:
        node.destroy_node()
        rclpy.shutdown()


def test_gateway_rejects_unsafe_publish_parameter_before_running():
    rclpy.init(
        args=[
            "--ros-args",
            "-p",
            f"gateway_hmac_secret:={GATEWAY_HMAC_SECRET}",
            "-p",
            "overlay_topic:=/cmd_vel",
        ]
    )
    try:
        with pytest.raises(ValueError, match="must stay under|unsafe overlay topic"):
            VisionFrameGateway(session=FakeSession())
    finally:
        if rclpy.ok():
            rclpy.shutdown()
