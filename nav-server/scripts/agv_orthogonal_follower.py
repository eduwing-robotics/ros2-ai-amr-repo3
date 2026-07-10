#!/usr/bin/env python3
"""ROS 2 AGV follower that executes only cardinal rotate/drive segments."""

from __future__ import annotations

from dataclasses import dataclass
import math
import os
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from agv_graph_builder import CorridorGraph, graph_allowed_cells, load_corridor_graph, validate_graph
from agv_grid_planner import (
    GridMap,
    MotionSegment,
    astar_4,
    cells_to_motion_segments,
    inflated_blocked_cells,
    inflation_cells,
)

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Point, Twist, TwistStamped
from nav_msgs.msg import OccupancyGrid, Odometry
from std_msgs.msg import String
from visualization_msgs.msg import Marker, MarkerArray

try:
    import tf2_ros
except ImportError:  # pragma: no cover - ROS environment dependency
    tf2_ros = None


NAV_SERVER_ROOT = Path(os.environ.get("NAV_SERVER_ROOT", Path(__file__).resolve().parents[1])).resolve()
DEFAULT_GRAPH_PATH = NAV_SERVER_ROOT / "map" / "agv_waypoint_graph.yaml"


def resolve_repo_path(path_value: str) -> Path:
    path = Path(os.path.expandvars(os.path.expanduser(str(path_value))))
    if path.is_absolute():
        return path
    return (NAV_SERVER_ROOT / path).resolve()


@dataclass
class Pose2D:
    x: float
    y: float
    yaw: float


