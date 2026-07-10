# Launch robot_localization EKF on Nav PC (same ROS_DOMAIN_ID as robot).
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
import os


def generate_launch_description():
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    default_params = os.path.join(root, 'config', 'robot_localization', 'ekf_tb3_burger.yaml')

    params_file = LaunchConfiguration('params_file')

    return LaunchDescription([
        DeclareLaunchArgument(
            'params_file',
            default_value=default_params,
            description='EKF parameter YAML (ekf_filter_node section)',
        ),
        Node(
            package='robot_localization',
            executable='ekf_node',
            name='ekf_filter_node',
            output='screen',
            parameters=[params_file],
        ),
    ])
