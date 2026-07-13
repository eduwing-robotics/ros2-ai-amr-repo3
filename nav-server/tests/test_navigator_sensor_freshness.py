"""ROS-free tests for the navigator's receipt/header freshness policy."""

from __future__ import annotations

import importlib.util
import sys
import threading
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]


def _module(monkeypatch, name: str, **values):
    module = ModuleType(name)
    for key, value in values.items():
        setattr(module, key, value)
    monkeypatch.setitem(sys.modules, name, module)
    return module


@pytest.fixture
def navigator_class(monkeypatch):
    _module(monkeypatch, "rclpy")
    _module(monkeypatch, "rclpy.node", Node=object)
    _module(monkeypatch, "rclpy.qos", DurabilityPolicy=SimpleNamespace(TRANSIENT_LOCAL=1), QoSProfile=object, ReliabilityPolicy=SimpleNamespace(RELIABLE=1, BEST_EFFORT=2), qos_profile_sensor_data=object())
    _module(monkeypatch, "rclpy.duration", Duration=lambda **_kwargs: object())
    _module(monkeypatch, "rclpy.time", Time=object)
    _module(monkeypatch, "rcl_interfaces")
    _module(monkeypatch, "rcl_interfaces.msg", Parameter=object, ParameterType=object, ParameterValue=object)
    _module(monkeypatch, "rcl_interfaces.srv", GetParameters=object, SetParameters=object)
    _module(monkeypatch, "tf2_ros", Buffer=object, ConnectivityException=Exception, ExtrapolationException=Exception, LookupException=Exception, TransformListener=object)
    _module(monkeypatch, "geometry_msgs")
    _module(monkeypatch, "geometry_msgs.msg", PoseStamped=object, PoseWithCovarianceStamped=object, TwistStamped=object)
    _module(monkeypatch, "nav2_simple_commander")
    _module(monkeypatch, "nav2_simple_commander.robot_navigator", BasicNavigator=object, TaskResult=SimpleNamespace(SUCCEEDED=1))
    _module(monkeypatch, "sensor_msgs")
    _module(monkeypatch, "sensor_msgs.msg", BatteryState=object, CompressedImage=object, LaserScan=object)
    _module(monkeypatch, "std_msgs")
    _module(monkeypatch, "std_msgs.msg", Bool=object, String=object)
    _module(monkeypatch, "std_srvs")
    _module(monkeypatch, "std_srvs.srv", Empty=object)
    spec = importlib.util.spec_from_file_location("freshness_navigator", ROOT / "scripts" / "logistics_navigator.py")
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module.LogisticsNavigator


def _navigator(cls, *, scan_stamp, tf_stamp, aruco=True):
    now_wall = time.time()
    now_monotonic = time.monotonic()
    navigator = cls.__new__(cls)
    navigator.scan_lock = threading.Lock()
    navigator.latest_scan = object()
    navigator.latest_scan_monotonic = now_monotonic
    navigator.latest_scan_header_stamp_sec = scan_stamp
    navigator.latest_tf_monotonic = now_monotonic
    navigator.latest_tf_header_stamp_sec = tf_stamp
    navigator.latest_tf_continuous = True
    navigator.last_velocity_loop_latency_sec = 0.002
    navigator.last_pose_lock = threading.Lock()
    navigator.last_pose = {
        "receipt_monotonic": now_monotonic,
        "stamp": {"sec": int(now_wall), "nanosec": int((now_wall % 1.0) * 1e9)},
        "covariance": {"x": 0.01, "y": 0.01, "yaw": 0.01},
    }
    navigator.latest_aruco_receipt_monotonic = now_monotonic if aruco else 0.0
    navigator.latest_aruco_source_stamp_sec = now_wall if aruco else None
    navigator._pose_from_transform = lambda: None
    return navigator, now_wall


