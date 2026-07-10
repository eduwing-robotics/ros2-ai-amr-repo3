#!/usr/bin/env python3

from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.substitutions import LaunchConfiguration


NAV_SERVER_ROOT = Path(__file__).resolve().parents[1]


def generate_launch_description():
    params_file = LaunchConfiguration("params_file")
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "params_file",
                default_value=str(NAV_SERVER_ROOT / "config" / "agv_follower.yaml"),
            ),
            ExecuteProcess(
                cmd=[
                    "python3",
                    str(NAV_SERVER_ROOT / "scripts" / "agv_orthogonal_follower.py"),
                    "--ros-args",
                    "--params-file",
                    params_file,
                ],
                output="screen",
            ),
        ]
    )
