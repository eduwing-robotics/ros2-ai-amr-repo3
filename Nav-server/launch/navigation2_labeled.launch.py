#!/usr/bin/env python3
# Nav2 + RViz with a clear per-robot window title (tb3_1 vs tb3_2).
# Replaces turtlebot3_navigation2/navigation2.launch.py when dual robots run.

import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    use_sim_time = LaunchConfiguration("use_sim_time")
    map_yaml = LaunchConfiguration("map")
    autostart = LaunchConfiguration("autostart")
    params_file = LaunchConfiguration("params_file")
    rviz_config = LaunchConfiguration("rviz_config")
    rviz_title = LaunchConfiguration("rviz_title")

    turtlebot3_share = get_package_share_directory("turtlebot3_navigation2")
    nav2_bringup_dir = os.path.join(
        get_package_share_directory("nav2_bringup"), "launch"
    )
    default_rviz = os.path.join(turtlebot3_share, "rviz", "tb3_navigation2.rviz")

    return LaunchDescription(
        [
            DeclareLaunchArgument("use_sim_time", default_value="false"),
            DeclareLaunchArgument("map"),
            DeclareLaunchArgument("params_file"),
            DeclareLaunchArgument("rviz_config", default_value=default_rviz),
            DeclareLaunchArgument("autostart", default_value="true"),
            DeclareLaunchArgument(
                "rviz_title",
                default_value="RViz2",
                description="Window title shown in the desktop taskbar",
            ),
            IncludeLaunchDescription(
                PythonLaunchDescriptionSource(
                    [nav2_bringup_dir, "/bringup_launch.py"]
                ),
                launch_arguments={
                    "map": map_yaml,
                    "use_sim_time": use_sim_time,
                    "autostart": autostart,
                    "params_file": params_file,
                }.items(),
            ),
            Node(
                package="rviz2",
                executable="rviz2",
                name="rviz2",
                arguments=["-d", rviz_config, "-t", rviz_title],
                parameters=[{"use_sim_time": use_sim_time}],
                output="screen",
            ),
        ]
    )
