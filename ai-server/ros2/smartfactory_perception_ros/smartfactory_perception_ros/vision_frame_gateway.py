from __future__ import annotations

from dataclasses import dataclass
import json
import threading
import time
from typing import Any

import requests
from cv_bridge import CvBridge
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage, Image
from std_msgs.msg import String

from .image_snapshot_client import (
    VALID_IMAGE_TRANSPORTS,
    VALID_SOURCE_IDS,
    encode_compressed_image_message,
    encode_image_message,
)
from .qos_profiles import build_bounded_image_qos_profile as build_qos_profile
from .vision_frame_gateway_helpers import (
    _json_path_int,
    assert_safe_input_topic,
    assert_safe_publish_topic,
    build_ai_server_url,
    frame_seq_from_post_response,
    overlay_seq_from_metadata,
    topic_has_forbidden_fragment,
)
from .vision_frame_gateway_http import (
    HttpResult,
    get_bytes,
    get_json,
    post_frame,
    post_frame_process,
    post_worker_tick,
)


@dataclass(frozen=True)
class PendingFrameWork:
    frame_id: int
    msg: Image | CompressedImage
    header: Any | None
    enqueued_monotonic_s: float


@dataclass(frozen=True)
class PendingOverlayPublish:
    header: Any | None
    content: bytes
    content_type: str | None
    frame_seq: int | None


@dataclass(frozen=True)
class FramePostOutcome:
    frame_result: HttpResult
    worker_result: HttpResult | None
    posted_frame_seq: int | None


