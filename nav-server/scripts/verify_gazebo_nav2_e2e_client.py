#!/usr/bin/env python3
"""ROS client for the headless Gazebo Nav2 acceptance launcher."""

from __future__ import annotations

import argparse
import json
import math
import sys
import time
from dataclasses import dataclass

import rclpy
from action_msgs.msg import GoalStatus
from geometry_msgs.msg import PoseStamped, PoseWithCovarianceStamped
from nav2_msgs.action import NavigateToPose
from rclpy.action import ActionClient
from rclpy.duration import Duration
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.time import Time
from std_srvs.srv import Trigger
from tf2_ros import Buffer, TransformException, TransformListener


# These are the localization acceptance limits in config/robots.json.
MAX_COVARIANCE_X = 0.25
MAX_COVARIANCE_Y = 0.25
MAX_COVARIANCE_YAW = 0.35
REQUIRED_CONSECUTIVE_LOCALIZED_SAMPLES = 3


@dataclass
class PoseSample:
    x: float
    y: float
    covariance_x: float
    covariance_y: float
    covariance_yaw: float
    received_at: float


@dataclass
class NavigationPoseSample:
    x: float
    y: float
    received_at: float


class AcceptanceClient(Node):
    def __init__(self, args: argparse.Namespace) -> None:
        super().__init__(
            "gazebo_nav2_e2e_acceptance",
            parameter_overrides=[Parameter("use_sim_time", value=True)],
        )
        self.args = args
        self.latest_pose: PoseSample | None = None
        self.latest_navigation_pose: NavigationPoseSample | None = None
        self.initial_pose_publisher = self.create_publisher(PoseWithCovarianceStamped, "/initialpose", 10)
        self.create_subscription(PoseWithCovarianceStamped, "/amcl_pose", self._amcl_pose_callback, 10)
        self.navigation_lifecycle = self.create_client(Trigger, "/lifecycle_manager_navigation/is_active")
        self.localization_lifecycle = self.create_client(Trigger, "/lifecycle_manager_localization/is_active")
        self.navigate = ActionClient(self, NavigateToPose, "/navigate_to_pose")
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

    def _amcl_pose_callback(self, message: PoseWithCovarianceStamped) -> None:
        covariance = message.pose.covariance
        self.latest_pose = PoseSample(
            x=message.pose.pose.position.x,
            y=message.pose.pose.position.y,
            covariance_x=covariance[0],
            covariance_y=covariance[7],
            covariance_yaw=covariance[35],
            received_at=time.monotonic(),
        )

    def publish_initial_pose(self) -> None:
        message = PoseWithCovarianceStamped()
        message.header.frame_id = "map"
        message.header.stamp = self.get_clock().now().to_msg()
        message.pose.pose.position.x = self.args.initial_x
        message.pose.pose.position.y = self.args.initial_y
        message.pose.pose.orientation.z = math.sin(self.args.initial_yaw / 2.0)
        message.pose.pose.orientation.w = math.cos(self.args.initial_yaw / 2.0)
        message.pose.covariance[0] = MAX_COVARIANCE_X
        message.pose.covariance[7] = MAX_COVARIANCE_Y
        message.pose.covariance[35] = MAX_COVARIANCE_YAW
        self.initial_pose_publisher.publish(message)

    def navigation_feedback(self, feedback_message) -> None:
        pose = feedback_message.feedback.current_pose.pose.position
        self.latest_navigation_pose = NavigationPoseSample(
            x=pose.x,
            y=pose.y,
            received_at=time.monotonic(),
        )

    @staticmethod
    def localized(pose: PoseSample | None) -> bool:
        return pose is not None and (
            pose.covariance_x <= MAX_COVARIANCE_X
            and pose.covariance_y <= MAX_COVARIANCE_Y
            and pose.covariance_yaw <= MAX_COVARIANCE_YAW
        )


def wait_for_active(
    node: AcceptanceClient,
    client,
    manager_name: str,
    timeout_sec: float,
) -> None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        if client.wait_for_service(timeout_sec=0.2):
            future = client.call_async(Trigger.Request())
            rclpy.spin_until_future_complete(node, future, timeout_sec=1.0)
            if future.done() and future.result() and future.result().success:
                return
        rclpy.spin_once(node, timeout_sec=0.2)
    raise RuntimeError(f"Nav2 {manager_name} lifecycle manager did not become active")


def wait_for_localization(node: AcceptanceClient, timeout_sec: float) -> None:
    deadline = time.monotonic() + timeout_sec
    consecutive_samples = 0
    last_sample_at = 0.0
    last_initial_pose_at = 0.0
    while time.monotonic() < deadline:
        now = time.monotonic()
        if now - last_initial_pose_at >= 1.0:
            node.publish_initial_pose()
            last_initial_pose_at = now
        rclpy.spin_once(node, timeout_sec=0.5)
        pose = node.latest_pose
        if pose is not None and pose.received_at > last_sample_at:
            last_sample_at = pose.received_at
            consecutive_samples = consecutive_samples + 1 if node.localized(pose) else 0
            if consecutive_samples >= REQUIRED_CONSECUTIVE_LOCALIZED_SAMPLES:
                return
    raise RuntimeError(
        "AMCL did not converge within configured covariance limits "
        f"x<={MAX_COVARIANCE_X}, y<={MAX_COVARIANCE_Y}, yaw<={MAX_COVARIANCE_YAW} "
        f"for {REQUIRED_CONSECUTIVE_LOCALIZED_SAMPLES} consecutive samples"
    )


