#!/usr/bin/env python3

from launch import LaunchDescription
from launch.actions import ExecuteProcess
from launch.substitutions import LaunchConfiguration
from launch.actions import DeclareLaunchArgument


def generate_launch_description():
    params_file = LaunchConfiguration("params_file")
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "params_file",
                default_value="/home/lucas/slam_nav_ws/config/agv_follower.yaml",
            ),
            ExecuteProcess(
                cmd=[
                    "python3",
                    "/home/lucas/slam_nav_ws/scripts/agv_orthogonal_follower.py",
                    "--ros-args",
                    "--params-file",
                    params_file,
                ],
                output="screen",
            ),
        ]
    )