class AgvOrthogonalFollower(Node):
    def __init__(self):
        super().__init__("agv_orthogonal_follower")

        self.declare_parameter("graph_path", os.environ.get("AGV_GRAPH_PATH", str(DEFAULT_GRAPH_PATH)))
        self.declare_parameter("robot_radius", 0.11)
        self.declare_parameter("lift_width", 0.34)
        self.declare_parameter("safety_margin", 0.08)
        self.declare_parameter("occupied_threshold", 50)
        self.declare_parameter("unknown_is_blocked", True)
        self.declare_parameter("cmd_vel_stamped", True)
        self.declare_parameter("linear_speed", 0.055)
        self.declare_parameter("angular_speed", 0.28)
        self.declare_parameter("linear_tolerance", 0.035)
        self.declare_parameter("yaw_tolerance", 0.055)
        self.declare_parameter("corner_stop_sec", 0.35)
        self.declare_parameter("control_rate_hz", 20.0)
        self.declare_parameter("base_frame", "base_link")

        self.graph_path = resolve_repo_path(self.get_parameter("graph_path").value)
        self.graph: CorridorGraph = load_corridor_graph(self.graph_path)
        self.grid: Optional[GridMap] = None
        self.blocked = set()
        self.allowed = set()
        self.odom_pose: Optional[Pose2D] = None
        self.segments: List[MotionSegment] = []
        self.segment_index = 0
        self.state = "IDLE"
        self.status = "IDLE"
        self.stop_until_time = None
        self.current_goal_name: Optional[str] = None
        self.cmd_vel_stamped = bool(self.get_parameter("cmd_vel_stamped").value)

        self.map_sub = self.create_subscription(OccupancyGrid, "/map", self._on_map, 1)
        self.odom_sub = self.create_subscription(Odometry, "/odom", self._on_odom, 20)
        self.goal_sub = self.create_subscription(String, "/lms_goal", self._on_goal, 10)
        self.marker_pub = self.create_publisher(MarkerArray, "/agv_path_markers", 1)
        self.status_pub = self.create_publisher(String, "/agv_follower/status", 10)
        if self.cmd_vel_stamped:
            self.cmd_pub = self.create_publisher(TwistStamped, "/cmd_vel", 10)
        else:
            self.cmd_pub = self.create_publisher(Twist, "/cmd_vel", 10)

        self.tf_buffer = None
        self.tf_listener = None
        if tf2_ros is not None:
            self.tf_buffer = tf2_ros.Buffer()
            self.tf_listener = tf2_ros.TransformListener(self.tf_buffer, self)

        rate = float(self.get_parameter("control_rate_hz").value)
        self.timer = self.create_timer(1.0 / rate, self._control_tick)
        self.get_logger().info(f"AGV orthogonal follower ready. graph={self.graph_path}")

    def _on_map(self, msg: OccupancyGrid) -> None:
        self.grid = GridMap(
            width=msg.info.width,
            height=msg.info.height,
            resolution=msg.info.resolution,
            origin_x=msg.info.origin.position.x,
            origin_y=msg.info.origin.position.y,
            data=list(msg.data),
            occupied_threshold=int(self.get_parameter("occupied_threshold").value),
            unknown_is_blocked=bool(self.get_parameter("unknown_is_blocked").value),
        )
        radius_cells = inflation_cells(
            self.grid,
            float(self.get_parameter("robot_radius").value),
            float(self.get_parameter("lift_width").value),
            float(self.get_parameter("safety_margin").value),
        )
        self.blocked = inflated_blocked_cells(self.grid, radius_cells)
        self.allowed = graph_allowed_cells(self.graph, self.grid)
        errors = validate_graph(self.graph, self.grid, self.blocked)
        if errors:
            self.get_logger().warning("AGV graph validation warnings: " + "; ".join(errors[:5]))
        self._publish_markers([])

    def _on_odom(self, msg: Odometry) -> None:
        pose = msg.pose.pose
        self.odom_pose = Pose2D(
            x=pose.position.x,
            y=pose.position.y,
            yaw=yaw_from_quaternion(pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w),
        )

    def _on_goal(self, msg: String) -> None:
        goal_name = msg.data.strip()
        if not goal_name:
            return
        if self.grid is None:
            self._fail("map is not ready")
            return
        if goal_name not in self.graph.nodes:
            self._fail(f"unknown AGV waypoint: {goal_name}")
            return
        current = self._current_map_pose()
        if current is None:
            self._fail("current map pose is not available")
            return

        start_cell = nearest_allowed_cell(self.grid.world_to_cell(current.x, current.y), self.allowed)
        goal_node = self.graph.nodes[goal_name]
        goal_cell = nearest_allowed_cell(self.grid.world_to_cell(goal_node.x, goal_node.y), self.allowed)
        try:
            path = astar_4(self.grid, start_cell, goal_cell, blocked=self.blocked, allowed_cells=self.allowed)
        except ValueError as exc:
            self._fail(str(exc))
            return

        self.segments = cells_to_motion_segments(path, self.grid)
        self.segment_index = 0
        self.state = "ROTATE" if self.segments else "ARRIVED"
        self.current_goal_name = goal_name
        self.status = f"RUNNING:{goal_name}"
        self._publish_status()
        self._publish_markers(path)
        self.get_logger().info(f"planned AGV path to {goal_name}: cells={len(path)}, segments={len(self.segments)}")

    def _control_tick(self) -> None:
        if self.state in ("IDLE", "ARRIVED", "FAILED"):
            return
        if self.segment_index >= len(self.segments):
            self._arrive()
            return
        pose = self._current_map_pose()
        if pose is None:
            self._stop()
            self._fail("current map pose lost")
            return

        segment = self.segments[self.segment_index]
        if segment.kind == "rotate":
            self._run_rotate(segment, pose)
        elif segment.kind == "drive":
            self._run_drive(segment, pose)
        elif segment.kind == "stop":
            self._run_stop(segment)
        else:
            self._fail(f"unknown segment kind: {segment.kind}")

    def _run_rotate(self, segment: MotionSegment, pose: Pose2D) -> None:
        target_yaw = math.radians(segment.heading_deg)
        error = normalize_angle(target_yaw - pose.yaw)
        if abs(error) <= float(self.get_parameter("yaw_tolerance").value):
            self._stop()
            self.segment_index += 1
            return
        speed = min(float(self.get_parameter("angular_speed").value), max(0.08, abs(error)))
        self._publish_cmd(0.0, math.copysign(speed, error))

    def _run_drive(self, segment: MotionSegment, pose: Pose2D) -> None:
        dx = segment.x - pose.x
        dy = segment.y - pose.y
        heading = math.radians(segment.heading_deg)
        along = math.cos(heading) * dx + math.sin(heading) * dy
        yaw_error = normalize_angle(heading - pose.yaw)
        if abs(along) <= float(self.get_parameter("linear_tolerance").value):
            self._stop()
            self.segment_index += 1
            return
        linear = min(float(self.get_parameter("linear_speed").value), max(0.018, abs(along) * 0.6))
        angular = max(-0.18, min(0.18, yaw_error * 1.8))
        self._publish_cmd(math.copysign(linear, along), angular)

    def _run_stop(self, segment: MotionSegment) -> None:
        now = self.get_clock().now()
        if self.stop_until_time is None:
            self._stop()
            self.stop_until_time = now + rclpy.duration.Duration(seconds=float(self.get_parameter("corner_stop_sec").value))
            return
        self._stop()
        if now >= self.stop_until_time:
            self.stop_until_time = None
            self.segment_index += 1

    def _current_map_pose(self) -> Optional[Pose2D]:
        if self.tf_buffer is not None:
            try:
                transform = self.tf_buffer.lookup_transform(
                    "map",
                    str(self.get_parameter("base_frame").value),
                    rclpy.time.Time(),
                    timeout=rclpy.duration.Duration(seconds=0.05),
                )
                tr = transform.transform.translation
                rot = transform.transform.rotation
                return Pose2D(tr.x, tr.y, yaw_from_quaternion(rot.x, rot.y, rot.z, rot.w))
            except Exception:
                pass
        return self.odom_pose

    def _publish_cmd(self, linear_x: float, angular_z: float) -> None:
        if self.cmd_vel_stamped:
            msg = TwistStamped()
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.header.frame_id = str(self.get_parameter("base_frame").value)
            msg.twist.linear.x = float(linear_x)
            msg.twist.angular.z = float(angular_z)
        else:
            msg = Twist()
            msg.linear.x = float(linear_x)
            msg.angular.z = float(angular_z)
        self.cmd_pub.publish(msg)

    def _stop(self) -> None:
        self._publish_cmd(0.0, 0.0)

    def _arrive(self) -> None:
        self._stop()
        self.state = "ARRIVED"
        self.status = f"ARRIVED:{self.current_goal_name or ''}"
        self._publish_status()
        self.get_logger().info(self.status)

    def _fail(self, reason: str) -> None:
        self._stop()
        self.state = "FAILED"
        self.status = f"FAILED:{reason}"
        self._publish_status()
        self.get_logger().error(self.status)

    def _publish_status(self) -> None:
        msg = String()
        msg.data = self.status
        self.status_pub.publish(msg)

    def _publish_markers(self, path: Sequence[Tuple[int, int]]) -> None:
        if self.grid is None:
            return
        markers = MarkerArray()
        stamp = self.get_clock().now().to_msg()

        graph_marker = Marker()
        graph_marker.header.frame_id = self.graph.frame_id
        graph_marker.header.stamp = stamp
        graph_marker.ns = "agv_graph_edges"
        graph_marker.id = 1
        graph_marker.type = Marker.LINE_LIST
        graph_marker.action = Marker.ADD
        graph_marker.scale.x = 0.01
        graph_marker.color.r = 0.1
        graph_marker.color.g = 0.7
        graph_marker.color.b = 1.0
        graph_marker.color.a = 0.75
        for start_name, end_name in self.graph.edges:
            for name in (start_name, end_name):
                node = self.graph.nodes[name]
                graph_marker.points.append(Point(x=node.x, y=node.y, z=0.03))
        markers.markers.append(graph_marker)

        path_marker = Marker()
        path_marker.header.frame_id = self.graph.frame_id
        path_marker.header.stamp = stamp
        path_marker.ns = "agv_path"
        path_marker.id = 2
        path_marker.type = Marker.LINE_STRIP
        path_marker.action = Marker.ADD
        path_marker.scale.x = 0.025
        path_marker.color.r = 0.0
        path_marker.color.g = 1.0
        path_marker.color.b = 0.15
        path_marker.color.a = 1.0
        for cell in path:
            x, y = self.grid.cell_to_world(cell)
            path_marker.points.append(Point(x=x, y=y, z=0.06))
        markers.markers.append(path_marker)

        self.marker_pub.publish(markers)


def nearest_allowed_cell(cell: Tuple[int, int], allowed: set[Tuple[int, int]]) -> Tuple[int, int]:
    if cell in allowed:
        return cell
    if not allowed:
        raise ValueError("allowed corridor graph is empty")
    return min(allowed, key=lambda candidate: abs(candidate[0] - cell[0]) + abs(candidate[1] - cell[1]))


def yaw_from_quaternion(x: float, y: float, z: float, w: float) -> float:
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def normalize_angle(angle: float) -> float:
    while angle > math.pi:
        angle -= 2.0 * math.pi
    while angle < -math.pi:
        angle += 2.0 * math.pi
    return angle


def main() -> None:
    rclpy.init()
    node = AgvOrthogonalFollower()
    try:
        rclpy.spin(node)
    finally:
        node._stop()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
