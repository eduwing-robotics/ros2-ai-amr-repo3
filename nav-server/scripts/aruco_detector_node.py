#!/usr/bin/env python3
"""ROS2 compressed-image ArUco detector for TurtleBot3 Pi Camera.

Input:  sensor_msgs/CompressedImage, normally /mission/<tb3>/camera/compressed
Output: std_msgs/String JSON, normally /mission/<tb3>/aruco/detections

The implementation follows the project PDFs: subscribe to the compressed Pi camera
stream, decode with cv2.imdecode, then run OpenCV ArUco detection.
"""

import json
import math
import os
import time
from typing import Any, Dict, List, Optional

import cv2
import numpy as np
import rclpy
from aruco_detector_activation import activation_requested, processing_due
from aruco_pose_geometry import estimate_marker_pose
from camera_calibration import load_calibration, scale_camera_matrix
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage
from std_msgs.msg import String

ARUCO_DICTIONARIES = {
    "DICT_4X4_50": cv2.aruco.DICT_4X4_50,
    "DICT_4X4_100": cv2.aruco.DICT_4X4_100,
    "DICT_4X4_250": cv2.aruco.DICT_4X4_250,
    "DICT_4X4_1000": cv2.aruco.DICT_4X4_1000,
    "DICT_5X5_50": cv2.aruco.DICT_5X5_50,
    "DICT_5X5_100": cv2.aruco.DICT_5X5_100,
    "DICT_5X5_250": cv2.aruco.DICT_5X5_250,
    "DICT_5X5_1000": cv2.aruco.DICT_5X5_1000,
    "DICT_6X6_50": cv2.aruco.DICT_6X6_50,
    "DICT_6X6_100": cv2.aruco.DICT_6X6_100,
    "DICT_6X6_250": cv2.aruco.DICT_6X6_250,
    "DICT_6X6_1000": cv2.aruco.DICT_6X6_1000,
    "DICT_ARUCO_ORIGINAL": cv2.aruco.DICT_ARUCO_ORIGINAL,
}


