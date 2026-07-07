"""Launch ROS image snapshot clients that POST frames to the AI Server.

This layer is intentionally disabled by default. It is a ROS-side adapter only:
no inference, no WMS policy, and no robot control. Robot PiCam defaults use
sensor_msgs/CompressedImage because the TurtleBot3 camera.launch.py compressed
stream runs close to camera frame rate while raw can be substantially slower.
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node


def _enabled_with(snapshot_flag, source_flag):
    return IfCondition(
        PythonExpression([
            "'", snapshot_flag, "' == 'true' and '", source_flag, "' == 'true'"
        ])
    )


def _snapshot_node(*, name, source_id, image_topic, image_transport, condition):
    return Node(
        condition=condition,
        package='smartfactory_perception_ros',
        executable='image_snapshot_client',
        name=name,
        output='screen',
        parameters=[{
            'source_id': source_id,
            'image_topic': image_topic,
            'image_transport': image_transport,
            'ai_server_url': LaunchConfiguration('ai_server_url'),
            'emit': LaunchConfiguration('ai_snapshot_emit'),
            'snapshot_period_sec': LaunchConfiguration('ai_snapshot_period_sec'),
            'request_timeout_sec': LaunchConfiguration('ai_snapshot_timeout_sec'),
            'image_format': 'jpg',
        }],
    )


def generate_launch_description():
    use_ai_snapshot_clients = LaunchConfiguration('use_ai_snapshot_clients')
    use_global_camera = LaunchConfiguration('use_global_camera')
    use_robot_picams = LaunchConfiguration('use_robot_picams')

    return LaunchDescription([
        DeclareLaunchArgument('use_ai_snapshot_clients', default_value='false'),
        DeclareLaunchArgument('use_global_camera', default_value='false'),
        DeclareLaunchArgument('use_robot_picams', default_value='false'),
        DeclareLaunchArgument('use_ai_server', default_value='false'),
        DeclareLaunchArgument('use_wms_bridge', default_value='false'),
        DeclareLaunchArgument('use_nav2', default_value='false'),
        DeclareLaunchArgument(
            'repo_root',
            default_value='/home/codelab/Desktop/Project/SmartFactory',
        ),
        DeclareLaunchArgument('ai_server_host', default_value='127.0.0.1'),
        DeclareLaunchArgument('ai_server_port', default_value='8100'),
        DeclareLaunchArgument('main_server_url', default_value='http://127.0.0.1:8000'),
        DeclareLaunchArgument('ai_server_url', default_value='http://127.0.0.1:8100'),
        DeclareLaunchArgument('ai_snapshot_period_sec', default_value='1.0'),
        DeclareLaunchArgument('ai_snapshot_timeout_sec', default_value='1.0'),
        DeclareLaunchArgument('ai_snapshot_emit', default_value='false'),
        DeclareLaunchArgument('global_cam_image_topic', default_value='/global_camera/image_raw'),
        DeclareLaunchArgument('global_cam_image_transport', default_value='raw'),
        DeclareLaunchArgument(
            'tb3_1_picam_image_topic',
            default_value='/tb3_1/pi_camera/image_raw/compressed',
        ),
        DeclareLaunchArgument('tb3_1_picam_image_transport', default_value='compressed'),
        DeclareLaunchArgument(
            'tb3_2_picam_image_topic',
            default_value='/tb3_2/pi_camera/image_raw/compressed',
        ),
        DeclareLaunchArgument('tb3_2_picam_image_transport', default_value='compressed'),
        LogInfo(
            condition=UnlessCondition(use_ai_snapshot_clients),
            msg=(
                '[SmartFactory] AI snapshot clients disabled. '
                'Enable with use_ai_snapshot_clients:=true.'
            ),
        ),
        _snapshot_node(
            name='global_cam_01_snapshot_client',
            source_id='global_cam_01',
            image_topic=LaunchConfiguration('global_cam_image_topic'),
            image_transport=LaunchConfiguration('global_cam_image_transport'),
            condition=_enabled_with(use_ai_snapshot_clients, use_global_camera),
        ),
        _snapshot_node(
            name='tb3_1_picam_snapshot_client',
            source_id='tb3_1_picam',
            image_topic=LaunchConfiguration('tb3_1_picam_image_topic'),
            image_transport=LaunchConfiguration('tb3_1_picam_image_transport'),
            condition=_enabled_with(use_ai_snapshot_clients, use_robot_picams),
        ),
        _snapshot_node(
            name='tb3_2_picam_snapshot_client',
            source_id='tb3_2_picam',
            image_topic=LaunchConfiguration('tb3_2_picam_image_topic'),
            image_transport=LaunchConfiguration('tb3_2_picam_image_transport'),
            condition=_enabled_with(use_ai_snapshot_clients, use_robot_picams),
        ),
    ])
