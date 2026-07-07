from __future__ import annotations

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    use_bridge = LaunchConfiguration("use_vision_overlay_stream_bridge")

    return LaunchDescription(
        [
            DeclareLaunchArgument("use_vision_overlay_stream_bridge", default_value="false"),
            DeclareLaunchArgument("host", default_value="0.0.0.0"),
            DeclareLaunchArgument("port", default_value="8090"),
            DeclareLaunchArgument("sources", default_value="tb3_1_picam"),
            DeclareLaunchArgument("overlay_topics_json", default_value=""),
            DeclareLaunchArgument("max_fps", default_value="15.0"),
            DeclareLaunchArgument("stale_after_sec", default_value="2.0"),
            DeclareLaunchArgument("cors_allow_origin", default_value=""),
            DeclareLaunchArgument("overlay_sub_qos_reliability", default_value="reliable"),
            DeclareLaunchArgument("overlay_sub_qos_depth", default_value="1"),
            LogInfo(
                condition=UnlessCondition(use_bridge),
                msg=(
                    "[SmartFactory] D1 read-only vision overlay stream bridge disabled. "
                    "Enable with use_vision_overlay_stream_bridge:=true."
                ),
            ),
            Node(
                condition=IfCondition(use_bridge),
                package="smartfactory_perception_ros",
                executable="vision_overlay_stream_bridge",
                name="vision_overlay_stream_bridge",
                output="screen",
                parameters=[
                    {
                        "host": LaunchConfiguration("host"),
                        "port": ParameterValue(LaunchConfiguration("port"), value_type=int),
                        "sources": LaunchConfiguration("sources"),
                        "overlay_topics_json": LaunchConfiguration("overlay_topics_json"),
                        "max_fps": ParameterValue(LaunchConfiguration("max_fps"), value_type=float),
                        "stale_after_sec": ParameterValue(
                            LaunchConfiguration("stale_after_sec"),
                            value_type=float,
                        ),
                        "cors_allow_origin": LaunchConfiguration("cors_allow_origin"),
                        "overlay_sub_qos_reliability": LaunchConfiguration(
                            "overlay_sub_qos_reliability"
                        ),
                        "overlay_sub_qos_depth": ParameterValue(
                            LaunchConfiguration("overlay_sub_qos_depth"),
                            value_type=int,
                        ),
                    }
                ],
            ),
        ]
    )