def _json_param(value: str, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _as_float_list(value: Any) -> List[float]:
    if value is None:
        return []
    if isinstance(value, str):
        parsed = _json_param(value, [])
        return _as_float_list(parsed)
    if isinstance(value, (list, tuple)):
        result = []
        for item in value:
            try:
                result.append(float(item))
            except (TypeError, ValueError):
                return []
        return result
    return []


class ArucoDetectorNode(Node):
    def __init__(self):
        super().__init__("aruco_detector_node")
        default_robot = os.getenv("BRIDGE_ROBOT_ID", "tb3_1")
        default_image_topic = f"/mission/{default_robot}/camera/compressed"
        default_detection_topic = f"/mission/{default_robot}/aruco/detections"

        self.declare_parameter("image_topic", os.getenv("ARUCO_IMAGE_TOPIC", default_image_topic))
        self.declare_parameter("detection_topic", os.getenv("ARUCO_DETECTION_TOPIC", default_detection_topic))
        self.declare_parameter("dictionary", os.getenv("ARUCO_DICTIONARY", "DICT_4X4_50"))
        self.declare_parameter("marker_size_m", float(os.getenv("ARUCO_MARKER_SIZE_M", "0.055")))
        self.declare_parameter("focal_length_px", float(os.getenv("ARUCO_FOCAL_LENGTH_PX", "0")))
        self.declare_parameter("calibration_file", os.getenv("ARUCO_CALIBRATION_FILE", ""))
        self.declare_parameter("camera_matrix", os.getenv("ARUCO_CAMERA_MATRIX", ""))
        self.declare_parameter("dist_coeffs", os.getenv("ARUCO_DIST_COEFFS", ""))
        self.declare_parameter("publish_empty", os.getenv("ARUCO_PUBLISH_EMPTY", "1") not in ("0", "false", "False"))
        self.declare_parameter("min_marker_width_px", float(os.getenv("ARUCO_MIN_MARKER_WIDTH_PX", "8")))
        self.declare_parameter("process_rate_hz", float(os.getenv("ARUCO_PROCESS_RATE_HZ", "5.0")))
        self.declare_parameter(
            "enabled_on_start",
            os.getenv("ARUCO_ENABLED_ON_START", "1") not in ("0", "false", "False"),
        )
        self.declare_parameter(
            "activation_file", os.getenv("ARUCO_DETECTOR_ACTIVATION_FILE", "")
        )

        self.image_topic = str(self.get_parameter("image_topic").value)
        self.detection_topic = str(self.get_parameter("detection_topic").value)
        dictionary_name = str(self.get_parameter("dictionary").value)
        dictionary_id = ARUCO_DICTIONARIES.get(dictionary_name)
        if dictionary_id is None:
            raise ValueError(f"unsupported ArUco dictionary: {dictionary_name}")
        self.dictionary_name = dictionary_name
        self.dictionary = cv2.aruco.getPredefinedDictionary(dictionary_id)
        if hasattr(cv2.aruco, "DetectorParameters_create"):
            self.parameters = cv2.aruco.DetectorParameters_create()
        else:
            self.parameters = cv2.aruco.DetectorParameters()
        self.marker_size_m = float(self.get_parameter("marker_size_m").value)
        self.focal_length_px = float(self.get_parameter("focal_length_px").value)
        self.publish_empty = bool(self.get_parameter("publish_empty").value)
        self.min_marker_width_px = float(self.get_parameter("min_marker_width_px").value)
        self.process_rate_hz = float(self.get_parameter("process_rate_hz").value)
        if not math.isfinite(self.process_rate_hz) or self.process_rate_hz < 0.0:
            raise ValueError("process_rate_hz must be finite and greater than or equal to zero")
        self.enabled_on_start = bool(self.get_parameter("enabled_on_start").value)
        self.activation_file = str(self.get_parameter("activation_file").value).strip()

        self.camera_matrix = self._camera_matrix_from_param(self.get_parameter("camera_matrix").value)
        self.dist_coeffs = self._dist_coeffs_from_param(self.get_parameter("dist_coeffs").value)
        self.calibration_metadata: Dict[str, Any] = {}
        self._calibration_resolution_warning_logged = False
        calibration_file = str(self.get_parameter("calibration_file").value).strip()
        if calibration_file:
            try:
                self.camera_matrix, self.dist_coeffs, self.calibration_metadata = load_calibration(
                    calibration_file
                )
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid camera calibration file {calibration_file}: {exc}") from exc
            self.get_logger().info(
                f"loaded camera calibration {calibration_file} for "
                f"{self.calibration_metadata['image_width']}x{self.calibration_metadata['image_height']} "
                f"(RMS={self.calibration_metadata.get('rms_reprojection_error_px', 'unknown')}px)"
            )

        # Camera frames are sensor samples: no reliable backlog may turn an old frame
        # into a current docking observation.  Keep the bounded depth explicit.
        self.sensor_qos = QoSProfile(
            depth=5,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        self.publisher = self.create_publisher(String, self.detection_topic, self.sensor_qos)
        self.subscription = None
        self.enabled = False
        self.frames_seen = 0
        self.frame_sequence = 0
        self.detections_seen = 0
        self.last_processed_frame_monotonic = 0.0
        self.last_log_time = 0.0
        self.activation_timer = None
        self._sync_activation()
        if self.activation_file:
            self.activation_timer = self.create_timer(0.1, self._sync_activation)
        self.get_logger().info(
            f"ArUco detector publishing {self.detection_topic}, "
            f"dictionary={self.dictionary_name}, marker_size_m={self.marker_size_m}, "
            f"process_rate_hz={self.process_rate_hz:g}, request_scoped={bool(self.activation_file)}"
        )

    def _sync_activation(self):
        requested = activation_requested(
            self.activation_file, default=self.enabled_on_start
        )
        self._set_detector_enabled(requested)

    def _set_detector_enabled(self, enabled: bool):
        enabled = bool(enabled)
        if enabled == self.enabled:
            return
        self.enabled = enabled
        if enabled:
            self.last_processed_frame_monotonic = 0.0
            self.subscription = self.create_subscription(
                CompressedImage,
                self.image_topic,
                self._image_callback,
                self.sensor_qos,
            )
            self.get_logger().info(f"ArUco camera subscription enabled: {self.image_topic}")
            return
        if self.subscription is not None:
            self.destroy_subscription(self.subscription)
            self.subscription = None
        self.get_logger().info("ArUco camera subscription disabled")

    def _camera_matrix_from_param(self, value: Any) -> Optional[np.ndarray]:
        values = _as_float_list(value)
        if len(values) != 9:
            return None
        return np.array(values, dtype=np.float64).reshape((3, 3))

    def _dist_coeffs_from_param(self, value: Any) -> Optional[np.ndarray]:
        values = _as_float_list(value)
        if len(values) not in (4, 5, 8, 12, 14):
            return None
        return np.array(values, dtype=np.float64)

    def _detect_markers(self, gray):
        if hasattr(cv2.aruco, "ArucoDetector"):
            detector = cv2.aruco.ArucoDetector(self.dictionary, self.parameters)
            return detector.detectMarkers(gray)
        return cv2.aruco.detectMarkers(gray, self.dictionary, parameters=self.parameters)

    def _camera_matrix_for_image(self, width: int, height: int) -> Optional[np.ndarray]:
        if self.camera_matrix is None:
            return None
        calibrated_width = int(self.calibration_metadata.get("image_width") or 0)
        calibrated_height = int(self.calibration_metadata.get("image_height") or 0)
        if calibrated_width <= 0 or calibrated_height <= 0:
            return self.camera_matrix
        try:
            return scale_camera_matrix(
                self.camera_matrix,
                calibrated_width=calibrated_width,
                calibrated_height=calibrated_height,
                image_width=width,
                image_height=height,
            )
        except ValueError as exc:
            if not self._calibration_resolution_warning_logged:
                self.get_logger().error(str(exc))
                self._calibration_resolution_warning_logged = True
            return None

    def _estimate_pose(self, marker_width_px: float, corner, width: int, height: int) -> Dict[str, Any]:
        if marker_width_px <= 0:
            return {}
        camera_matrix = self._camera_matrix_for_image(width, height)
        if camera_matrix is not None and self.dist_coeffs is not None:
            try:
                return estimate_marker_pose(
                    corner.reshape((4, 2)),
                    marker_size_m=self.marker_size_m,
                    camera_matrix=camera_matrix,
                    dist_coeffs=self.dist_coeffs,
                )
            except Exception as exc:
                self.get_logger().debug(f"pose estimate failed: {exc}")
        if self.focal_length_px > 0 and self.marker_size_m > 0:
            distance = float(self.marker_size_m * self.focal_length_px / marker_width_px)
            return {"estimated_distance_m": distance, "forward_distance_m": distance}
        return {}

    def _image_callback(self, msg: CompressedImage):
        if not self.enabled:
            return
        receipt_monotonic = time.monotonic()
        if not processing_due(
            self.last_processed_frame_monotonic,
            receipt_monotonic,
            self.process_rate_hz,
        ):
            return
        self.last_processed_frame_monotonic = receipt_monotonic
        self.frames_seen += 1
        self.frame_sequence += 1
        receipt_wall = time.time()
        np_arr = np.frombuffer(msg.data, dtype=np.uint8)
        frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
        if frame is None:
            self.get_logger().warning("failed to decode compressed image")
            return
        height, width = frame.shape[:2]
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, _ = self._detect_markers(gray)

        detections: List[Dict[str, Any]] = []
        if ids is not None:
            for marker_id, corner in zip(ids.flatten().tolist(), corners):
                pts = corner.reshape((4, 2)).astype(float)
                side_lengths = [
                    float(np.linalg.norm(pts[(i + 1) % 4] - pts[i]))
                    for i in range(4)
                ]
                marker_width_px = float((side_lengths[0] + side_lengths[2]) / 2.0)
                marker_height_px = float((side_lengths[1] + side_lengths[3]) / 2.0)
                if marker_width_px < self.min_marker_width_px:
                    continue
                center_x = float(np.mean(pts[:, 0]))
                center_y = float(np.mean(pts[:, 1]))
                error_px = center_x - (width / 2.0)
                error_norm = error_px / max(1.0, width / 2.0)
                marker_pose = self._estimate_pose(marker_width_px, corner, width, height)
                detection = {
                    "marker_id": int(marker_id),
                    "center_px": [center_x, center_y],
                    "center_error_px": float(error_px),
                    "center_error_norm": float(error_norm),
                    "marker_width_px": marker_width_px,
                    "marker_height_px": marker_height_px,
                    "area_px": float(cv2.contourArea(pts.astype(np.float32))),
                    "image_width": int(width),
                    "image_height": int(height),
                    "corners_px": pts.tolist(),
                }
                for key, value in marker_pose.items():
                    if isinstance(value, float) and not math.isfinite(value):
                        continue
                    detection[key] = value
                detections.append(detection)

        if detections or self.publish_empty:
            payload = {
                "source_header_stamp": {"sec": int(msg.header.stamp.sec), "nanosec": int(msg.header.stamp.nanosec)},
                "stamp": {"sec": int(msg.header.stamp.sec), "nanosec": int(msg.header.stamp.nanosec)},
                "source_receipt_monotonic": receipt_monotonic,
                "received_at": receipt_wall,
                "frame_sequence": self.frame_sequence,
                "frame_id": msg.header.frame_id,
                "image_topic": self.image_topic,
                "dictionary": self.dictionary_name,
                "marker_size_m": self.marker_size_m,
                "detections": detections,
            }
            out = String()
            out.data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            self.publisher.publish(out)

        if detections:
            self.detections_seen += len(detections)
        now = time.monotonic()
        if now - self.last_log_time >= 5.0:
            self.get_logger().info(
                f"frames={self.frames_seen}, detections={self.detections_seen}, last_count={len(detections)}"
            )
            self.last_log_time = now


def main():
    rclpy.init()
    node = ArucoDetectorNode()
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
