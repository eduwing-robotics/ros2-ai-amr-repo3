from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from pathlib import Path
import os
import sys
import time
from typing import Sequence

import cv2
import numpy as np
from cv_bridge import CvBridge
import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage, Image


def _ensure_ai_server_app_importable() -> None:
    """Allow this ROS package to reuse services/ai-server pure logic in-place.

    In development this package lives under ``<repo>/ros2/...`` while the shared
    deterministic perception helpers live under ``<repo>/services/ai-server``.
    The central-PC monitor is intentionally a thin ROS adapter around that pure
    code.  Operators may also set ``SMARTFACTORY_AI_SERVER_PYTHONPATH`` when the
    package is installed outside the repository tree.
    """

    try:
        import app.docking  # noqa: F401
        import app.detectors  # noqa: F401
        return
    except ModuleNotFoundError:
        pass

    candidates: list[Path] = []
    if env_value := os.environ.get("SMARTFACTORY_AI_SERVER_PYTHONPATH"):
        candidates.append(Path(env_value).expanduser())
    if repo_root := os.environ.get("SMARTFACTORY_REPO_ROOT"):
        candidates.append(Path(repo_root).expanduser() / "services" / "ai-server")
    candidates.append(Path.cwd() / "services" / "ai-server")
    for parent in Path(__file__).resolve().parents:
        candidates.append(parent / "services" / "ai-server")

    for candidate in candidates:
        if (candidate / "app" / "docking.py").exists():
            sys.path.insert(0, str(candidate))
            return


_ensure_ai_server_app_importable()

from app.detectors import MarkerDetection, detect_markers  # noqa: E402
from app.docking import (  # noqa: E402
    CameraIntrinsics,
    DockingCommand,
    DockingError,
    DockingGains,
    DockingLimits,
    DockingTarget,
    DockingTolerances,
    MarkerPose,
    compute_docking_error,
    estimate_marker_pose,
    is_aligned,
    lost_marker_error,
    propose_docking_command,
    stable_alignment_count,
)

VALID_IMAGE_TRANSPORTS = {"raw", "compressed"}


@dataclass(frozen=True)
class PoseMonitorConfig:
    """Static configuration for passive ArUco pose monitoring."""

    target_marker_id: str | None
    marker_size_m: float
    intrinsics: CameraIntrinsics
    target: DockingTarget
    tolerances: DockingTolerances = DockingTolerances()
    gains: DockingGains = DockingGains()
    limits: DockingLimits = DockingLimits()
    stable_frames_required: int = 5
    stale_timeout_sec: float = 0.3


@dataclass(frozen=True)
class PoseObservation:
    """One passive monitor observation from a processed frame.

    This is diagnostic evidence only.  The optional command proposal is never
    published by this module; it exists to help tune signs/gains before a later,
    permission-gated controller is introduced.
    """

    state: str
    frame_id: int
    stamp_monotonic: float
    fps: float
    detections_seen: tuple[str, ...]
    marker_id: str | None
    pose: MarkerPose | None
    error: DockingError
    aligned: bool
    stable_alignment_frames: int
    advisory_command: DockingCommand


@dataclass(frozen=True)
class PoseMonitorStatus:
    state: str
    last_frame_id: int
    last_frame_age_sec: float | None
    fps: float
    last_observation: PoseObservation | None


def normalize_marker_id(value: str | int | None) -> str | None:
    """Normalize operator marker-id input to detector IDs.

    ``0`` and ``"0"`` become ``"ARUCO_4X4_50_0"``.  Empty values mean "use the
    first detected marker".
    """

    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return f"ARUCO_4X4_50_{int(text)}"
    return text


def select_target_detection(
    detections: Sequence[MarkerDetection],
    target_marker_id: str | None,
) -> MarkerDetection | None:
    if not detections:
        return None
    if target_marker_id is None:
        return detections[0]
    for detection in detections:
        if detection.marker_id == target_marker_id:
            return detection
    return None


