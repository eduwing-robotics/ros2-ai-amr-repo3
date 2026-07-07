from __future__ import annotations

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    use_monitor = LaunchConfiguration("use_aruco_pose_monitor")
    image_topic = LaunchConfiguration("image_topic")
    image_transport = LaunchConfiguration("image_transport")
    target_marker_id = LaunchConfiguration("target_marker_id")
    marker_size_m = LaunchConfiguration("marker_size_m")
    ai_server_pythonpath = LaunchConfiguration("ai_server_pythonpath")

    return LaunchDescription(
        [
            DeclareLaunchArgument("use_aruco_pose_monitor", default_value="false"),
            DeclareLaunchArgument("image_topic", default_value="/camera/image_raw/compressed"),
            DeclareLaunchArgument("image_transport", default_value="compressed"),
            DeclareLaunchArgument("target_marker_id", default_value="ARUCO_4X4_50_0"),
            DeclareLaunchArgument("marker_size_m", default_value="0.08"),
            DeclareLaunchArgument("camera_fx", default_value="600.0"),
            DeclareLaunchArgument("camera_fy", default_value="600.0"),
            DeclareLaunchArgument("camera_cx", default_value="320.0"),
            DeclareLaunchArgument("camera_cy", default_value="240.0"),
            DeclareLaunchArgument("target_distance_m", default_value="0.45"),
            DeclareLaunchArgument("target_lateral_offset_m", default_value="0.0"),
            DeclareLaunchArgument("target_yaw_rad", default_value="0.0"),
            DeclareLaunchArgument("stale_timeout_sec", default_value="0.3"),
            DeclareLaunchArgument("log_period_sec", default_value="0.5"),
            DeclareLaunchArgument(
                "ai_server_pythonpath",
                default_value="/home/codelab/Desktop/Project/SmartFactory/services/ai-server",
            ),
            Node(
                package="smartfactory_perception_ros",
                executable="aruco_pose_monitor",
                name="aruco_pose_monitor",
                output="screen",
                condition=IfCondition(use_monitor),
                parameters=[
                    {
                        "image_topic": image_topic,
                        "image_transport": image_transport,
                        "target_marker_id": target_marker_id,
                        "marker_size_m": ParameterValue(marker_size_m, value_type=float),
                        "camera_fx": ParameterValue(LaunchConfiguration("camera_fx"), value_type=float),
                        "camera_fy": ParameterValue(LaunchConfiguration("camera_fy"), value_type=float),
                        "camera_cx": ParameterValue(LaunchConfiguration("camera_cx"), value_type=float),
                        "camera_cy": ParameterValue(LaunchConfiguration("camera_cy"), value_type=float),
                        "target_distance_m": ParameterValue(LaunchConfiguration("target_distance_m"), value_type=float),
                        "target_lateral_offset_m": ParameterValue(LaunchConfiguration("target_lateral_offset_m"), value_type=float),
                        "target_yaw_rad": ParameterValue(LaunchConfiguration("target_yaw_rad"), value_type=float),
                        "stale_timeout_sec": ParameterValue(LaunchConfiguration("stale_timeout_sec"), value_type=float),
                        "log_period_sec": ParameterValue(LaunchConfiguration("log_period_sec"), value_type=float),
                    }
                ],
                additional_env={"SMARTFACTORY_AI_SERVER_PYTHONPATH": ai_server_pythonpath},
            ),
        ]
    )
