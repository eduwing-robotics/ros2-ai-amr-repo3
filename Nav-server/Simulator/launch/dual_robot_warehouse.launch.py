#!/usr/bin/env python3
# Launch one Gazebo world with tb3_1 in domain 2 and tb3_2 in domain 5.

import os
import sys
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import AppendEnvironmentVariable, DeclareLaunchArgument, IncludeLaunchDescription, TimerAction
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

SIMULATOR_ROOT = Path(os.getenv("SIMULATOR_ROOT", Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(SIMULATOR_ROOT / "scripts"))
from dual_robot_geometry import load_layout


def generate_launch_description():
    layout = load_layout()
    world = LaunchConfiguration("world")
    gui = LaunchConfiguration("gui")
    use_sim_time = LaunchConfiguration("use_sim_time")
    generated = SIMULATOR_ROOT / "generated" / "dual_robot"
    ros_gz_share = get_package_share_directory("ros_gz_sim")
    tb3_share = Path(get_package_share_directory("turtlebot3_gazebo"))
    sensor_config = Path(os.getenv(
        "DUAL_SIM_SENSOR_CONFIG",
        SIMULATOR_ROOT / "config" / "gz_sim_sensors_server.config",
    ))
    robot_description = (tb3_share / "urdf" / "turtlebot3_burger.urdf").read_text(encoding="utf-8")

    headless_setting = os.getenv("GAZEBO_HEADLESS_RENDERING", "auto").strip().lower()
    use_headless_rendering = headless_setting in ("1", "true", "yes", "on") or (
        headless_setting == "auto" and not os.getenv("DISPLAY")
    )
    server_flags = "-r -s -v2"
    if use_headless_rendering:
        server_flags += " --headless-rendering"

    actions = [
        DeclareLaunchArgument("world", default_value=str(SIMULATOR_ROOT / "worlds" / "generated_nav_server_dual.world")),
        DeclareLaunchArgument("gui", default_value="false"),
        DeclareLaunchArgument("use_sim_time", default_value="true"),
        AppendEnvironmentVariable("GZ_SIM_RESOURCE_PATH", os.pathsep.join([str(SIMULATOR_ROOT / "models"), str(tb3_share / "models")])),
        AppendEnvironmentVariable("GZ_SIM_SERVER_CONFIG_PATH", str(sensor_config)),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(str(Path(ros_gz_share) / "launch" / "gz_sim.launch.py")),
            launch_arguments={"gz_args": [server_flags + " ", world], "on_exit_shutdown": "true"}.items(),
        ),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(str(Path(ros_gz_share) / "launch" / "gz_sim.launch.py")),
            launch_arguments={"gz_args": "-g -v2"}.items(),
            condition=IfCondition(gui),
        ),
    ]

    spawn_actions = []
    for robot in layout["robots"]:
        name = str(robot["name"])
        domain = str(robot["ros_domain_id"])
        hold = robot["hold_pose"]
        env = {"ROS_DOMAIN_ID": domain, "TURTLEBOT3_MODEL": "burger"}
        actions.extend([
            Node(
                package="robot_state_publisher",
                executable="robot_state_publisher",
                name="robot_state_publisher",
                output="screen",
                parameters=[{"use_sim_time": use_sim_time, "robot_description": robot_description}],
                additional_env=env,
            ),
            Node(
                package="ros_gz_bridge",
                executable="parameter_bridge",
                name="{}_gz_bridge".format(name),
                arguments=["--ros-args", "-p", "config_file:={}".format(generated / "{}_bridge.yaml".format(name))],
                output="screen",
                additional_env=env,
            ),
        ])
        spawn_actions.append(Node(
            package="ros_gz_sim",
            executable="create",
            name="spawn_{}".format(name),
            arguments=[
                "-name", name,
                "-file", str(generated / "{}.sdf".format(name)),
                "-x", str(hold["x"]),
                "-y", str(hold["y"]),
                "-z", "0.01",
                "-Y", str(hold["yaw"]),
            ],
            output="screen",
            additional_env=env,
        ))
    actions.append(TimerAction(period=4.0, actions=spawn_actions))
    return LaunchDescription(actions)
