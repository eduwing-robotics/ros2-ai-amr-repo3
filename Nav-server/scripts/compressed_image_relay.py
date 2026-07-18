#!/usr/bin/env python3
"""Relay a CompressedImage topic to another CompressedImage topic."""

import os

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import CompressedImage


class CompressedImageRelay(Node):
    def __init__(self):
        super().__init__('compressed_image_relay')
        self.input_topic = self.declare_parameter(
            'input_topic', os.getenv('RELAY_INPUT_TOPIC', '/camera/image_raw/compressed')
        ).value
        self.output_topic = self.declare_parameter(
            'output_topic', os.getenv('RELAY_OUTPUT_TOPIC', '/mission/tb3_1/camera/compressed')
        ).value
        self.publisher = self.create_publisher(CompressedImage, self.output_topic, qos_profile_sensor_data)
        self.subscription = self.create_subscription(CompressedImage, self.input_topic, self._callback, qos_profile_sensor_data)
        self.frames = 0
        self.get_logger().info(f'relaying compressed images: {self.input_topic} -> {self.output_topic}')

    def _callback(self, msg):
        self.publisher.publish(msg)
        self.frames += 1
        if self.frames == 1 or self.frames % 100 == 0:
            self.get_logger().info(f'relayed_frames={self.frames}')


def main():
    rclpy.init()
    node = CompressedImageRelay()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
