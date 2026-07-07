from setuptools import find_packages, setup

package_name = 'smartfactory_perception_ros'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        ('share/' + package_name + '/launch', [
            'launch/ai_snapshot_clients.launch.py',
            'launch/aruco_pose_monitor.launch.py',
            'launch/vision_frame_gateway.launch.py',
            'launch/vision_overlay_stream_bridge.launch.py',
        ]),
        ('share/' + package_name + '/config', [
            'config/lane_c_domain_bridge_allowlist.yaml',
        ]),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='SmartFactory Team',
    maintainer_email='codex-planner@example.com',
    description='Thin ROS2 camera snapshot adapter for the SmartFactory AI Server.',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'image_snapshot_client = smartfactory_perception_ros.image_snapshot_client:main',
            'aruco_pose_monitor = smartfactory_perception_ros.aruco_pose_monitor:main',
            'vision_frame_gateway = smartfactory_perception_ros.vision_frame_gateway:main',
            'vision_overlay_stream_bridge = smartfactory_perception_ros.vision_overlay_stream_bridge:main',
        ],
    },
)
