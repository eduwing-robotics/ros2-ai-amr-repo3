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
        self.declare_parameter("marker_size_m", float(os.getenv("ARUCO_MARKER_SIZE_M", "0.05")))
        self.declare_parameter("focal_length_px", float(os.getenv("ARUCO_FOCAL_LENGTH_PX", "0")))
        self.declare_parameter("camera_matrix", os.getenv("ARUCO_CAMERA_MATRIX", ""))
        self.declare_parameter("dist_coeffs", os.getenv("ARUCO_DIST_COEFFS", ""))
        self.declare_parameter("publish_empty", os.getenv("ARUCO_PUBLISH_EMPTY", "1") not in ("0", "false", "False"))
        self.declare_parameter("min_marker_width_px", float(os.getenv("ARUCO_MIN_MARKER_WIDTH_PX", "8")))

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

        self.camera_matrix = self._camera_matrix_from_param(self.get_parameter("camera_matrix").value)
        self.dist_coeffs = self._dist_coeffs_from_param(self.get_parameter("dist_coeffs").value)

        # Camera frames are sensor samples: no reliable backlog may turn an old frame
        # into a current docking observation.  Keep the bounded depth explicit.
        self.sensor_qos = QoSProfile(
            depth=5,
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
        )
        self.publisher = self.create_publisher(String, self.detection_topic, self.sensor_qos)
        self.subscription = self.create_subscription(
            CompressedImage, self.image_topic, self._image_callback, self.sensor_qos
        )
        self.frames_seen = 0
        self.frame_sequence = 0
        self.detections_seen = 0
        self.last_log_time = 0.0
        self.get_logger().info(
            f"ArUco detector subscribed to {self.image_topic}, publishing {self.detection_topic}, "
            f"dictionary={self.dictionary_name}, marker_size_m={self.marker_size_m}"
        )

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

    def _estimate_distance(self, marker_width_px: float, corner) -> Optional[float]:
        if marker_width_px <= 0:
            return None
        if self.camera_matrix is not None and self.dist_coeffs is not None and hasattr(cv2.aruco, "estimatePoseSingleMarkers"):
            try:
                _, tvecs, _ = cv2.aruco.estimatePoseSingleMarkers(
                    np.array([corner], dtype=np.float32),
                    self.marker_size_m,
                    self.camera_matrix,
                    self.dist_coeffs,
                )
                tvec = tvecs[0][0]
                return float(np.linalg.norm(tvec))
            except Exception as exc:
                self.get_logger().debug(f"pose estimate failed: {exc}")
        if self.focal_length_px > 0 and self.marker_size_m > 0:
            return float(self.marker_size_m * self.focal_length_px / marker_width_px)
        return None

    def _image_callback(self, msg: CompressedImage):
        self.frames_seen += 1
        self.frame_sequence += 1
        receipt_monotonic = time.monotonic()
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
                estimated_distance = self._estimate_distance(marker_width_px, corner)
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
                if estimated_distance is not None and math.isfinite(estimated_distance):
                    detection["estimated_distance_m"] = estimated_distance
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