class VisionFrameGateway(Node):
    """Lane C passive ROS image ingest sidecar.

    The node subscribes to an allowed camera image topic, posts latest frames to
    the AI Server `/api/v1/vision/frame` seam, and can optionally publish safe
    `/sf/vision/...` overlay/evidence outputs. It never creates motion/control
    publishers and never calls Nav2 actions.
    """

    def __init__(
        self,
        *,
        session: requests.Session | None = None,
        bridge: CvBridge | None = None,
    ) -> None:
        super().__init__("vision_frame_gateway")

        self._declare_gateway_parameters()
        self._load_gateway_parameters()
        self._validate_gateway_parameters()
        self._initialize_runtime_state(session=session, bridge=bridge)
        self._setup_ros_interfaces()
        self._start_async_worker_if_enabled()
        self._log_gateway_ready()

    def _declare_gateway_parameters(self) -> None:
        self.declare_parameter("source_id", "tb3_1_picam")
        self.declare_parameter("image_topic", "/tb3_1/camera/image_raw/compressed")
        self.declare_parameter("image_transport", "compressed")
        self.declare_parameter("ai_server_url", "http://127.0.0.1:8100")
        self.declare_parameter("frame_ingest_path", "/api/v1/vision/frame")
        self.declare_parameter("frame_process_path", "/api/v1/vision/frame/process")
        self.declare_parameter("worker_tick_path", "/api/v1/vision/worker/tick")
        self.declare_parameter("overlay_image_path", "/api/v1/vision/overlay/latest/image")
        self.declare_parameter("overlay_metadata_path", "/api/v1/vision/overlay/latest")
        self.declare_parameter("overlay_topic", "/sf/vision/sources/tb3_1_picam/overlay/compressed")
        self.declare_parameter("evidence_topic", "/sf/vision/events")
        self.declare_parameter("request_timeout_sec", 1.0)
        self.declare_parameter("publish_period_sec", 0.2)
        self.declare_parameter("publish_output_period_sec", 0.02)
        self.declare_parameter("image_format", "jpg")
        self.declare_parameter("image_qos_reliability", "sensor_data")
        self.declare_parameter("image_qos_depth", 1)
        self.declare_parameter("overlay_pub_qos_reliability", "reliable")
        self.declare_parameter("overlay_pub_qos_depth", 1)
        self.declare_parameter("async_pipeline", True)
        self.declare_parameter("retry_failed_frame", True)
        self.declare_parameter("retry_backoff_sec", 0.05)
        self.declare_parameter("publish_lagging_overlay", False)
        self.declare_parameter("process_frame_inline", True)
        self.declare_parameter("process_with_worker_tick", False)
        self.declare_parameter("force_worker_tick", False)
        self.declare_parameter("mark_worker_tick_stale", False)
        self.declare_parameter("publish_overlay", False)
        self.declare_parameter("publish_evidence", False)

    def _load_gateway_parameters(self) -> None:
        self.source_id = str(self.get_parameter("source_id").value)
        self.image_topic = str(self.get_parameter("image_topic").value)
        self.image_transport = str(self.get_parameter("image_transport").value).strip().lower()
        ai_server_url = str(self.get_parameter("ai_server_url").value)
        self.frame_ingest_url = build_ai_server_url(
            ai_server_url, str(self.get_parameter("frame_ingest_path").value)
        )
        self.frame_process_url = build_ai_server_url(
            ai_server_url, str(self.get_parameter("frame_process_path").value)
        )
        self.worker_tick_url = build_ai_server_url(
            ai_server_url, str(self.get_parameter("worker_tick_path").value)
        )
        self.overlay_image_url = build_ai_server_url(
            ai_server_url, str(self.get_parameter("overlay_image_path").value)
        )
        self.overlay_metadata_url = build_ai_server_url(
            ai_server_url, str(self.get_parameter("overlay_metadata_path").value)
        )
        self.overlay_topic = str(self.get_parameter("overlay_topic").value)
        self.evidence_topic = str(self.get_parameter("evidence_topic").value)
        self.request_timeout_sec = max(0.1, float(self.get_parameter("request_timeout_sec").value))
        self.publish_period_sec = max(0.001, float(self.get_parameter("publish_period_sec").value))
        self.publish_output_period_sec = max(
            0.001, float(self.get_parameter("publish_output_period_sec").value)
        )
        self.image_format = str(self.get_parameter("image_format").value)
        self.image_qos_reliability = str(self.get_parameter("image_qos_reliability").value)
        self.image_qos_depth = max(1, int(self.get_parameter("image_qos_depth").value))
        self.overlay_pub_qos_reliability = str(
            self.get_parameter("overlay_pub_qos_reliability").value
        )
        self.overlay_pub_qos_depth = max(1, int(self.get_parameter("overlay_pub_qos_depth").value))
        self.async_pipeline = bool(self.get_parameter("async_pipeline").value)
        self.retry_failed_frame = bool(self.get_parameter("retry_failed_frame").value)
        self.retry_backoff_sec = max(0.0, float(self.get_parameter("retry_backoff_sec").value))
        self.publish_lagging_overlay = bool(self.get_parameter("publish_lagging_overlay").value)
        self.process_frame_inline = bool(self.get_parameter("process_frame_inline").value)
        self.process_with_worker_tick = bool(self.get_parameter("process_with_worker_tick").value)
        self.force_worker_tick = bool(self.get_parameter("force_worker_tick").value)
        self.mark_worker_tick_stale = bool(self.get_parameter("mark_worker_tick_stale").value)
        self.publish_overlay_enabled = bool(self.get_parameter("publish_overlay").value)
        self.publish_evidence_enabled = bool(self.get_parameter("publish_evidence").value)

    def _validate_gateway_parameters(self) -> None:
        if self.source_id not in VALID_SOURCE_IDS:
            self.get_logger().warning(
                f"source_id {self.source_id!r} is not one of {sorted(VALID_SOURCE_IDS)}"
            )
        if self.image_transport not in VALID_IMAGE_TRANSPORTS:
            raise ValueError(
                f"image_transport must be one of {sorted(VALID_IMAGE_TRANSPORTS)}, "
                f"got {self.image_transport!r}"
            )
        assert_safe_input_topic(self.image_topic)
        assert_safe_publish_topic(self.overlay_topic, role="overlay")
        assert_safe_publish_topic(self.evidence_topic, role="evidence")

    def _initialize_runtime_state(
        self,
        *,
        session: requests.Session | None,
        bridge: CvBridge | None,
    ) -> None:
        self._bridge = bridge or CvBridge()
        self._session = session or requests.Session()
        self._latest_lock = threading.Lock()
        self._latest_msg: Image | CompressedImage | None = None
        self._latest_header = None
        self._latest_frame_id = 0
        self._last_attempted_frame_id = 0
        self._received_frames = 0
        self._frame_post_attempts = 0
        self._frame_post_successes = 0
        self._frame_post_failures = 0
        self._worker_tick_attempts = 0
        self._worker_tick_successes = 0
        self._overlay_publish_attempts = 0
        self._overlay_publish_successes = 0
        self._evidence_publish_attempts = 0
        self._evidence_publish_successes = 0
        self._work_enqueued = 0
        self._work_replaced = 0
        self._work_processed = 0
        self._work_retries = 0
        self._overlay_publish_skips = 0
        self._last_overlay_publish_frame_seq = 0
        self._shutdown_event = threading.Event()
        self._work_condition = threading.Condition()
        self._pending_work: PendingFrameWork | None = None
        self._pending_overlay_lock = threading.Lock()
        self._pending_overlay_publish: PendingOverlayPublish | None = None
        self._pending_evidence_payload: str | None = None
        self._worker_thread: threading.Thread | None = None

    def _setup_ros_interfaces(self) -> None:
        image_qos = build_qos_profile(
            self.image_qos_reliability,
            depth=self.image_qos_depth,
            role="image input",
        )
        overlay_pub_qos = build_qos_profile(
            self.overlay_pub_qos_reliability,
            depth=self.overlay_pub_qos_depth,
            role="overlay publish",
        )

        self._overlay_pub = self.create_publisher(CompressedImage, self.overlay_topic, overlay_pub_qos)
        self._evidence_pub = self.create_publisher(String, self.evidence_topic, 10)

        if self.image_transport == "compressed":
            self.create_subscription(
                CompressedImage,
                self.image_topic,
                self._on_compressed_image,
                image_qos,
            )
        else:
            self.create_subscription(Image, self.image_topic, self._on_image, image_qos)
        self.create_timer(self.publish_period_sec, self._on_timer)
        self.create_timer(self.publish_output_period_sec, self._publish_pending_outputs)

    def _start_async_worker_if_enabled(self) -> None:
        if self.async_pipeline:
            self._worker_thread = threading.Thread(
                target=self._http_worker_loop,
                name=f"sf-vision-frame-gateway-{self.source_id}",
                daemon=True,
            )
            self._worker_thread.start()

    def _log_gateway_ready(self) -> None:
        self.get_logger().info(
            "SmartFactory Lane C vision frame gateway ready: "
            f"source_id={self.source_id}, image_topic={self.image_topic}, "
            f"overlay_topic={self.overlay_topic}, evidence_topic={self.evidence_topic}, "
            f"frame_url={self.frame_ingest_url}, frame_process_url={self.frame_process_url}, "
            f"process_frame_inline={self.process_frame_inline}, "
            f"process_with_worker_tick={self.process_with_worker_tick}, "
            f"publish_overlay={self.publish_overlay_enabled}, publish_evidence={self.publish_evidence_enabled}, "
            f"async_pipeline={self.async_pipeline}, image_qos={self.image_qos_reliability}, "
            f"overlay_pub_qos={self.overlay_pub_qos_reliability}"
        )

    @property
    def diagnostics(self) -> dict[str, int | str | bool]:
        return self._diagnostics_snapshot()

    def _diagnostics_snapshot(self) -> dict[str, int | str | bool]:
        return {
            "source_id": self.source_id,
            "image_topic": self.image_topic,
            "overlay_topic": self.overlay_topic,
            "evidence_topic": self.evidence_topic,
            "process_with_worker_tick": self.process_with_worker_tick,
            "publish_overlay": self.publish_overlay_enabled,
            "publish_evidence": self.publish_evidence_enabled,
            "async_pipeline": self.async_pipeline,
            "process_frame_inline": self.process_frame_inline,
            "image_qos_reliability": self.image_qos_reliability,
            "overlay_pub_qos_reliability": self.overlay_pub_qos_reliability,
            "received_frames": self._received_frames,
            "frame_post_attempts": self._frame_post_attempts,
            "frame_post_successes": self._frame_post_successes,
            "frame_post_failures": self._frame_post_failures,
            "worker_tick_attempts": self._worker_tick_attempts,
            "worker_tick_successes": self._worker_tick_successes,
            "overlay_publish_attempts": self._overlay_publish_attempts,
            "overlay_publish_successes": self._overlay_publish_successes,
            "overlay_publish_skips": self._overlay_publish_skips,
            "evidence_publish_attempts": self._evidence_publish_attempts,
            "evidence_publish_successes": self._evidence_publish_successes,
            "work_enqueued": self._work_enqueued,
            "work_replaced": self._work_replaced,
            "work_processed": self._work_processed,
            "work_retries": self._work_retries,
        }

    def _on_image(self, msg: Image) -> None:
        self._store_latest_msg(msg)

    def _on_compressed_image(self, msg: CompressedImage) -> None:
        self._store_latest_msg(msg)

    def _store_latest_msg(self, msg: Image | CompressedImage) -> None:
        with self._latest_lock:
            self._received_frames += 1
            self._latest_frame_id = self._received_frames
            self._latest_msg = msg
            self._latest_header = getattr(msg, "header", None)

    def _encode_msg(self, msg: Image | CompressedImage | None) -> tuple[str, str, bytes]:
        if msg is None:
            raise ValueError("no latest image message")
        if isinstance(msg, CompressedImage):
            return encode_compressed_image_message(msg, image_format=self.image_format)
        return encode_image_message(msg, bridge=self._bridge, image_format=self.image_format)

    def _encode_latest_msg(self) -> tuple[str, str, bytes]:
        with self._latest_lock:
            msg = self._latest_msg
        return self._encode_msg(msg)

    def _on_timer(self) -> None:
        with self._latest_lock:
            latest_msg = self._latest_msg
            latest_header = self._latest_header
            latest_frame_id = self._latest_frame_id
        if latest_msg is None:
            self.get_logger().debug("No image received yet; skipping Lane C frame POST")
            return
        if latest_frame_id == self._last_attempted_frame_id:
            self.get_logger().debug("No new image since last Lane C frame POST; skipping")
            return

        work = PendingFrameWork(
            frame_id=latest_frame_id,
            msg=latest_msg,
            header=latest_header,
            enqueued_monotonic_s=time.monotonic(),
        )
        self._last_attempted_frame_id = latest_frame_id
        if self.async_pipeline:
            self._enqueue_frame_work(work)
            return
        self._process_frame_work(work)

    def _enqueue_frame_work(self, work: PendingFrameWork) -> None:
        with self._work_condition:
            if self._pending_work is not None:
                self._work_replaced += 1
            self._pending_work = work
            self._work_enqueued += 1
            self._work_condition.notify()

    def _take_pending_frame_work(self) -> PendingFrameWork | None:
        with self._work_condition:
            while self._pending_work is None and not self._shutdown_event.is_set():
                self._work_condition.wait(timeout=0.1)
            if self._shutdown_event.is_set():
                return None
            work = self._pending_work
            self._pending_work = None
            return work

    def _http_worker_loop(self) -> None:
        while not self._shutdown_event.is_set():
            work = self._take_pending_frame_work()
            if work is None:
                continue
            while not self._shutdown_event.is_set():
                processed = self._process_frame_work(work)
                if processed or not self.retry_failed_frame:
                    break
                with self._work_condition:
                    if self._pending_work is not None:
                        # A newer camera frame supersedes this failed one.
                        break
                    self._work_retries += 1
                    self._work_condition.wait(timeout=self.retry_backoff_sec)
                    if self._pending_work is not None:
                        break

    def _process_frame_work(self, work: PendingFrameWork) -> bool:
        try:
            image_file = self._encode_msg(work.msg)
        except Exception as exc:  # noqa: BLE001 - ROS callback should not crash on bad frame
            self._frame_post_failures += 1
            self.get_logger().warning(f"Failed to encode Lane C frame: {exc}")
            return False

        outcome = self._post_frame_work(image_file)
        if outcome is None:
            return False

        if self.publish_evidence_enabled:
            self._publish_evidence(outcome.worker_result or outcome.frame_result)
        if self.publish_overlay_enabled:
            self._stage_overlay_image_for_publish(
                work.header,
                expected_frame_seq=outcome.posted_frame_seq,
                overlay_metadata_payload=outcome.worker_result.json_body
                if outcome.worker_result is not None and outcome.worker_result.ok
                else None,
            )
        return True

    def _post_frame_work(self, image_file: tuple[str, str, bytes]) -> FramePostOutcome | None:
        if self.process_frame_inline:
            return self._post_inline_frame(image_file)
        frame_result = self._post_ingest_frame(image_file)
        if frame_result is None:
            return None
        worker_result = self._post_worker_tick_if_enabled()
        return FramePostOutcome(
            frame_result=frame_result,
            worker_result=worker_result,
            posted_frame_seq=frame_seq_from_post_response(frame_result.json_body),
        )

    def _post_inline_frame(self, image_file: tuple[str, str, bytes]) -> FramePostOutcome | None:
        self._frame_post_attempts += 1
        frame_result = post_frame_process(
            session=self._session,
            url=self.frame_process_url,
            source_id=self.source_id,
            image_file=image_file,
            timeout=self.request_timeout_sec,
            force=self.force_worker_tick,
            stale=self.mark_worker_tick_stale,
        )
        if not frame_result.ok:
            self._frame_post_failures += 1
            self.get_logger().warning(
                f"Lane C frame process failed: status={frame_result.status_code}, "
                f"error={frame_result.error}"
            )
            return None
        self._frame_post_successes += 1
        self._work_processed += 1
        if self.process_with_worker_tick:
            self._worker_tick_attempts += 1
            self._worker_tick_successes += 1
        return FramePostOutcome(
            frame_result=frame_result,
            worker_result=frame_result,
            posted_frame_seq=frame_seq_from_post_response(frame_result.json_body),
        )

    def _post_ingest_frame(self, image_file: tuple[str, str, bytes]) -> HttpResult | None:
        self._frame_post_attempts += 1
        frame_result = post_frame(
            session=self._session,
            url=self.frame_ingest_url,
            source_id=self.source_id,
            image_file=image_file,
            timeout=self.request_timeout_sec,
        )
        if not frame_result.ok:
            self._frame_post_failures += 1
            self.get_logger().warning(
                f"Lane C frame POST failed: status={frame_result.status_code}, error={frame_result.error}"
            )
            return None
        self._frame_post_successes += 1
        self._work_processed += 1
        return frame_result

    def _post_worker_tick_if_enabled(self) -> HttpResult | None:
        if not self.process_with_worker_tick:
            return None
        self._worker_tick_attempts += 1
        worker_result = post_worker_tick(
            session=self._session,
            url=self.worker_tick_url,
            source_id=self.source_id,
            timeout=self.request_timeout_sec,
            force=self.force_worker_tick,
            stale=self.mark_worker_tick_stale,
        )
        if worker_result.ok:
            self._worker_tick_successes += 1
        else:
            self.get_logger().warning(
                f"Lane C worker tick failed: status={worker_result.status_code}, "
                f"error={worker_result.error}"
            )
        return worker_result

    def _publish_evidence(self, result: HttpResult) -> None:
        self._evidence_publish_attempts += 1
        if result.json_body is None:
            return
        payload = {
            "source": self.source_id,
            "lane": "C",
            "kind": "vision_gateway_evidence_snapshot",
            "safe": True,
            "motion_control": False,
            "ai_server": result.json_body,
        }
        payload_text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        self._publish_evidence_payload(payload_text)

    def _publish_evidence_payload(self, payload_text: str) -> None:
        msg = String()
        msg.data = payload_text
        self._evidence_pub.publish(msg)
        self._evidence_publish_successes += 1

    def _stage_overlay_image_for_publish(
        self,
        header: Any | None,
        *,
        expected_frame_seq: int | None,
        overlay_metadata_payload: Any | None = None,
    ) -> None:
        self._overlay_publish_attempts += 1
        metadata_payload = overlay_metadata_payload
        if metadata_payload is None:
            metadata = get_json(
                session=self._session,
                url=self.overlay_metadata_url,
                source_id=self.source_id,
                timeout=self.request_timeout_sec,
            )
            if not metadata.ok:
                self._overlay_publish_skips += 1
                self.get_logger().debug(
                    f"No publishable Lane C overlay metadata: "
                    f"status={metadata.status_code}, error={metadata.error}"
                )
                return
            metadata_payload = metadata.json_body
        overlay_frame_seq = overlay_seq_from_metadata(metadata_payload)
        if overlay_frame_seq is None:
            self._overlay_publish_skips += 1
            if self._overlay_publish_skips <= 3:
                self.get_logger().warning("Skipping Lane C overlay publish: overlay frame_seq missing")
            return
        if overlay_frame_seq <= self._last_overlay_publish_frame_seq:
            self._overlay_publish_skips += 1
            if self._overlay_publish_skips <= 3:
                self.get_logger().warning(
                    f"Skipping Lane C overlay publish: duplicate/old overlay_frame_seq={overlay_frame_seq}"
                )
            return
        reference_frame_seq = (
            _json_path_int(metadata_payload, "sync", "latest_frame_seq")
            or _json_path_int(metadata_payload, "frame_seq")
            or expected_frame_seq
        )
        if (
            not self.publish_lagging_overlay
            and reference_frame_seq is not None
            and overlay_frame_seq != reference_frame_seq
        ):
            self._overlay_publish_skips += 1
            if self._overlay_publish_skips <= 3:
                self.get_logger().warning(
                    f"Skipping lagging Lane C overlay: overlay_frame_seq={overlay_frame_seq}, "
                    f"reference_frame_seq={reference_frame_seq}, expected_frame_seq={expected_frame_seq}"
                )
            else:
                self.get_logger().debug(
                    f"Skipping lagging Lane C overlay: overlay_frame_seq={overlay_frame_seq}, "
                    f"reference_frame_seq={reference_frame_seq}, expected_frame_seq={expected_frame_seq}"
                )
            return
        result = get_bytes(
            session=self._session,
            url=self.overlay_image_url,
            source_id=self.source_id,
            timeout=self.request_timeout_sec,
        )
        if not result.ok or not result.content:
            self._overlay_publish_skips += 1
            if self._overlay_publish_skips <= 3:
                self.get_logger().warning(
                    f"No publishable Lane C overlay image: status={result.status_code}, "
                    f"error={result.error}"
                )
            else:
                self.get_logger().debug(
                    f"No publishable Lane C overlay image: status={result.status_code}, "
                    f"error={result.error}"
                )
            return
        pending = PendingOverlayPublish(
            header=header,
            content=result.content,
            content_type=result.content_type,
            frame_seq=overlay_frame_seq,
        )
        if self.async_pipeline:
            self._publish_overlay_payload(pending)
            return
        with self._pending_overlay_lock:
            self._pending_overlay_publish = pending
        self._publish_pending_outputs()

    def _publish_pending_outputs(self) -> None:
        with self._pending_overlay_lock:
            evidence_payload = self._pending_evidence_payload
            overlay = self._pending_overlay_publish
            self._pending_evidence_payload = None
            self._pending_overlay_publish = None
        if evidence_payload:
            self._publish_evidence_payload(evidence_payload)
        if overlay is None:
            return
        self._publish_overlay_payload(overlay)

    def _publish_overlay_payload(self, overlay: PendingOverlayPublish) -> None:
        msg = CompressedImage()
        if overlay.header is not None:
            msg.header = overlay.header
        else:
            msg.header.stamp = self.get_clock().now().to_msg()
        msg.format = "jpeg" if (overlay.content_type or "").lower() != "image/png" else "png"
        msg.data = overlay.content
        self._overlay_pub.publish(msg)
        if overlay.frame_seq is not None:
            self._last_overlay_publish_frame_seq = max(
                self._last_overlay_publish_frame_seq,
                overlay.frame_seq,
            )
        self._overlay_publish_successes += 1
        if self._overlay_publish_successes <= 3 or self._overlay_publish_successes % 100 == 0:
            self.get_logger().info(
                f"Published Lane C overlay: source_id={self.source_id}, "
                f"frame_seq={overlay.frame_seq}, successes={self._overlay_publish_successes}"
            )

    def destroy_node(self) -> bool:
        self._stop_worker_thread()
        self._close_session()
        return super().destroy_node()

    def _stop_worker_thread(self) -> None:
        self._shutdown_event.set()
        with self._work_condition:
            self._work_condition.notify_all()
        if self._worker_thread is not None and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=2.0)

    def _close_session(self) -> None:
        close = getattr(self._session, "close", None)
        if callable(close):
            close()


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = VisionFrameGateway()
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
