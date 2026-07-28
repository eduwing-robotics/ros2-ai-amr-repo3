#!/usr/bin/env python3
"""Drive collision_monitor's upstream velocity input and prove a contact-free STOP."""

from __future__ import annotations

import argparse
import json
import math
import time
from pathlib import Path

import rclpy
from geometry_msgs.msg import TwistStamped
from nav2_msgs.msg import CollisionMonitorState
from nav_msgs.msg import Odometry
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import LaserScan


class CollisionProbe(Node):
    def __init__(self, speed_mps: float):
        super().__init__("dual_robot_collision_stop_probe")
        self.speed_mps = speed_mps
        self.start_xy = None
        self.current_xy = None
        self.front_clearance_m = None
        self.stop_polygon = None
        self.smoothed_samples = 0
        self.output_samples = 0
        self.max_smoothed_linear_mps = 0.0
        self.max_output_linear_mps = 0.0
        self.publisher = self.create_publisher(TwistStamped, "/cmd_vel_nav", 10)
        self.create_subscription(Odometry, "/odom", self._odom, qos_profile_sensor_data)
        self.create_subscription(LaserScan, "/scan", self._scan, qos_profile_sensor_data)
        self.create_subscription(CollisionMonitorState, "/collision_monitor_state", self._state, 10)
        self.create_subscription(TwistStamped, "/cmd_vel_smoothed", self._smoothed, 10)
        self.create_subscription(TwistStamped, "/cmd_vel", self._output, 10)

    def _odom(self, msg: Odometry) -> None:
        xy = (float(msg.pose.pose.position.x), float(msg.pose.pose.position.y))
        if self.start_xy is None:
            self.start_xy = xy
        self.current_xy = xy

    def _scan(self, msg: LaserScan) -> None:
        candidates = []
        angle = float(msg.angle_min)
        for value in msg.ranges:
            normalized = math.atan2(math.sin(angle), math.cos(angle))
            if abs(normalized) <= math.radians(20.0) and math.isfinite(value):
                candidates.append(float(value))
            angle += float(msg.angle_increment)
        if candidates:
            self.front_clearance_m = min(candidates)

    def _state(self, msg: CollisionMonitorState) -> None:
        if int(msg.action_type) == int(CollisionMonitorState.STOP):
            self.stop_polygon = str(msg.polygon_name)

    def _smoothed(self, msg: TwistStamped) -> None:
        self.smoothed_samples += 1
        self.max_smoothed_linear_mps = max(
            self.max_smoothed_linear_mps, abs(float(msg.twist.linear.x))
        )

    def _output(self, msg: TwistStamped) -> None:
        self.output_samples += 1
        self.max_output_linear_mps = max(
            self.max_output_linear_mps, abs(float(msg.twist.linear.x))
        )

    def publish(self, linear_x: float) -> None:
        msg = TwistStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = "base_link"
        msg.twist.linear.x = float(linear_x)
        self.publisher.publish(msg)

    def displacement(self) -> float:
        if self.start_xy is None or self.current_xy is None:
            return 0.0
        return math.hypot(
            self.current_xy[0] - self.start_xy[0],
            self.current_xy[1] - self.start_xy[1],
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--speed-mps", type=float, default=0.08)
    parser.add_argument("--timeout-sec", type=float, default=12.0)
    parser.add_argument("--minimum-clearance-m", type=float, default=0.14)
    parser.add_argument("--maximum-displacement-m", type=float, default=0.45)
    parser.add_argument("--evidence", type=Path)
    args, ros_args = parser.parse_known_args()

    rclpy.init(args=ros_args)
    node = CollisionProbe(abs(args.speed_mps))
    startup_deadline = time.monotonic() + 8.0
    while rclpy.ok() and time.monotonic() < startup_deadline and (
        node.start_xy is None or node.front_clearance_m is None
    ):
        rclpy.spin_once(node, timeout_sec=0.1)
    discovery_deadline = time.monotonic() + 3.0
    while rclpy.ok() and time.monotonic() < discovery_deadline and node.publisher.get_subscription_count() < 1:
        rclpy.spin_once(node, timeout_sec=0.05)
    started = bool(
        node.start_xy is not None
        and node.front_clearance_m is not None
        and node.publisher.get_subscription_count() >= 1
    )

    deadline = time.monotonic() + max(0.1, args.timeout_sec)
    while started and rclpy.ok() and time.monotonic() < deadline and node.stop_polygon is None:
        node.publish(abs(args.speed_mps))
        rclpy.spin_once(node, timeout_sec=0.05)

    for _ in range(12):
        node.publish(0.0)
        rclpy.spin_once(node, timeout_sec=0.05)

    displacement_m = node.displacement()
    velocity_gate_stop = bool(
        node.max_smoothed_linear_mps >= 0.02
        and node.max_output_linear_mps <= 0.005
        and displacement_m <= 0.03
    )
    state_topic_stop = node.stop_polygon is not None
    evidence = {
        "scenario": "collision_monitor_contact_free_stop",
        "input_topic": "/cmd_vel_nav",
        "smoothed_topic": "/cmd_vel_smoothed",
        "output_topic": "/cmd_vel",
        "started": started,
        "stop_observed": state_topic_stop or velocity_gate_stop,
        "stop_evidence_source": "state_topic" if state_topic_stop else ("velocity_gate" if velocity_gate_stop else None),
        "stop_polygon": node.stop_polygon,
        "smoothed_samples": node.smoothed_samples,
        "output_samples": node.output_samples,
        "max_smoothed_linear_mps": node.max_smoothed_linear_mps,
        "max_output_linear_mps": node.max_output_linear_mps,
        "front_clearance_m": node.front_clearance_m,
        "displacement_m": displacement_m,
        "minimum_clearance_m": args.minimum_clearance_m,
        "maximum_displacement_m": args.maximum_displacement_m,
    }
    evidence["passed"] = bool(
        started
        and evidence["stop_observed"]
        and evidence["front_clearance_m"] is not None
        and float(evidence["front_clearance_m"]) >= args.minimum_clearance_m
        and float(evidence["displacement_m"]) <= args.maximum_displacement_m
    )
    if args.evidence:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        args.evidence.write_text(json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    node.destroy_node()
    rclpy.shutdown()
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
