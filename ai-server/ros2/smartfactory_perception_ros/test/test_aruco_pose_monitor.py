from __future__ import annotations

import cv2
import numpy as np
import pytest
import rclpy
from sensor_msgs.msg import CompressedImage

from smartfactory_perception_ros.aruco_pose_monitor import (
    ArucoPoseMonitor,
    PassiveArucoPoseMonitor,
    PoseMonitorConfig,
    decode_compressed_bgr,
    format_observation,
    normalize_marker_id,
)
from app.docking import CameraIntrinsics, DockingTarget, DockingTolerances


def _marker_image(marker_id: int = 0, marker_size: int = 96, padding: int = 32) -> np.ndarray:
    dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    if hasattr(cv2.aruco, "generateImageMarker"):
        marker = cv2.aruco.generateImageMarker(dictionary, marker_id, marker_size)
    else:
        marker = np.zeros((marker_size, marker_size), dtype=np.uint8)
        cv2.aruco.drawMarker(dictionary, marker_id, marker_size, marker, 1)
    canvas_size = marker_size + padding * 2
    canvas = np.full((canvas_size, canvas_size), 255, dtype=np.uint8)
    canvas[padding : padding + marker_size, padding : padding + marker_size] = marker
    return cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR)


def _compressed_msg(image: np.ndarray) -> CompressedImage:
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    msg = CompressedImage()
    msg.format = "jpeg"
    msg.data = encoded.tobytes()
    return msg


def _config(target_marker_id="ARUCO_4X4_50_0") -> PoseMonitorConfig:
    return PoseMonitorConfig(
        target_marker_id=target_marker_id,
        marker_size_m=0.08,
        intrinsics=CameraIntrinsics(fx=600.0, fy=600.0, cx=80.0, cy=80.0),
        target=DockingTarget(distance_m=0.50),
        tolerances=DockingTolerances(lateral_m=0.04, distance_m=0.04, yaw_rad=0.1),
        stable_frames_required=2,
        stale_timeout_sec=0.2,
    )


def test_normalize_marker_id_accepts_empty_full_and_numeric_values():
    assert normalize_marker_id(0) == "ARUCO_4X4_50_0"
    assert normalize_marker_id("7") == "ARUCO_4X4_50_7"
    assert normalize_marker_id("ARUCO_4X4_50_3") == "ARUCO_4X4_50_3"
    assert normalize_marker_id("") is None


def test_passive_monitor_detects_target_marker_and_computes_pose_error():
    monitor = PassiveArucoPoseMonitor(_config())

    observation = monitor.process_bgr_image(_marker_image(0), now=10.0)

    assert observation.marker_id == "ARUCO_4X4_50_0"
    assert observation.pose is not None
    assert observation.pose.distance_m > 0.0
    assert observation.error.visible is True
    assert observation.state in {"tracking", "aligned"}
    assert "advisory_only" in format_observation(observation)


def test_passive_monitor_reports_marker_lost_when_target_is_absent():
    monitor = PassiveArucoPoseMonitor(_config(target_marker_id="ARUCO_4X4_50_99"))

    observation = monitor.process_bgr_image(_marker_image(0), now=10.0)

    assert observation.state == "marker_lost"
    assert observation.pose is None
    assert observation.error.visible is False
    assert observation.advisory_command.reason == "marker_lost"
    assert "ARUCO_4X4_50_0" in observation.detections_seen


def test_passive_monitor_reports_waiting_and_stale_states_with_fake_clock():
    monitor = PassiveArucoPoseMonitor(_config())

    assert monitor.status(now=1.0).state == "waiting_for_frame"
    monitor.process_bgr_image(_marker_image(0), now=1.0)

    assert monitor.status(now=1.1).state != "stale"
    assert monitor.status(now=1.3).state == "stale"


def test_passive_monitor_fps_uses_recent_frame_timestamps():
    monitor = PassiveArucoPoseMonitor(_config())

    monitor.process_bgr_image(_marker_image(0), now=1.0)
    observation = monitor.process_bgr_image(_marker_image(0), now=1.5)

    assert observation.fps == pytest.approx(2.0, abs=0.01)


def test_decode_compressed_bgr_decodes_jpeg_payload():
    image = _marker_image(0)
    decoded = decode_compressed_bgr(_compressed_msg(image))

    assert decoded.shape == image.shape


def test_ros_node_processes_compressed_frame_without_creating_publishers():
    rclpy.init(args=[
        "--ros-args",
        "-p",
        "target_marker_id:=ARUCO_4X4_50_0",
        "-p",
        "camera_cx:=80.0",
        "-p",
        "camera_cy:=80.0",
        "-p",
        "stable_frames_required:=2",
    ])
    node = ArucoPoseMonitor()
    try:
        node._on_compressed_image(_compressed_msg(_marker_image(0)))
        assert node.diagnostics["received_frames"] == 1
        assert node.diagnostics["processed_frames"] == 1
        assert node.diagnostics["state"] in {"tracking", "aligned"}
        publishers = node.get_publisher_names_and_types_by_node(node.get_name(), node.get_namespace())
        assert all(name != "/cmd_vel" for name, _types in publishers)
    finally:
        node.destroy_node()
        rclpy.shutdown()
