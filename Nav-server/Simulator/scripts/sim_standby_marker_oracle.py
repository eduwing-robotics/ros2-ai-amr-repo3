#!/usr/bin/env python3
# Publish deterministic virtual standby-marker distance from simulated odometry.

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from pathlib import Path

import rclpy
from nav_msgs.msg import Odometry
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from std_msgs.msg import String

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))
from dual_robot_geometry import DEFAULT_CONFIG, load_layout, marker_distance_from_progress


def _yaw(q) -> float:
    return math.atan2(2.0 * (q.w * q.z + q.x * q.y), 1.0 - 2.0 * (q.y * q.y + q.z * q.z))


class StandbyMarkerOracle(Node):
    def __init__(self, robot: dict, hold_distance_m: float, rate_hz: float):
        super().__init__("{}_standby_marker_oracle".format(robot["name"]))
        self.robot = robot
        self.hold_distance_m = float(hold_distance_m)
        self.reverse_progress_m = 0.0
        self.max_abs_angular_z_rps = 0.0
        self.last_pose = None
        self.publisher = self.create_publisher(String, "/mission/{}/aruco/detections".format(robot["name"]), 10)
        self.subscription = self.create_subscription(Odometry, "/odom", self._on_odom, 20)
        self.timer = self.create_timer(1.0 / max(1.0, rate_hz), self._publish)

    def _on_odom(self, msg: Odometry) -> None:
        pose = msg.pose.pose
        current = (float(pose.position.x), float(pose.position.y), _yaw(pose.orientation))
        if self.last_pose is not None:
            dx = current[0] - self.last_pose[0]
            dy = current[1] - self.last_pose[1]
            heading = self.last_pose[2]
            signed_forward = dx * math.cos(heading) + dy * math.sin(heading)
            self.reverse_progress_m = max(-self.hold_distance_m, self.reverse_progress_m - signed_forward)
            if self.reverse_progress_m > 0.001:
                self.max_abs_angular_z_rps = max(
                    self.max_abs_angular_z_rps,
                    abs(float(msg.twist.twist.angular.z)),
                )
        self.last_pose = current

    def _publish(self) -> None:
        if self.last_pose is None:
            return
        distance = marker_distance_from_progress(self.hold_distance_m, self.reverse_progress_m)
        marker_width = 65.0 * 0.40 / max(0.05, distance)
        detection = {
            "marker_id": int(self.robot["marker_id"]),
            "estimated_distance_m": round(distance, 6),
            "marker_width_px": round(marker_width, 2),
            "center_norm": [0.0, 0.0],
            "max_abs_angular_z_rps": round(self.max_abs_angular_z_rps, 6),
            "source": "gazebo_odometry_oracle",
        }
        payload = {
            "received_at": time.time(),
            "robot_name": self.robot["name"],
            "simulation": True,
            "detections": [detection],
        }
        msg = String()
        msg.data = json.dumps(payload, separators=(",", ":"))
        self.publisher.publish(msg)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--robot", required=True, choices=("tb3_1", "tb3_2"))
    parser.add_argument("--rate-hz", type=float, default=20.0)
    args = parser.parse_args()
    layout = load_layout(args.config)
    robot = next(item for item in layout["robots"] if item["name"] == args.robot)
    rclpy.init()
    node = StandbyMarkerOracle(robot, layout["hold_marker_distance_m"], args.rate_hz)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
