from __future__ import annotations

import numpy as np
import pytest
import requests
from cv_bridge import CvBridge
import rclpy
from sensor_msgs.msg import CompressedImage, Image

from smartfactory_perception_ros.image_snapshot_client import (
    ImageSnapshotClient,
    build_detect_url,
    encode_compressed_image_message,
    encode_image_message,
    post_snapshot,
)


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    def __init__(self, response=None, exc=None):
        self.response = response or FakeResponse(200, {"events": []})
        self.exc = exc
        self.calls = []

    def post(self, url, *, data, files, timeout):
        self.calls.append({"url": url, "data": data, "files": files, "timeout": timeout})
        if self.exc:
            raise self.exc
        return self.response


def make_image_msg(width=16, height=12) -> Image:
    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :, 1] = 255
    msg = Image()
    msg.height = height
    msg.width = width
    msg.encoding = "bgr8"
    msg.is_bigendian = 0
    msg.step = width * 3
    msg.data = image.tobytes()
    return msg



def make_compressed_image_msg(width=16, height=12, image_format="jpeg") -> CompressedImage:
    import cv2

    image = np.zeros((height, width, 3), dtype=np.uint8)
    image[:, :, 2] = 255
    extension = ".jpg" if "jpeg" in image_format or "jpg" in image_format else ".png"
    ok, encoded = cv2.imencode(extension, image)
    assert ok
    msg = CompressedImage()
    msg.format = image_format
    msg.data = encoded.tobytes()
    return msg

def test_build_detect_url_normalizes_slashes():
    assert (
        build_detect_url("http://127.0.0.1:8100/", "/api/v1/detect/image")
        == "http://127.0.0.1:8100/api/v1/detect/image"
    )


def test_encode_image_message_encodes_raw_image_to_jpeg_bytes():
    filename, content_type, payload = encode_image_message(
        make_image_msg(), bridge=CvBridge(), image_format="jpg"
    )

    assert filename == "snapshot.jpg"
    assert content_type == "image/jpeg"
    assert payload.startswith(b"\xff\xd8")



def test_encode_compressed_image_message_passes_jpeg_bytes_through():
    msg = make_compressed_image_msg(image_format="bgr8; jpeg compressed bgr8")

    filename, content_type, payload = encode_compressed_image_message(msg, image_format="png")

    assert filename == "snapshot.jpg"
    assert content_type == "image/jpeg"
    assert payload == bytes(msg.data)
    assert payload.startswith(b"\xff\xd8")


def test_encode_compressed_image_message_decodes_unknown_format_to_requested_format():
    msg = make_compressed_image_msg(image_format="custom-transport")

    filename, content_type, payload = encode_compressed_image_message(msg, image_format="png")

    assert filename == "snapshot.png"
    assert content_type == "image/png"
    assert payload.startswith(b"\x89PNG")

def test_post_snapshot_sends_expected_multipart_payload():
    session = FakeSession(FakeResponse(200, {"events": [{"event_id": "evt-1"}]}))

    result = post_snapshot(
        session=session,
        url="http://ai.local/api/v1/detect/image",
        source_id="tb3_1_picam",
        emit=False,
        image_file=("snapshot.jpg", "image/jpeg", b"jpg-bytes"),
        timeout=0.5,
    )

    assert result.ok is True
    assert result.status_code == 200
    assert result.response == {"events": [{"event_id": "evt-1"}]}
    assert session.calls[0]["url"] == "http://ai.local/api/v1/detect/image"
    assert session.calls[0]["data"] == {"source": "tb3_1_picam", "emit": "false"}
    assert session.calls[0]["files"]["image"] == (
        "snapshot.jpg",
        b"jpg-bytes",
        "image/jpeg",
    )
    assert session.calls[0]["timeout"] == 0.5


@pytest.mark.parametrize("status_code", [400, 503])
def test_post_snapshot_reports_non_2xx_without_raising(status_code):
    session = FakeSession(FakeResponse(status_code, {"error": "nope"}))

    result = post_snapshot(
        session=session,
        url="http://ai.local/api/v1/detect/image",
        source_id="global_cam_01",
        emit=False,
        image_file=("snapshot.jpg", "image/jpeg", b"jpg-bytes"),
        timeout=0.5,
    )

    assert result.ok is False
    assert result.status_code == status_code
    assert result.error == f"AI Server returned HTTP {status_code}"


def test_post_snapshot_reports_timeout_without_raising():
    session = FakeSession(exc=requests.Timeout("slow"))

    result = post_snapshot(
        session=session,
        url="http://ai.local/api/v1/detect/image",
        source_id="global_cam_01",
        emit=False,
        image_file=("snapshot.jpg", "image/jpeg", b"jpg-bytes"),
        timeout=0.5,
    )

    assert result.ok is False
    assert result.status_code is None
    assert result.error == "AI Server request timed out"


def test_node_timer_without_latest_image_does_not_post():
    rclpy.init(args=None)
    session = FakeSession()
    node = ImageSnapshotClient(session=session)
    try:
        node._on_timer()
        assert session.calls == []
        assert node.diagnostics["post_attempts"] == 0
    finally:
        node.destroy_node()
        rclpy.shutdown()


def test_node_timer_posts_latest_image_with_fake_session():
    rclpy.init(args=None)
    session = FakeSession(FakeResponse(200, {"events": []}))
    node = ImageSnapshotClient(session=session)
    try:
        node._on_image(make_image_msg())
        node._on_timer()
        assert len(session.calls) == 1
        assert node.diagnostics["received_frames"] == 1
        assert node.diagnostics["post_attempts"] == 1
        assert node.diagnostics["post_successes"] == 1
    finally:
        node.destroy_node()
        rclpy.shutdown()


def test_node_timer_does_not_repost_same_frame_without_new_image():
    rclpy.init(args=None)
    session = FakeSession(FakeResponse(200, {"events": []}))
    node = ImageSnapshotClient(session=session)
    try:
        node._on_image(make_image_msg())
        node._on_timer()
        node._on_timer()
        assert len(session.calls) == 1
        assert node.diagnostics["received_frames"] == 1
        assert node.diagnostics["post_attempts"] == 1
    finally:
        node.destroy_node()
        rclpy.shutdown()


def test_node_timer_posts_again_after_new_image_arrives():
    rclpy.init(args=None)
    session = FakeSession(FakeResponse(200, {"events": []}))
    node = ImageSnapshotClient(session=session)
    try:
        node._on_image(make_image_msg())
        node._on_timer()
        node._on_image(make_image_msg())
        node._on_timer()
        assert len(session.calls) == 2
        assert node.diagnostics["received_frames"] == 2
        assert node.diagnostics["post_attempts"] == 2
    finally:
        node.destroy_node()
        rclpy.shutdown()


def test_node_timer_posts_compressed_image_without_reencoding_jpeg():
    rclpy.init(args=["--ros-args", "-p", "image_transport:=compressed"])
    session = FakeSession(FakeResponse(200, {"events": []}))
    node = ImageSnapshotClient(session=session)
    try:
        msg = make_compressed_image_msg(image_format="jpeg")
        node._on_compressed_image(msg)
        node._on_timer()
        assert len(session.calls) == 1
        assert node.diagnostics["received_frames"] == 1
        assert node.diagnostics["post_attempts"] == 1
        assert session.calls[0]["files"]["image"] == (
            "snapshot.jpg",
            bytes(msg.data),
            "image/jpeg",
        )
    finally:
        node.destroy_node()
        rclpy.shutdown()
