#!/usr/bin/env python3
"""Pi CSI imx219 → /camera/image_raw/compressed (picamera2, marco libcamera).

ros-jazzy-libcamera IPA ControlInfoMap 크래시 우회용. 로봇 SBC에서만 실행.
"""
from __future__ import annotations

import os

import cv2
import rclpy
from picamera2 import Picamera2
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import CompressedImage


class Picamera2CompressedPublisher(Node):
    def __init__(self) -> None:
        super().__init__('camera')
        self.declare_parameter('width', 320)
        self.declare_parameter('height', 240)
        self.declare_parameter('jpeg_quality', 80)
        self.declare_parameter('frame_id', 'camera_link')
        self.declare_parameter('topic', '/camera/image_raw/compressed')

        width = int(self.get_parameter('width').value)
        height = int(self.get_parameter('height').value)
        quality = int(self.get_parameter('jpeg_quality').value)
        frame_id = str(self.get_parameter('frame_id').value)
        topic = str(self.get_parameter('topic').value)
        self._frame_id = frame_id
        self._quality = quality

        qos = QoSProfile(
            reliability=ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=5,
            durability=DurabilityPolicy.VOLATILE,
        )
        self._pub = self.create_publisher(CompressedImage, topic, qos)

        self._picam = Picamera2()
        cfg = self._picam.create_video_configuration(
            main={'size': (width, height), 'format': 'RGB888'},
        )
        self._picam.configure(cfg)
        self._picam.start()
        period = float(os.environ.get('CAMERA_PUBLISH_PERIOD_SEC', '0.1'))
        self._timer = self.create_timer(period, self._publish)
        self.get_logger().info(
            f'picamera2 publisher {width}x{height} → {topic} (q={quality})'
        )

    def _publish(self) -> None:
        try:
            frame = self._picam.capture_array('main')
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warning(f'capture failed: {exc}')
            return
        ok, encoded = cv2.imencode(
            '.jpg', frame,
            [int(cv2.IMWRITE_JPEG_QUALITY), self._quality],
        )
        if not ok:
            self.get_logger().warning('jpeg encode failed')
            return
        msg = CompressedImage()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = self._frame_id
        msg.format = 'jpeg'
        msg.data = encoded.tobytes()
        self._pub.publish(msg)

    def destroy_node(self) -> bool:
        try:
            self._picam.stop()
            self._picam.close()
        except Exception:  # noqa: BLE001
            pass
        return super().destroy_node()


def main() -> None:
    rclpy.init()
    node = Picamera2CompressedPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
