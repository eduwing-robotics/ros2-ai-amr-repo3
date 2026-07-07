from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np
import requests
from cv_bridge import CvBridge
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage, Image

VALID_SOURCE_IDS = {"global_cam_01", "tb3_1_picam", "tb3_2_picam"}
VALID_IMAGE_TRANSPORTS = {"raw", "compressed"}


@dataclass(frozen=True)
class SnapshotPostResult:
    ok: bool
    status_code: int | None
    error: str | None = None
    response: Any | None = None


def build_detect_url(ai_server_url: str, detect_path: str = "/api/v1/detect/image") -> str:
    """Join the AI Server base URL and detect endpoint path."""

    base = ai_server_url.rstrip("/")
    path = (detect_path or "/api/v1/detect/image").strip()
    return f"{base}/{path.lstrip('/')}"


def _normalize_image_format(image_format: str) -> str:
    normalized_format = image_format.strip().lower().lstrip(".") or "jpg"
    if normalized_format == "jpeg":
        normalized_format = "jpg"
    if normalized_format not in {"jpg", "png"}:
        raise ValueError("image_format must be 'jpg' or 'png'")
    return normalized_format


def _content_type_for_format(image_format: str) -> str:
    return "image/jpeg" if image_format == "jpg" else "image/png"


def _compressed_format(msg: CompressedImage) -> str | None:
    """Return jpg/png if a ROS CompressedImage format string clearly says so."""

    fmt = (msg.format or "").strip().lower()
    # Common ROS formats include "jpeg", "png", and strings like
    # "bgr8; jpeg compressed bgr8".
    if "jpeg" in fmt or "jpg" in fmt:
        return "jpg"
    if "png" in fmt:
        return "png"
    return None


def encode_image_message(
    msg: Image,
    *,
    bridge: CvBridge | None = None,
    image_format: str = "jpg",
) -> tuple[str, str, bytes]:
    """Encode a raw ROS Image message into bytes accepted by AI Server upload."""

    bridge = bridge or CvBridge()
    normalized_format = _normalize_image_format(image_format)

    cv_image = bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
    extension = f".{normalized_format}"
    ok, encoded = cv2.imencode(extension, cv_image)
    if not ok:
        raise ValueError(f"failed to encode image as {normalized_format}")

    content_type = _content_type_for_format(normalized_format)
    filename = f"snapshot.{normalized_format}"
    return filename, content_type, encoded.tobytes()


def encode_compressed_image_message(
    msg: CompressedImage,
    *,
    image_format: str = "jpg",
) -> tuple[str, str, bytes]:
    """Prepare a ROS CompressedImage message for AI Server upload.

    If the transport already carries JPEG/PNG bytes, keep them unchanged.  This
    avoids unnecessary decode/re-encode work on robot camera streams.  If the
    format is missing or not one of the AI Server upload formats, decode and
    re-encode to the requested image_format.
    """

    requested_format = _normalize_image_format(image_format)
    transport_format = _compressed_format(msg)
    payload = bytes(msg.data)
    if not payload:
        raise ValueError("compressed image payload is empty")

    if transport_format in {"jpg", "png"}:
        content_type = _content_type_for_format(transport_format)
        filename = f"snapshot.{transport_format}"
        return filename, content_type, payload

    encoded_array = np.frombuffer(payload, dtype=np.uint8)
    cv_image = cv2.imdecode(encoded_array, cv2.IMREAD_COLOR)
    if cv_image is None:
        raise ValueError(f"failed to decode compressed image format={msg.format!r}")

    extension = f".{requested_format}"
    ok, encoded = cv2.imencode(extension, cv_image)
    if not ok:
        raise ValueError(f"failed to encode compressed image as {requested_format}")

    content_type = _content_type_for_format(requested_format)
    filename = f"snapshot.{requested_format}"
    return filename, content_type, encoded.tobytes()


def post_snapshot(
    *,
    session: requests.Session,
    url: str,
    source_id: str,
    emit: bool,
    image_file: tuple[str, str, bytes],
    timeout: float,
) -> SnapshotPostResult:
    """POST one encoded snapshot to AI Server without raising transport failures."""

    filename, content_type, image_bytes = image_file
    try:
        response = session.post(
            url,
            data={"source": source_id, "emit": str(bool(emit)).lower()},
            files={"image": (filename, image_bytes, content_type)},
            timeout=timeout,
        )
    except requests.Timeout:
        return SnapshotPostResult(ok=False, status_code=None, error="AI Server request timed out")
    except requests.RequestException as exc:
        return SnapshotPostResult(
            ok=False,
            status_code=None,
            error=f"AI Server request failed: {exc.__class__.__name__}",
        )

    if 200 <= response.status_code < 300:
        try:
            payload = response.json()
        except ValueError:
            payload = None
        return SnapshotPostResult(ok=True, status_code=response.status_code, response=payload)

    return SnapshotPostResult(
        ok=False,
        status_code=response.status_code,
        error=f"AI Server returned HTTP {response.status_code}",
    )


