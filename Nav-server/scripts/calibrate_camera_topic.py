#!/usr/bin/env python3
"""Collect ChArUco views from a ROS compressed-image topic and calibrate."""
from __future__ import annotations
import argparse
import time
import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from camera_calibration import save_calibration

DICTIONARIES = {
    "DICT_4X4_50": cv2.aruco.DICT_4X4_50,
    "DICT_5X5_100": cv2.aruco.DICT_5X5_100,
}

def make_board(args):
    dictionary = cv2.aruco.getPredefinedDictionary(DICTIONARIES[args.dictionary])
    if hasattr(cv2.aruco, "CharucoBoard_create"):
        board = cv2.aruco.CharucoBoard_create(args.squares_x, args.squares_y, args.square_size_m, args.marker_size_m, dictionary)
    else:
        board = cv2.aruco.CharucoBoard((args.squares_x, args.squares_y), args.square_size_m, args.marker_size_m, dictionary)
    return dictionary, board

class Collector(Node):
    def __init__(self, args):
        super().__init__("camera_calibration_collector")
        self.args = args
        self.dictionary, self.board = make_board(args)
        self.corners, self.ids = [], []
        self.size, self.last, self.finished = None, 0.0, False
        self.create_subscription(CompressedImage, args.topic, self.on_image, 10)
        self.get_logger().info(
            f"collecting {args.samples} ChArUco views ({args.squares_x}x{args.squares_y}, "
            f"square={args.square_size_m}m marker={args.marker_size_m}m, {args.dictionary}) from {args.topic}"
        )

    def on_image(self, msg):
        if self.finished or time.monotonic() - self.last < self.args.interval_sec:
            return
        frame = cv2.imdecode(np.frombuffer(msg.data, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            return
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        marker_corners, marker_ids, _ = cv2.aruco.detectMarkers(gray, self.dictionary)
        if marker_ids is None or len(marker_ids) < 2:
            return
        count, charuco_corners, charuco_ids = cv2.aruco.interpolateCornersCharuco(
            marker_corners, marker_ids, gray, self.board
        )
        if charuco_ids is None or count < self.args.min_corners:
            return
        self.corners.append(charuco_corners)
        self.ids.append(charuco_ids)
        self.size, self.last = (gray.shape[1], gray.shape[0]), time.monotonic()
        self.get_logger().info(
            f"accepted view {len(self.corners)}/{self.args.samples} ({int(count)} corners); move/tilt board"
        )
        if len(self.corners) >= self.args.samples:
            self.finish()

    def finish(self):
        calibration_flags = cv2.CALIB_ZERO_TANGENT_DIST | cv2.CALIB_FIX_K3
        result = cv2.aruco.calibrateCameraCharucoExtended(
            self.corners, self.ids, self.board, self.size, None, None,
            flags=calibration_flags,
        )
        rms, matrix, distortion = result[:3]
        per_view = np.asarray(result[-1], dtype=float).reshape(-1) if len(result) >= 8 else np.array([])
        output = {
            "format_version": 1,
            "calibration_type": "charuco",
            "image_width": self.size[0], "image_height": self.size[1],
            "camera_matrix": matrix.tolist(), "dist_coeffs": distortion.reshape(-1).tolist(),
            "rms_reprojection_error_px": float(rms),
            "mean_reprojection_error_px": float(np.mean(per_view)) if per_view.size else float(rms),
            "max_view_reprojection_error_px": float(np.max(per_view)) if per_view.size else float(rms),
            "sample_count": len(self.corners),
            "squares_x": self.args.squares_x, "squares_y": self.args.squares_y,
            "square_size_m": self.args.square_size_m, "marker_size_m": self.args.marker_size_m,
            "dictionary": self.args.dictionary, "source_topic": self.args.topic,
            "calibration_flags": ["ZERO_TANGENT_DIST", "FIX_K3"],
        }
        save_calibration(self.args.output, output)
        self.get_logger().info(
            f"saved {self.args.output}; RMS={output['rms_reprojection_error_px']:.3f}px, "
            f"mean={output['mean_reprojection_error_px']:.3f}px"
        )
        self.finished = True

def parse_args():
    p = argparse.ArgumentParser(description="Calibrate from an OpenCV ChArUco board")
    p.add_argument("--topic", default="/camera/image_raw/compressed")
    p.add_argument("--output", required=True)
    p.add_argument("--squares-x", type=int, default=5)
    p.add_argument("--squares-y", type=int, default=7)
    p.add_argument("--square-size-m", type=float, default=0.025)
    p.add_argument("--marker-size-m", type=float, default=0.0125)
    p.add_argument("--dictionary", choices=sorted(DICTIONARIES), default="DICT_5X5_100")
    p.add_argument("--samples", type=int, default=25)
    p.add_argument("--min-corners", type=int, default=12)
    p.add_argument("--interval-sec", type=float, default=0.8)
    a = p.parse_args()
    if min(a.squares_x, a.squares_y) < 3 or not 0 < a.marker_size_m < a.square_size_m or a.samples < 10:
        p.error("board >=3x3, 0 < marker < square, and samples >=10 required")
    return a

def main():
    args = parse_args(); rclpy.init(); node = Collector(args)
    try:
        while rclpy.ok() and not node.finished:
            rclpy.spin_once(node, timeout_sec=.5)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok(): rclpy.shutdown()
if __name__ == "__main__": main()
