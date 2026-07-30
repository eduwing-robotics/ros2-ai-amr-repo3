#!/usr/bin/env python3

from pathlib import Path

from launch.actions import DeclareLaunchArgument, ExecuteProcess
from launch.substitutions import LaunchConfiguration

from launch import LaunchDescription

EXPERIMENT_ROOT = Path(__file__).resolve().parents[1]


def generate_launch_description():
    params_file = LaunchConfiguration("params_file")
    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "params_file",
                default_value=str(EXPERIMENT_ROOT / "config" / "agv_follower.yaml"),
            ),
            ExecuteProcess(
                cmd=[
                    "python3",
                    str(EXPERIMENT_ROOT / "agv_orthogonal_follower.py"),
                    "--ros-args",
                    "--params-file",
                    params_file,
                ],
                output="screen",
            ),
        ]
    )