class PassiveArucoPoseMonitor:
    """Robot-free/passive ArUco pose monitor core.

    The core has no ROS dependency and performs no actuation.  ROS nodes and
    synthetic tests can feed BGR images into it and inspect the resulting pose,
    docking error, FPS, marker-lost and stale states.
    """

    def __init__(self, config: PoseMonitorConfig, *, clock=time.monotonic) -> None:
        if config.marker_size_m <= 0:
            raise ValueError("marker_size_m must be positive")
        if config.stable_frames_required < 1:
            raise ValueError("stable_frames_required must be >= 1")
        self.config = config
        self._clock = clock
        self._frame_id = 0
        self._timestamps: deque[float] = deque(maxlen=30)
        self._errors: deque[DockingError] = deque(maxlen=max(1, config.stable_frames_required))
        self._last_observation: PoseObservation | None = None

    @property
    def last_observation(self) -> PoseObservation | None:
        return self._last_observation

    def process_bgr_image(self, image: np.ndarray, *, now: float | None = None) -> PoseObservation:
        now = self._clock() if now is None else float(now)
        if image is None or image.size == 0:
            raise ValueError("image must be a non-empty OpenCV BGR array")

        self._frame_id += 1
        self._timestamps.append(now)
        detections = detect_markers(image)
        detections_seen = tuple(detection.marker_id for detection in detections)
        selected = select_target_detection(detections, self.config.target_marker_id)
        fps = self._fps()

        if selected is None or not selected.corners_xy:
            error = lost_marker_error()
            self._errors.append(error)
            observation = PoseObservation(
                state="marker_lost",
                frame_id=self._frame_id,
                stamp_monotonic=now,
                fps=fps,
                detections_seen=detections_seen,
                marker_id=None,
                pose=None,
                error=error,
                aligned=False,
                stable_alignment_frames=0,
                advisory_command=propose_docking_command(
                    error,
                    tolerances=self.config.tolerances,
                    gains=self.config.gains,
                    limits=self.config.limits,
                ),
            )
            self._last_observation = observation
            return observation

        pose = estimate_marker_pose(
            selected.corners_xy,
            marker_size_m=self.config.marker_size_m,
            intrinsics=self.config.intrinsics,
        )
        error = compute_docking_error(pose, self.config.target)
        self._errors.append(error)
        aligned = is_aligned(error, self.config.tolerances)
        stable_frames = stable_alignment_count(tuple(self._errors), self.config.tolerances)
        state = "aligned" if aligned and stable_frames >= self.config.stable_frames_required else "tracking"

        observation = PoseObservation(
            state=state,
            frame_id=self._frame_id,
            stamp_monotonic=now,
            fps=fps,
            detections_seen=detections_seen,
            marker_id=selected.marker_id,
            pose=pose,
            error=error,
            aligned=aligned,
            stable_alignment_frames=stable_frames,
            advisory_command=propose_docking_command(
                error,
                tolerances=self.config.tolerances,
                gains=self.config.gains,
                limits=self.config.limits,
            ),
        )
        self._last_observation = observation
        return observation

    def status(self, *, now: float | None = None) -> PoseMonitorStatus:
        now = self._clock() if now is None else float(now)
        if self._last_observation is None:
            return PoseMonitorStatus(
                state="waiting_for_frame",
                last_frame_id=0,
                last_frame_age_sec=None,
                fps=0.0,
                last_observation=None,
            )

        age = max(0.0, now - self._last_observation.stamp_monotonic)
        state = "stale" if age > self.config.stale_timeout_sec else self._last_observation.state
        return PoseMonitorStatus(
            state=state,
            last_frame_id=self._last_observation.frame_id,
            last_frame_age_sec=age,
            fps=self._fps(),
            last_observation=self._last_observation,
        )

    def _fps(self) -> float:
        if len(self._timestamps) < 2:
            return 0.0
        elapsed = self._timestamps[-1] - self._timestamps[0]
        if elapsed <= 0:
            return 0.0
        return (len(self._timestamps) - 1) / elapsed