class ImageSnapshotClient(Node):
    """ROS image snapshot adapter for SmartFactory AI Server."""

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        bridge: CvBridge | None = None,
    ) -> None:
        super().__init__("image_snapshot_client")

        self.declare_parameter("source_id", "global_cam_01")
        self.declare_parameter("image_topic", "/global_camera/image_raw")
        self.declare_parameter("image_transport", "raw")
        self.declare_parameter("ai_server_url", "http://127.0.0.1:8100")
        self.declare_parameter("detect_path", "/api/v1/detect/image")
        self.declare_parameter("emit", False)
        self.declare_parameter("snapshot_period_sec", 1.0)
        self.declare_parameter("request_timeout_sec", 1.0)
        self.declare_parameter("image_format", "jpg")

        self.source_id = str(self.get_parameter("source_id").value)
        self.image_topic = str(self.get_parameter("image_topic").value)
        self.image_transport = str(self.get_parameter("image_transport").value).strip().lower()
        self.detect_url = build_detect_url(
            str(self.get_parameter("ai_server_url").value),
            str(self.get_parameter("detect_path").value),
        )
        self.emit = bool(self.get_parameter("emit").value)
        self.snapshot_period_sec = max(0.1, float(self.get_parameter("snapshot_period_sec").value))
        self.request_timeout_sec = max(0.1, float(self.get_parameter("request_timeout_sec").value))
        self.image_format = str(self.get_parameter("image_format").value)

        if self.source_id not in VALID_SOURCE_IDS:
            self.get_logger().warning(
                f"source_id {self.source_id!r} is not one of {sorted(VALID_SOURCE_IDS)}"
            )
        if self.image_transport not in VALID_IMAGE_TRANSPORTS:
            raise ValueError(
                f"image_transport must be one of {sorted(VALID_IMAGE_TRANSPORTS)}, "
                f"got {self.image_transport!r}"
            )

        self._bridge = bridge or CvBridge()
        self._session = session or requests.Session()
        self._latest_msg: Image | CompressedImage | None = None
        self._latest_frame_id = 0
        self._last_attempted_frame_id = 0
        self._received_frames = 0
        self._post_attempts = 0
        self._post_successes = 0
        self._post_failures = 0

        if self.image_transport == "compressed":
            self.create_subscription(
                CompressedImage,
                self.image_topic,
                self._on_compressed_image,
                qos_profile_sensor_data,
            )
        else:
            self.create_subscription(
                Image,
                self.image_topic,
                self._on_image,
                qos_profile_sensor_data,
            )
        self.create_timer(self.snapshot_period_sec, self._on_timer)

        self.get_logger().info(
            "SmartFactory image snapshot client ready: "
            f"source_id={self.source_id}, topic={self.image_topic}, "
            f"transport={self.image_transport}, url={self.detect_url}, "
            f"period={self.snapshot_period_sec:.2f}s, emit={self.emit}"
        )

    @property
    def diagnostics(self) -> dict[str, int]:
        return {
            "received_frames": self._received_frames,
            "post_attempts": self._post_attempts,
            "post_successes": self._post_successes,
            "post_failures": self._post_failures,
        }

    def _on_image(self, msg: Image) -> None:
        self._store_latest_msg(msg)

    def _on_compressed_image(self, msg: CompressedImage) -> None:
        self._store_latest_msg(msg)

    def _store_latest_msg(self, msg: Image | CompressedImage) -> None:
        self._received_frames += 1
        self._latest_frame_id = self._received_frames
        self._latest_msg = msg

    def _encode_latest_msg(self) -> tuple[str, str, bytes]:
        if self._latest_msg is None:
            raise ValueError("no latest image message")
        if isinstance(self._latest_msg, CompressedImage):
            return encode_compressed_image_message(
                self._latest_msg,
                image_format=self.image_format,
            )
        return encode_image_message(
            self._latest_msg,
            bridge=self._bridge,
            image_format=self.image_format,
        )

    def _on_timer(self) -> None:
        if self._latest_msg is None:
            self.get_logger().debug("No image received yet; skipping AI Server snapshot POST")
            return
        if self._latest_frame_id == self._last_attempted_frame_id:
            self.get_logger().debug("No new image since last snapshot POST; skipping stale frame")
            return
        self._last_attempted_frame_id = self._latest_frame_id

        try:
            image_file = self._encode_latest_msg()
        except Exception as exc:  # noqa: BLE001 - ROS callback should not crash on bad frame
            self._post_failures += 1
            self.get_logger().warning(f"Failed to encode image snapshot: {exc}")
            return

        self._post_attempts += 1
        result = post_snapshot(
            session=self._session,
            url=self.detect_url,
            source_id=self.source_id,
            emit=self.emit,
            image_file=image_file,
            timeout=self.request_timeout_sec,
        )
        if result.ok:
            self._post_successes += 1
            self.get_logger().debug(
                "AI Server snapshot accepted: "
                f"status={result.status_code}, source={self.source_id}"
            )
        else:
            self._post_failures += 1
            self.get_logger().warning(
                f"AI Server snapshot failed: status={result.status_code}, error={result.error}"
            )


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = ImageSnapshotClient()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    main()