@pytest.mark.parametrize(
    ("scan_offset", "tf_offset", "expected"),
    [(-3.0, 0.0, "scan_stale"), (0.0, -3.0, "tf_stale"), (1.0, 0.0, "scan_timestamp_future")],
)
def test_header_timestamp_staleness_and_future_time_fail_closed(navigator_class, scan_offset, tf_offset, expected):
    now = time.time()
    navigator, _ = _navigator(navigator_class, scan_stamp=now + scan_offset, tf_stamp=now + tf_offset)

    health = navigator.docking_sensor_freshness(require_aruco=True, max_scan_age_sec=1.0, max_tf_age_sec=1.0)

    assert health["ok"] is False
    assert health["reason"] == expected


def test_dropped_aruco_frame_fails_closed(navigator_class):
    now = time.time()
    navigator, _ = _navigator(navigator_class, scan_stamp=now, tf_stamp=now, aruco=False)

    health = navigator.docking_sensor_freshness(require_aruco=True)

    assert "velocity_loop_latency_sec" in health
    assert health["ok"] is False
    assert health["reason"] == "aruco_missing_or_stale"


def test_stale_localization_fails_closed(navigator_class):
    now = time.time()
    navigator, _ = _navigator(navigator_class, scan_stamp=now, tf_stamp=now)
    navigator.last_pose["receipt_monotonic"] = time.monotonic() - 3.0

    health = navigator.docking_sensor_freshness(require_aruco=True, max_tf_age_sec=1.0)

    assert health["ok"] is False
    assert health["reason"] == "localization_missing_or_stale"


def test_amcl_postdated_tf_within_transform_tolerance_is_accepted(navigator_class, monkeypatch):
    now = time.time()
    navigator, _ = _navigator(navigator_class, scan_stamp=now, tf_stamp=now + 1.5)
    monkeypatch.setenv("TF_FUTURE_TOLERANCE_SEC", "2.0")

    health = navigator.docking_sensor_freshness(require_aruco=True, max_tf_age_sec=2.0)

    assert health["ok"] is True
    assert health["reason"] == "ok"


def test_tf_beyond_configured_postdate_window_fails_closed(navigator_class, monkeypatch):
    now = time.time()
    navigator, _ = _navigator(navigator_class, scan_stamp=now, tf_stamp=now + 2.5)
    monkeypatch.setenv("TF_FUTURE_TOLERANCE_SEC", "2.0")

    health = navigator.docking_sensor_freshness(require_aruco=True, max_tf_age_sec=2.0)

    assert health["ok"] is False
    assert health["reason"] == "tf_timestamp_future"


def test_pose_lookup_accepts_amcl_postdated_transform_within_tf_window(navigator_class, monkeypatch):
    now = time.time() + 1.5
    seconds = int(now)
    nanoseconds = int((now - seconds) * 1e9)
    transform = SimpleNamespace(
        header=SimpleNamespace(
            frame_id="map",
            stamp=SimpleNamespace(sec=seconds, nanosec=nanoseconds),
        ),
        child_frame_id="base_link",
        transform=SimpleNamespace(
            translation=SimpleNamespace(x=1.0, y=2.0),
            rotation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
        ),
    )
    navigator = navigator_class.__new__(navigator_class)
    navigator.tf_buffer = SimpleNamespace(lookup_transform=lambda *_args, **_kwargs: transform)
    navigator.latest_tf_monotonic = 0.0
    navigator.latest_tf_header_stamp_sec = None
    navigator.latest_tf_continuous = False
    monkeypatch.setenv("TF_FUTURE_TOLERANCE_SEC", "2.0")

    pose = navigator._pose_from_transform()

    assert pose is not None
    assert pose["x"] == 1.0
    assert navigator.latest_tf_continuous is True


def test_one_transient_tf_lookup_miss_keeps_recent_success_continuous(navigator_class):
    navigator = navigator_class.__new__(navigator_class)
    navigator.tf_buffer = SimpleNamespace(
        lookup_transform=lambda *_args, **_kwargs: (_ for _ in ()).throw(Exception("transient TF race"))
    )
    navigator.latest_tf_monotonic = time.monotonic()
    navigator.latest_tf_header_stamp_sec = time.time()
    navigator.latest_tf_continuous = True

    assert navigator._pose_from_transform() is None
    assert navigator.latest_tf_continuous is True

    navigator.latest_tf_monotonic = time.monotonic() - 3.0
    assert navigator._pose_from_transform() is None
    assert navigator.latest_tf_continuous is False