def decode_compressed_bgr(msg: CompressedImage) -> np.ndarray:
    payload = np.frombuffer(bytes(msg.data), dtype=np.uint8)
    if payload.size == 0:
        raise ValueError("compressed image payload is empty")
    image = cv2.imdecode(payload, cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"failed to decode compressed image format={msg.format!r}")
    return image


def format_observation(observation: PoseObservation) -> str:
    if observation.pose is None:
        return (
            f"state={observation.state} frame={observation.frame_id} "
            f"fps={observation.fps:.1f} seen={list(observation.detections_seen)}"
        )
    pose = observation.pose
    error = observation.error
    command = observation.advisory_command
    return (
        f"state={observation.state} frame={observation.frame_id} marker={observation.marker_id} "
        f"fps={observation.fps:.1f} "
        f"pose[x={pose.lateral_m:+.3f}m,z={pose.distance_m:.3f}m,yaw={pose.yaw_rad:+.3f}rad] "
        f"error[lat={error.lateral_error_m:+.3f}m,dist={error.distance_error_m:+.3f}m,"
        f"yaw={error.yaw_error_rad:+.3f}rad] "
        f"aligned={observation.aligned} stable={observation.stable_alignment_frames} "
        f"advisory_only[linear={command.linear_x_mps:+.3f},angular={command.angular_z_radps:+.3f},"
        f"reason={command.reason}]"
    )


