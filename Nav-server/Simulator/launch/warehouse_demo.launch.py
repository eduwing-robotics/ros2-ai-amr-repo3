"""Launch Gazebo Sim with a generated warehouse world and one TurtleBot3 burger."""

import os
from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import AppendEnvironmentVariable, DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, TextSubstitution
from launch_ros.actions import Node


def _simulator_root() -> str:
    env = os.environ.get("SIMULATOR_ROOT")
    if env:
        return env
    return str(Path(__file__).resolve().parents[1])


def generate_launch_description():
    simulator_dir = _simulator_root()
    world = LaunchConfiguration("world")
    gui = LaunchConfiguration("gui")
    x_pose = LaunchConfiguration("x_pose")
    y_pose = LaunchConfiguration("y_pose")
    yaw = LaunchConfiguration("yaw")
    use_sim_time = LaunchConfiguration("use_sim_time")

    ros_gz_sim_share = get_package_share_directory("ros_gz_sim")
    turtlebot3_gazebo_share = get_package_share_directory("turtlebot3_gazebo")
    launch_file_dir = os.path.join(turtlebot3_gazebo_share, "launch")

    turtlebot3_model = os.environ.get("TURTLEBOT3_MODEL", "burger")
    model_folder = f"turtlebot3_{turtlebot3_model}"
    robot_sdf = os.path.join(turtlebot3_gazebo_share, "models", model_folder, "model.sdf")
    bridge_params = LaunchConfiguration("bridge_config")
    gz_server_config_path = LaunchConfiguration("gz_server_config")
    default_bridge = os.path.join(simulator_dir, "config", f"{model_folder}_bridge_sim.yaml")
    default_gz_server = os.path.join(simulator_dir, "config", "gz_sim_sensors_server.config")

    gz_resource_paths = os.pathsep.join(
        [
            os.path.join(simulator_dir, "models"),
            os.path.join(turtlebot3_gazebo_share, "models"),
        ]
    )

    gzserver_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(ros_gz_sim_share, "launch", "gz_sim.launch.py")
        ),
        launch_arguments={
            "gz_args": ["-r -s --headless-rendering -v2 ", world],
            "on_exit_shutdown": "true",
        }.items(),
    )

    gzclient_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(ros_gz_sim_share, "launch", "gz_sim.launch.py")
        ),
        launch_arguments={"gz_args": "-g -v2"}.items(),
        condition=IfCondition(gui),
    )

    robot_state_publisher_cmd = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            os.path.join(launch_file_dir, "robot_state_publisher.launch.py")
        ),
        launch_arguments={"use_sim_time": use_sim_time}.items(),
    )

    spawn_robot_cmd = Node(
        package="ros_gz_sim",
        executable="create",
        arguments=[
            "-name",
            turtlebot3_model,
            "-file",
            robot_sdf,
            "-x",
            x_pose,
            "-y",
            y_pose,
            "-z",
            "0.01",
            "-Y",
            yaw,
        ],
        output="screen",
    )

    bridge_cmd = Node(
        package="ros_gz_bridge",
        executable="parameter_bridge",
        arguments=[
            "--ros-args",
            "-p",
            [TextSubstitution(text="config_file:="), bridge_params],
        ],
        output="screen",
    )

    return LaunchDescription(
        [
            DeclareLaunchArgument(
                "world",
                default_value=os.path.join(simulator_dir, "worlds", "warehouse.world"),
            ),
            DeclareLaunchArgument("gui", default_value="false"),
            DeclareLaunchArgument("use_sim_time", default_value="true"),
            DeclareLaunchArgument("x_pose", default_value="0.765"),
            DeclareLaunchArgument("y_pose", default_value="0.58"),
            DeclareLaunchArgument("yaw", default_value="-1.57"),
            DeclareLaunchArgument("bridge_config", default_value=default_bridge),
            DeclareLaunchArgument("gz_server_config", default_value=default_gz_server),
            AppendEnvironmentVariable("GZ_SIM_RESOURCE_PATH", gz_resource_paths),
            AppendEnvironmentVariable("GZ_SIM_SERVER_CONFIG_PATH", gz_server_config_path),
            gzserver_cmd,
            gzclient_cmd,
            robot_state_publisher_cmd,
            spawn_robot_cmd,
            bridge_cmd,
        ]
    )
