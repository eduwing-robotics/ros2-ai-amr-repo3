"""Fast checks for the pip/ROS dependency boundary used by the running API."""

from importlib import import_module
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
ROS_RUNTIME_IMPORTS = (
    "rclpy",
    "tf2_ros",
    "geometry_msgs",
    "nav2_simple_commander",
)
APP_RUNTIME_IMPORTS = ("nav_app", "uvicorn")


def test_numpy_is_declared_for_ros_python_message_imports():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")
    assert any(line.strip().startswith("numpy==") for line in requirements.splitlines())


def test_ros_backed_runtime_imports_are_available():
    try:
        import_module("rclpy")
    except ModuleNotFoundError as error:
        pytest.skip(f"ROS 2 runtime is unavailable in this environment: {error}")

    for module_name in (*ROS_RUNTIME_IMPORTS, *APP_RUNTIME_IMPORTS):
        import_module(module_name)