def latest_navigation_transform(
    node: AcceptanceClient,
    timeout_sec: float,
) -> NavigationPoseSample:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        rclpy.spin_once(node, timeout_sec=0.1)
        try:
            transform = node.tf_buffer.lookup_transform(
                "map",
                "base_link",
                Time(),
                timeout=Duration(seconds=0.2),
            )
        except TransformException:
            continue
        translation = transform.transform.translation
        return NavigationPoseSample(
            x=translation.x,
            y=translation.y,
            received_at=time.monotonic(),
        )
    raise RuntimeError("NavigateToPose SUCCEEDED but final map->base_link TF is unavailable")


def navigate_and_verify(node: AcceptanceClient, timeout_sec: float) -> dict[str, float | int | str]:
    if not node.navigate.wait_for_server(timeout_sec=timeout_sec):
        raise RuntimeError("/navigate_to_pose action server did not become available")

    goal = NavigateToPose.Goal()
    goal.pose = PoseStamped()
    goal.pose.header.frame_id = "map"
    goal.pose.header.stamp = node.get_clock().now().to_msg()
    goal.pose.pose.position.x = node.args.goal_x
    goal.pose.pose.position.y = node.args.goal_y
    goal.pose.pose.orientation.z = math.sin(node.args.goal_yaw / 2.0)
    goal.pose.pose.orientation.w = math.cos(node.args.goal_yaw / 2.0)
    sent_at = time.monotonic()
    goal_future = node.navigate.send_goal_async(
        goal,
        feedback_callback=node.navigation_feedback,
    )
    rclpy.spin_until_future_complete(node, goal_future, timeout_sec=10.0)
    goal_handle = goal_future.result() if goal_future.done() else None
    if goal_handle is None or not goal_handle.accepted:
        raise RuntimeError("NavigateToPose goal was not accepted")

    result_future = goal_handle.get_result_async()
    rclpy.spin_until_future_complete(node, result_future, timeout_sec=timeout_sec)
    if not result_future.done() or result_future.result() is None:
        raise RuntimeError(f"NavigateToPose did not finish within {timeout_sec:.1f}s")
    status = result_future.result().status
    if status != GoalStatus.STATUS_SUCCEEDED:
        raise RuntimeError(f"NavigateToPose status={status}; expected SUCCEEDED ({GoalStatus.STATUS_SUCCEEDED})")

    navigation_pose = latest_navigation_transform(node, timeout_sec=5.0)
    amcl_pose = node.latest_pose
    if navigation_pose.received_at < sent_at:
        raise RuntimeError("NavigateToPose SUCCEEDED without a post-goal map-frame pose")
    if amcl_pose is None:
        raise RuntimeError("NavigateToPose SUCCEEDED without an AMCL covariance sample")

    error_m = math.hypot(
        navigation_pose.x - node.args.goal_x,
        navigation_pose.y - node.args.goal_y,
    )
    if error_m > node.args.max_final_error_m:
        raise RuntimeError(
            "NavigateToPose SUCCEEDED but "
            f"final_error_m={error_m:.4f} exceeds threshold={node.args.max_final_error_m:.4f}"
        )
    return {
        "status": status,
        "status_name": "SUCCEEDED",
        "final_x": navigation_pose.x,
        "final_y": navigation_pose.y,
        "final_error_m": error_m,
        "final_error_threshold_m": node.args.max_final_error_m,
        "final_pose_source": "map_to_base_link_tf",
        "covariance_x": amcl_pose.covariance_x,
        "covariance_y": amcl_pose.covariance_y,
        "covariance_yaw": amcl_pose.covariance_yaw,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("initial-x", "initial-y", "initial-yaw", "goal-x", "goal-y", "goal-yaw", "max-final-error-m"):
        parser.add_argument(f"--{name}", type=float, required=True)
    parser.add_argument("--startup-timeout-sec", type=float, required=True)
    parser.add_argument("--action-timeout-sec", type=float, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    rclpy.init()
    node = AcceptanceClient(args)
    try:
        # Navigation activation needs map->base_link, while AMCL cannot provide
        # that transform until it has received an initial pose. Keep this order.
        wait_for_active(
            node,
            node.localization_lifecycle,
            "localization",
            args.startup_timeout_sec,
        )
        wait_for_localization(node, args.startup_timeout_sec)
        wait_for_active(
            node,
            node.navigation_lifecycle,
            "navigation",
            args.startup_timeout_sec,
        )
        result = navigate_and_verify(node, args.action_timeout_sec)
        print("[gazebo-nav2-e2e] PASS " + json.dumps(result, sort_keys=True))
        return 0
    except Exception as error:
        print(f"[gazebo-nav2-e2e] FAIL {error}", file=sys.stderr)
        return 1
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