class ArucoPoseMonitor(Node):
    """Central-PC passive ArUco pose/error monitor.

    Safety boundary: this node subscribes to camera images and logs diagnostic
    evidence only.  It intentionally creates no application command publishers and never
    publishes to ``/cmd_vel``.
    """

    def __init__(self, *, bridge: CvBridge | None = None) -> None:
        super().__init__("aruco_pose_monitor")

        self.declare_parameter("image_topic", "/camera/image_raw/compressed")
        self.declare_parameter("image_transport", "compressed")
        self.declare_parameter("target_marker_id", "ARUCO_4X4_50_0")
        self.declare_parameter("marker_size_m", 0.08)
        self.declare_parameter("camera_fx", 600.0)
        self.declare_parameter("camera_fy", 600.0)
        self.declare_parameter("camera_cx", 320.0)
        self.declare_parameter("camera_cy", 240.0)
        self.declare_parameter("camera_dist_coeffs", [0.0, 0.0, 0.0, 0.0, 0.0])
        self.declare_parameter("target_distance_m", 0.45)
        self.declare_parameter("target_lateral_offset_m", 0.0)
        self.declare_parameter("target_yaw_rad", 0.0)
        self.declare_parameter("tolerance_lateral_m", 0.04)
        self.declare_parameter("tolerance_distance_m", 0.04)
        self.declare_parameter("tolerance_yaw_rad", 0.0872664626)
        self.declare_parameter("stable_frames_required", 5)
        self.declare_parameter("stale_timeout_sec", 0.3)
        self.declare_parameter("log_period_sec", 0.5)

        self.image_topic = str(self.get_parameter("image_topic").value)
        self.image_transport = str(self.get_parameter("image_transport").value).strip().lower()
        if self.image_transport not in VALID_IMAGE_TRANSPORTS:
            raise ValueError(
                f"image_transport must be one of {sorted(VALID_IMAGE_TRANSPORTS)}, "
                f"got {self.image_transport!r}"
            )

        dist_value = self.get_parameter("camera_dist_coeffs").value
        dist_coeffs = tuple(float(v) for v in (dist_value or []))
        config = PoseMonitorConfig(
            target_marker_id=normalize_marker_id(self.get_parameter("target_marker_id").value),
            marker_size_m=float(self.get_parameter("marker_size_m").value),
            intrinsics=CameraIntrinsics(
                fx=float(self.get_parameter("camera_fx").value),
                fy=float(self.get_parameter("camera_fy").value),
                cx=float(self.get_parameter("camera_cx").value),
                cy=float(self.get_parameter("camera_cy").value),
                dist_coeffs=dist_coeffs,
            ),
            target=DockingTarget(
                distance_m=float(self.get_parameter("target_distance_m").value),
                lateral_offset_m=float(self.get_parameter("target_lateral_offset_m").value),
                yaw_rad=float(self.get_parameter("target_yaw_rad").value),
            ),
            tolerances=DockingTolerances(
                lateral_m=float(self.get_parameter("tolerance_lateral_m").value),
                distance_m=float(self.get_parameter("tolerance_distance_m").value),
                yaw_rad=float(self.get_parameter("tolerance_yaw_rad").value),
            ),
            stable_frames_required=int(self.get_parameter("stable_frames_required").value),
            stale_timeout_sec=float(self.get_parameter("stale_timeout_sec").value),
        )
        self.monitor = PassiveArucoPoseMonitor(config)
        self._bridge = bridge or CvBridge()
        self._received_frames = 0
        self._processed_frames = 0
        self._decode_failures = 0
        self._marker_lost_frames = 0
        self._last_log_frame_id = 0

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
        log_period = max(0.1, float(self.get_parameter("log_period_sec").value))
        self.create_timer(log_period, self._on_log_timer)

        self.get_logger().info(
            "SmartFactory passive ArUco pose monitor ready: "
            f"topic={self.image_topic}, transport={self.image_transport}, "
            f"target_marker_id={config.target_marker_id}, marker_size_m={config.marker_size_m:.3f}. "
            "No command publishers are created; /cmd_vel is never published."
        )

    @property
    def diagnostics(self) -> dict[str, int | str | float]:
        status = self.monitor.status()
        return {
            "received_frames": self._received_frames,
            "processed_frames": self._processed_frames,
            "decode_failures": self._decode_failures,
            "marker_lost_frames": self._marker_lost_frames,
            "last_frame_id": status.last_frame_id,
            "state": status.state,
            "fps": status.fps,
        }

    def _on_image(self, msg: Image) -> None:
        self._received_frames += 1
        try:
            image = self._bridge.imgmsg_to_cv2(msg, desired_encoding="bgr8")
            self._process_image(image)
        except Exception as exc:  # noqa: BLE001 - ROS callbacks should survive bad frames
            self._decode_failures += 1
            self.get_logger().warning(f"Failed to process raw image for ArUco pose monitor: {exc}")

    def _on_compressed_image(self, msg: CompressedImage) -> None:
        self._received_frames += 1
        try:
            self._process_image(decode_compressed_bgr(msg))
        except Exception as exc:  # noqa: BLE001 - ROS callbacks should survive bad frames
            self._decode_failures += 1
            self.get_logger().warning(
                f"Failed to process compressed image for ArUco pose monitor: {exc}"
            )

    def _process_image(self, image: np.ndarray) -> PoseObservation:
        observation = self.monitor.process_bgr_image(image)
        self._processed_frames += 1
        if observation.state == "marker_lost":
            self._marker_lost_frames += 1
        return observation

    def _on_log_timer(self) -> None:
        status = self.monitor.status()
        if status.last_observation is None:
            self.get_logger().info("ArUco pose monitor waiting_for_frame")
            return
        if status.state == "stale":
            age = status.last_frame_age_sec or 0.0
            self.get_logger().warning(
                f"ArUco pose monitor stale: last_frame={status.last_frame_id} age={age:.3f}s "
                f"fps={status.fps:.1f}"
            )
            return
        if status.last_frame_id == self._last_log_frame_id:
            return
        self._last_log_frame_id = status.last_frame_id
        self.get_logger().info(format_observation(status.last_observation))


def main(args: list[str] | None = None) -> None:
    rclpy.init(args=args)
    node = ArucoPoseMonitor()
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
