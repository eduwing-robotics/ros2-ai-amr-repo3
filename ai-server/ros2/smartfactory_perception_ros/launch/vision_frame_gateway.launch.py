from __future__ import annotations

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, LogInfo
from launch.conditions import IfCondition, UnlessCondition
from launch.substitutions import LaunchConfiguration, PythonExpression
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def _enabled_with(global_flag, source_flag):
    return IfCondition(
        PythonExpression(["'", global_flag, "' == 'true' and '", source_flag, "' == 'true'"])
    )


def _gateway_node(*, name, source_id, image_topic, overlay_topic, condition):
    return Node(
        condition=condition,
        package="smartfactory_perception_ros",
        executable="vision_frame_gateway",
        name=name,
        output="screen",
        parameters=[
            {
                "source_id": source_id,
                "image_topic": image_topic,
                "image_transport": "compressed",
                "ai_server_url": LaunchConfiguration("ai_server_url"),
                "frame_process_path": LaunchConfiguration("frame_process_path"),
                "request_timeout_sec": ParameterValue(
                    LaunchConfiguration("request_timeout_sec"), value_type=float
                ),
                "publish_period_sec": ParameterValue(
                    LaunchConfiguration("publish_period_sec"), value_type=float
                ),
                "publish_output_period_sec": ParameterValue(
                    LaunchConfiguration("publish_output_period_sec"), value_type=float
                ),
                "image_qos_reliability": LaunchConfiguration("image_qos_reliability"),
                "image_qos_depth": ParameterValue(
                    LaunchConfiguration("image_qos_depth"), value_type=int
                ),
                "overlay_pub_qos_reliability": LaunchConfiguration(
                    "overlay_pub_qos_reliability"
                ),
                "overlay_pub_qos_depth": ParameterValue(
                    LaunchConfiguration("overlay_pub_qos_depth"), value_type=int
                ),
                "async_pipeline": ParameterValue(
                    LaunchConfiguration("async_pipeline"), value_type=bool
                ),
                "process_frame_inline": ParameterValue(
                    LaunchConfiguration("process_frame_inline"), value_type=bool
                ),
                "retry_failed_frame": ParameterValue(
                    LaunchConfiguration("retry_failed_frame"), value_type=bool
                ),
                "retry_backoff_sec": ParameterValue(
                    LaunchConfiguration("retry_backoff_sec"), value_type=float
                ),
                "publish_lagging_overlay": ParameterValue(
                    LaunchConfiguration("publish_lagging_overlay"), value_type=bool
                ),
                "process_with_worker_tick": ParameterValue(
                    LaunchConfiguration("process_with_worker_tick"), value_type=bool
                ),
                "force_worker_tick": ParameterValue(
                    LaunchConfiguration("force_worker_tick"), value_type=bool
                ),
                "mark_worker_tick_stale": ParameterValue(
                    LaunchConfiguration("mark_worker_tick_stale"), value_type=bool
                ),
                "publish_overlay": ParameterValue(
                    LaunchConfiguration("publish_overlay"), value_type=bool
                ),
                "publish_evidence": ParameterValue(
                    LaunchConfiguration("publish_evidence"), value_type=bool
                ),
                "overlay_topic": overlay_topic,
                "evidence_topic": LaunchConfiguration("evidence_topic"),
            }
        ],
    )


def generate_launch_description():
    use_gateway = LaunchConfiguration("use_vision_frame_gateway")
    use_tb3_1 = LaunchConfiguration("use_tb3_1_picam")
    use_tb3_2 = LaunchConfiguration("use_tb3_2_picam")
    use_global = LaunchConfiguration("use_global_cam")

    return LaunchDescription(
        [
            DeclareLaunchArgument("use_vision_frame_gateway", default_value="false"),
            DeclareLaunchArgument("use_tb3_1_picam", default_value="false"),
            DeclareLaunchArgument("use_tb3_2_picam", default_value="false"),
            DeclareLaunchArgument("use_global_cam", default_value="false"),
            DeclareLaunchArgument("ai_server_url", default_value="http://127.0.0.1:8100"),
            DeclareLaunchArgument(
                "frame_process_path",
                default_value="/api/v1/vision/frame/process",
            ),
            DeclareLaunchArgument("request_timeout_sec", default_value="1.0"),
            DeclareLaunchArgument("publish_period_sec", default_value="0.2"),
            DeclareLaunchArgument("publish_output_period_sec", default_value="0.02"),
            DeclareLaunchArgument("image_qos_reliability", default_value="sensor_data"),
            DeclareLaunchArgument("image_qos_depth", default_value="1"),
            DeclareLaunchArgument("overlay_pub_qos_reliability", default_value="reliable"),
            DeclareLaunchArgument("overlay_pub_qos_depth", default_value="1"),
            DeclareLaunchArgument("async_pipeline", default_value="true"),
            DeclareLaunchArgument("process_frame_inline", default_value="true"),
            DeclareLaunchArgument("retry_failed_frame", default_value="true"),
            DeclareLaunchArgument("retry_backoff_sec", default_value="0.05"),
            DeclareLaunchArgument("publish_lagging_overlay", default_value="false"),
            DeclareLaunchArgument("process_with_worker_tick", default_value="false"),
            DeclareLaunchArgument("force_worker_tick", default_value="false"),
            DeclareLaunchArgument("mark_worker_tick_stale", default_value="false"),
            DeclareLaunchArgument("publish_overlay", default_value="false"),
            DeclareLaunchArgument("publish_evidence", default_value="false"),
            DeclareLaunchArgument("evidence_topic", default_value="/sf/vision/events"),
            DeclareLaunchArgument(
                "global_cam_image_topic",
                default_value="/global_camera/image_raw/compressed",
            ),
            DeclareLaunchArgument(
                "tb3_1_picam_image_topic",
                default_value="/tb3_1/camera/image_raw/compressed",
            ),
            DeclareLaunchArgument(
                "tb3_2_picam_image_topic",
                default_value="/tb3_2/camera/image_raw/compressed",
            ),
            LogInfo(
                condition=UnlessCondition(use_gateway),
                msg=(
                    "[SmartFactory] Lane C vision_frame_gateway disabled. "
                    "Enable with use_vision_frame_gateway:=true and one source flag."
                ),
            ),
            _gateway_node(
                name="global_cam_01_vision_frame_gateway",
                source_id="global_cam_01",
                image_topic=LaunchConfiguration("global_cam_image_topic"),
                overlay_topic="/sf/vision/sources/global_cam_01/overlay/compressed",
                condition=_enabled_with(use_gateway, use_global),
            ),
            _gateway_node(
                name="tb3_1_picam_vision_frame_gateway",
                source_id="tb3_1_picam",
                image_topic=LaunchConfiguration("tb3_1_picam_image_topic"),
                overlay_topic="/sf/vision/sources/tb3_1_picam/overlay/compressed",
                condition=_enabled_with(use_gateway, use_tb3_1),
            ),
            _gateway_node(
                name="tb3_2_picam_vision_frame_gateway",
                source_id="tb3_2_picam",
                image_topic=LaunchConfiguration("tb3_2_picam_image_topic"),
                overlay_topic="/sf/vision/sources/tb3_2_picam/overlay/compressed",
                condition=_enabled_with(use_gateway, use_tb3_2),
            ),
        ]
    )
