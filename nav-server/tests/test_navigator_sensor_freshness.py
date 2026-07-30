"""ROS-free tests for the navigator's receipt/header freshness policy."""

from __future__ import annotations

import importlib.util
import sys
import threading
import time
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import Mock

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
    _module(
        monkeypatch,
        "geometry_msgs.msg",
        PoseStamped=object,
        PoseWithCovarianceStamped=object,
        TwistStamped=lambda: SimpleNamespace(
            header=SimpleNamespace(frame_id="", stamp=None),
            twist=SimpleNamespace(
                linear=SimpleNamespace(x=0.0),
                angular=SimpleNamespace(z=0.0),
            ),
        ),
    )
    _module(monkeypatch, "lifecycle_msgs")
    _module(monkeypatch, "lifecycle_msgs.srv", GetState=object)
    _module(monkeypatch, "nav2_simple_commander")
    _module(monkeypatch, "nav2_simple_commander.robot_navigator", BasicNavigator=object, TaskResult=SimpleNamespace(SUCCEEDED=1))
    _module(monkeypatch, "sensor_msgs")
    _module(monkeypatch, "sensor_msgs.msg", BatteryState=object, CompressedImage=object, LaserScan=object)
    _module(monkeypatch, "std_msgs")
    _module(monkeypatch, "std_msgs.msg", Bool=object, String=object)
    _module(monkeypatch, "std_srvs")
    _module(monkeypatch, "std_srvs.srv", Empty=object)
    spec = importlib.util.spec_from_file_location(
        "freshness_navigator",
        ROOT / "nav_app" / "services" / "logistics_navigator.py",
    )
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


def _vision_navigator(cls):
    navigator = cls.__new__(cls)
    navigator.aruco_detection_topic = "/mission/tb3_2/aruco/detections"
    navigator.latest_aruco_detections = {}
    navigator.latest_aruco_detections_by_transport = {}
    navigator.latest_aruco_payload = None
    navigator.latest_aruco_receipt_monotonic = 0.0
    navigator.latest_aruco_source_stamp_sec = None
    navigator.aruco_lock = threading.Lock()
    navigator.aruco_observation_config = {
        "transport": "vision_http",
        "api_base_url": "http://smartfactory-vision.local:8100",
        "source": "tb3_2_picam",
        "poll_interval_sec": 0.1,
        "request_timeout_sec": 0.3,
        "limit": 20,
    }
    navigator.aruco_observation_poll_lock = threading.Lock()
    navigator.aruco_observation_last_poll_monotonic = 0.0
    navigator.aruco_observation_last_success_monotonic = 0.0
    navigator.aruco_observation_last_error = None
    navigator.aruco_observation_last_error_log_monotonic = 0.0
    navigator.get_logger = lambda: SimpleNamespace(warning=lambda *_args: None)
    return navigator


def _vision_payload(*, observed_at=None):
    observed_at = time.time() if observed_at is None else float(observed_at)
    sec = int(observed_at)
    return {
        "source_header_stamp": {
            "sec": sec,
            "nanosec": int((observed_at - sec) * 1e9),
        },
        "transport": "vision_http",
        "source": "tb3_2_picam",
        "detections": [
            {
                "marker_id": 4,
                "center_px": [160.0, 120.0],
                "center_error_norm": 0.0,
                "marker_width_px": 120.0,
                "image_width": 320,
                "image_height": 240,
            }
        ],
    }


def test_marker_specific_read_polls_profile_vision_api_but_generic_health_does_not(
    navigator_class, monkeypatch
):
    navigator = _vision_navigator(navigator_class)
    calls = []

    def _fetch(**kwargs):
        calls.append(kwargs)
        return _vision_payload()

    monkeypatch.setitem(
        navigator_class._refresh_vision_aruco.__globals__,
        "fetch_detector_payload",
        _fetch,
    )

    assert navigator.get_latest_aruco_detection(max_age_sec=1.0) == []
    assert calls == []

    detection = navigator.get_latest_aruco_detection(4, max_age_sec=1.0)
    assert detection["marker_id"] == 4
    assert detection["transport"] == "vision_http"
    assert calls == [
        {
            "api_base_url": "http://smartfactory-vision.local:8100",
            "source": "tb3_2_picam",
            "limit": 20,
            "timeout_sec": 0.3,
        }
    ]

    # The 100 ms profile throttle prevents a docking loop from flooding AI.
    assert navigator.get_latest_aruco_detection(4, max_age_sec=1.0)
    assert len(calls) == 1


def test_vision_http_receipt_cannot_make_an_old_ai_event_fresh(
    navigator_class, monkeypatch
):
    navigator = _vision_navigator(navigator_class)
    monkeypatch.setitem(
        navigator_class._refresh_vision_aruco.__globals__,
        "fetch_detector_payload",
        lambda **_kwargs: _vision_payload(observed_at=time.time() - 10.0),
    )

    assert navigator.get_latest_aruco_detection(4, max_age_sec=1.0) is None


def test_primary_http_alignment_and_dock_ros_distance_are_transport_isolated(
    navigator_class, monkeypatch
):
    navigator = _vision_navigator(navigator_class)
    observed_at = time.time()
    sec = int(observed_at)
    navigator._record_aruco_payload(
        {
            "source_header_stamp": {
                "sec": sec,
                "nanosec": int((observed_at - sec) * 1e9),
            },
            "detections": [
                {
                    "marker_id": 4,
                    "center_error_norm": 0.01,
                    "marker_width_px": 80.0,
                    "forward_distance_m": 0.31,
                }
            ],
        },
        transport="ros_topic",
    )
    monkeypatch.setitem(
        navigator_class._refresh_vision_aruco.__globals__,
        "fetch_detector_payload",
        lambda **_kwargs: _vision_payload(observed_at=observed_at),
    )

    alignment = navigator.get_latest_aruco_detection(4, max_age_sec=1.0)
    distance = navigator.get_latest_aruco_detection(
        4, max_age_sec=1.0, transport="ros_topic"
    )

    assert alignment["transport"] == "vision_http"
    assert "forward_distance_m" not in alignment
    assert distance["transport"] == "ros_topic"
    assert distance["forward_distance_m"] == pytest.approx(0.31)


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


def test_stale_localization_requests_one_nomotion_refresh_before_motion(
    navigator_class, monkeypatch
):
    now = time.time()
    navigator, _ = _navigator(navigator_class, scan_stamp=now, tf_stamp=now)
    navigator.last_pose["receipt_monotonic"] = time.monotonic() - 3.0
    navigator.external_spin = True
    calls = []

    class _Future:
        @staticmethod
        def done():
            return True

        @staticmethod
        def result():
            return object()

    class _Client:
        @staticmethod
        def wait_for_service(timeout_sec):
            return timeout_sec > 0.0

        @staticmethod
        def call_async(_request):
            calls.append(True)
            refreshed = time.time()
            with navigator.last_pose_lock:
                navigator.last_pose["receipt_monotonic"] = time.monotonic()
                navigator.last_pose["stamp"] = {
                    "sec": int(refreshed),
                    "nanosec": int((refreshed % 1.0) * 1e9),
                }
            return _Future()

    navigator.request_nomotion_update_client = _Client()
    monkeypatch.setitem(
        navigator_class.refresh_localization_pose.__globals__,
        "Empty",
        SimpleNamespace(Request=lambda: object()),
    )

    health = navigator.docking_sensor_freshness(
        require_aruco=True, max_tf_age_sec=1.0
    )

    assert health["ok"] is True
    assert health["reason"] == "ok"
    assert health["localization_refreshed"] is True
    assert calls == [True]


def test_nomotion_refresh_rechecks_scan_before_motion(navigator_class, monkeypatch):
    now = time.time()
    navigator, _ = _navigator(navigator_class, scan_stamp=now, tf_stamp=now)
    navigator.last_pose["receipt_monotonic"] = time.monotonic() - 3.0
    navigator.external_spin = True

    class _Future:
        @staticmethod
        def done():
            return True

        @staticmethod
        def result():
            return object()

    class _Client:
        @staticmethod
        def wait_for_service(timeout_sec):
            return timeout_sec > 0.0

        @staticmethod
        def call_async(_request):
            refreshed = time.time()
            with navigator.last_pose_lock:
                navigator.last_pose["receipt_monotonic"] = time.monotonic()
                navigator.last_pose["stamp"] = {
                    "sec": int(refreshed),
                    "nanosec": int((refreshed % 1.0) * 1e9),
                }
            navigator.latest_scan_monotonic = time.monotonic() - 3.0
            navigator.latest_scan_header_stamp_sec = time.time() - 3.0
            return _Future()

    navigator.request_nomotion_update_client = _Client()
    monkeypatch.setitem(
        navigator_class.refresh_localization_pose.__globals__,
        "Empty",
        SimpleNamespace(Request=lambda: object()),
    )

    health = navigator.docking_sensor_freshness(
        require_aruco=True, max_scan_age_sec=1.0, max_tf_age_sec=1.0
    )

    assert health["ok"] is False
    assert health["reason"] == "scan_stale"
    assert health["localization_refreshed"] is True


def test_mapwide_only_matcher_reports_initial_match_scope(navigator_class):
    navigator = navigator_class.__new__(navigator_class)

    result = navigator._localization_alignment_observation_locked(
        {
            "localization": {
                "global_search": {"map_wide_scan_matching": True},
                "scan_map_alignment": {"enabled": False},
            }
        }
    )

    assert result == {
        "accepted": True,
        "refinement_required": False,
        "reason": "initial_match_only",
        "attempts": 0,
    }


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
    assert pose["age_sec"] == 0.0
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


def test_initial_pose_uses_latest_tf_instead_of_future_dated_stamp(navigator_class, monkeypatch):
    class Header:
        def __init__(self):
            self.frame_id = ""
            self.stamp = SimpleNamespace(sec=0, nanosec=0)

    class Pose:
        def __init__(self):
            self.position = SimpleNamespace(x=0.0, y=0.0)
            self.orientation = SimpleNamespace(z=0.0, w=0.0)

    class PoseStamped:
        def __init__(self):
            self.header = Header()
            self.pose = Pose()

    class PoseWithCovarianceStamped:
        def __init__(self):
            self.header = Header()
            self.pose = SimpleNamespace(pose=Pose(), covariance=[0.0] * 36)

    monkeypatch.setitem(navigator_class.set_initial_pose.__globals__, "PoseStamped", PoseStamped)
    monkeypatch.setitem(
        navigator_class.set_initial_pose.__globals__,
        "PoseWithCovarianceStamped",
        PoseWithCovarianceStamped,
    )
    navigator = navigator_class.__new__(navigator_class)
    navigator.nav = SimpleNamespace(setInitialPose=Mock())
    navigator.initial_pose_pub = SimpleNamespace(publish=Mock())

    navigator.set_initial_pose({"x": 1.0, "y": 2.0, "yaw": 0.1})

    message = navigator.initial_pose_pub.publish.call_args.args[0]
    navigator.nav.setInitialPose.assert_not_called()
    assert (message.header.stamp.sec, message.header.stamp.nanosec) == (0, 0)
    assert navigator._pose_from_transform() is None
    assert navigator.latest_tf_continuous is False


def _alignment_profile(*, interval_sec=1.0):
    return {
        "active_map_yaml": "/tmp/test-map.yaml",
        "localization": {
            "scan_map_alignment": {
                "enabled": True,
                "continuous_check_interval_sec": interval_sec,
            }
        },
    }


def _alignment_navigator(cls, *, scan_token=10.0):
    navigator = cls.__new__(cls)
    navigator.scan_lock = threading.Lock()
    navigator.scan_map_alignment_lock = threading.RLock()
    navigator.latest_scan = SimpleNamespace(
        header=SimpleNamespace(
            frame_id="base_scan",
            stamp=SimpleNamespace(sec=int(time.time()), nanosec=0),
        ),
        ranges=[1.0],
        angle_min=0.0,
        angle_increment=1.0,
        range_min=0.1,
        range_max=3.0,
    )
    navigator.latest_scan_monotonic = scan_token
    navigator.latest_scan_header_stamp_sec = time.time()
    navigator.scan_map_alignment_status = {
        "accepted": False,
        "refinement_required": False,
        "reason": "not_checked",
        "attempts": 0,
        "confirmation_count": 0,
    }
    navigator._pose_at_scan_stamp = lambda _scan: {"x": 0.0, "y": 0.0, "yaw": 0.0}
    navigator._scan_mount = lambda *_args: {"x": 0.0, "y": 0.0, "yaw": 0.0}
    return navigator


def test_pending_scan_map_alignment_is_throttled_between_intervals(navigator_class, monkeypatch):
    navigator = _alignment_navigator(navigator_class, scan_token=10.5)
    navigator.scan_map_alignment_status = {
        "accepted": False,
        "refinement_required": False,
        "reason": "confirmation_pending",
        "attempts": 0,
        "confirmation_count": 2,
        "last_confirmation_scan_token": 10.0,
    }
    module_globals = navigator_class.localization_alignment_observation.__globals__
    matcher = Mock(side_effect=AssertionError("matcher must remain cached inside the interval"))
    monkeypatch.setitem(module_globals, "align_scan_to_map", matcher)

    status = navigator.localization_alignment_observation(_alignment_profile(interval_sec=1.0))

    assert status["reason"] == "confirmation_pending"
    assert status["confirmation_count"] == 2
    matcher.assert_not_called()


def test_concurrent_alignment_queries_compute_one_scan_once(navigator_class, monkeypatch):
    navigator = _alignment_navigator(navigator_class, scan_token=20.0)
    module_globals = navigator_class.localization_alignment_observation.__globals__
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def align_once(**_kwargs):
        calls.append(time.monotonic())
        entered.set()
        assert release.wait(2.0)
        return {
            "accepted": True,
            "refinement_required": False,
            "reason": "aligned",
            "attempts": 0,
            "correction": {"x": 0.0, "y": 0.0, "yaw": 0.0},
            "corrected_pose": {"x": 0.0, "y": 0.0, "yaw": 0.0},
        }

    monkeypatch.setitem(module_globals, "align_scan_to_map", align_once)
    results = []
    first = threading.Thread(
        target=lambda: results.append(
            navigator.localization_alignment_observation(_alignment_profile())
        )
    )
    second = threading.Thread(
        target=lambda: results.append(
            navigator.localization_alignment_observation(_alignment_profile())
        )
    )

    first.start()
    assert entered.wait(1.0)
    second.start()
    time.sleep(0.05)
    assert len(calls) == 1
    release.set()
    first.join(timeout=2.0)
    second.join(timeout=2.0)

    assert not first.is_alive() and not second.is_alive()
    assert len(calls) == 1
    assert len(results) == 2
    assert all(result["confirmation_count"] == 1 for result in results)


def test_scan_alignment_uses_pose_at_scan_timestamp(navigator_class, monkeypatch):
    stamp = SimpleNamespace(sec=123, nanosec=456)
    scan = SimpleNamespace(header=SimpleNamespace(frame_id="base_scan", stamp=stamp))
    transform = SimpleNamespace(
        transform=SimpleNamespace(
            translation=SimpleNamespace(x=1.0, y=2.0),
            rotation=SimpleNamespace(x=0.0, y=0.0, z=0.0, w=1.0),
        )
    )
    calls = []
    navigator = navigator_class.__new__(navigator_class)
    navigator.tf_buffer = SimpleNamespace(
        lookup_transform=lambda *args, **kwargs: calls.append((args, kwargs)) or transform
    )
    monkeypatch.setitem(
        navigator_class._pose_at_scan_stamp.__globals__,
        "Time",
        SimpleNamespace(from_msg=lambda value: ("scan-time", value)),
    )

    pose = navigator._pose_at_scan_stamp(scan)

    assert pose == {"x": 1.0, "y": 2.0, "yaw": 0.0}
    assert calls[0][0][2] == ("scan-time", stamp)


def test_temporal_pair_gap_retains_recent_accepted_alignment(navigator_class):
    navigator = _alignment_navigator(navigator_class, scan_token=11.0)
    navigator.scan_map_alignment_status = {
        "accepted": True,
        "refinement_required": False,
        "reason": "aligned",
        "attempts": 0,
        "last_confirmation_scan_token": 10.0,
    }
    navigator._pose_at_scan_stamp = lambda _scan: None

    status = navigator.localization_alignment_observation(_alignment_profile(interval_sec=1.0))

    assert status["accepted"] is True
    assert status["reason"] == "aligned"
    assert status["temporal_pair_pending"] is True
    assert status["deferred_reason"] == "scan_transform_pair_unavailable"


def test_temporal_pair_gap_without_recent_admission_stays_pending(navigator_class):
    navigator = _alignment_navigator(navigator_class, scan_token=20.0)
    navigator._pose_at_scan_stamp = lambda _scan: None

    status = navigator.localization_alignment_observation(_alignment_profile(interval_sec=1.0))

    assert status["accepted"] is False
    assert status["refinement_required"] is False
    assert status["reason"] == "temporal_pair_pending"


def test_nav2_readiness_monitor_starts_only_one_background_check(navigator_class):
    navigator = navigator_class.__new__(navigator_class)
    navigator.nav2_ready = False
    navigator.nav2_readiness_start_lock = threading.Lock()
    navigator.nav2_readiness_thread = None
    entered = threading.Event()
    release = threading.Event()
    calls = []

    def monitor_loop():
        calls.append(time.monotonic())
        entered.set()
        assert release.wait(2.0)

    navigator._nav2_readiness_monitor_loop = monitor_loop

    first = navigator.start_nav2_readiness_monitor()
    assert entered.wait(1.0)
    second = navigator.start_nav2_readiness_monitor()
    assert first is second
    assert len(calls) == 1

    release.set()
    first.join(timeout=2.0)
    assert not first.is_alive()


def test_nav2_liveness_expires_a_stale_success(navigator_class, monkeypatch):
    navigator = navigator_class.__new__(navigator_class)
    navigator.nav2_ready = True
    navigator.nav2_last_probe_monotonic = 10.0
    navigator.nav2_liveness_max_age_sec = 3.0
    monkeypatch.setattr(time, "monotonic", lambda: 14.1)

    assert navigator.nav2_liveness() is False


def test_nav2_liveness_refresh_tracks_lifecycle_loss(navigator_class, monkeypatch):
    navigator = navigator_class.__new__(navigator_class)
    navigator.nav2_ready = True
    navigator.nav2_ready_lock = threading.Lock()
    navigator.nav2_last_probe_monotonic = 0.0
    navigator.nav2_liveness_reason = "not_checked"
    navigator._probe_lifecycle_active = Mock(
        side_effect=[
            (True, "active"),
            (True, "active"),
            (True, "active"),
            (False, "service_unavailable"),
        ]
    )
    clock = iter((20.0, 22.0))
    monkeypatch.setattr(time, "monotonic", lambda: next(clock))

    assert navigator.refresh_nav2_liveness() is True
    assert navigator.nav2_liveness_reason == "active"
    assert navigator.refresh_nav2_liveness() is False
    assert navigator.nav2_ready is False
    assert navigator.nav2_liveness_reason == "bt_navigator_service_unavailable"


def test_nav2_readiness_does_not_publish_a_default_amcl_initial_pose(
    navigator_class, monkeypatch
):
    """Lifecycle readiness must not seed AMCL with BasicNavigator's zero pose."""
    navigator = navigator_class.__new__(navigator_class)
    navigator.nav2_ready = False
    navigator.nav2_ready_lock = threading.Lock()
    navigator.last_nav_failure = None
    navigator.nav = SimpleNamespace(waitUntilNav2Active=Mock())
    navigator._wait_for_lifecycle_active = Mock(side_effect=[True, True])
    navigator.get_logger = lambda: SimpleNamespace(info=Mock(), error=Mock())
    monkeypatch.setenv("SIMULATION_MODE", "0")
    monkeypatch.delenv("NAV2_SKIP_ACTIVE_WAIT", raising=False)
    monkeypatch.setenv("NAV2_LOCALIZER", "amcl")

    assert navigator.ensure_nav2_ready() is True

    # The application owns localization. Readiness checks lifecycle services
    # directly, so it neither publishes BasicNavigator's default (0, 0) pose
    # nor wedges on an in-flight request when an external Nav2 process restarts.
    assert navigator._wait_for_lifecycle_active.call_args_list == [
        (("amcl",),),
        (("bt_navigator",),),
    ]
    navigator.nav.waitUntilNav2Active.assert_not_called()


def test_nav2_readiness_fails_closed_when_a_lifecycle_node_is_unavailable(
    navigator_class, monkeypatch
):
    navigator = navigator_class.__new__(navigator_class)
    navigator.nav2_ready = False
    navigator.nav2_ready_lock = threading.Lock()
    navigator.last_nav_failure = None
    navigator._wait_for_lifecycle_active = Mock(side_effect=[True, False])
    navigator.get_logger = lambda: SimpleNamespace(info=Mock(), error=Mock())
    monkeypatch.setenv("SIMULATION_MODE", "0")
    monkeypatch.delenv("NAV2_SKIP_ACTIVE_WAIT", raising=False)

    assert navigator.ensure_nav2_ready() is False
    assert navigator.nav2_ready is False
    assert navigator.last_nav_failure == "bt_navigator lifecycle is not active"


def test_distance_drive_stops_from_measured_feedback(navigator_class):
    navigator = navigator_class.__new__(navigator_class)
    navigator.safety = SimpleNamespace(estop=False)
    navigator.status = "IDLE"
    navigator.manual_stop_event = threading.Event()
    navigator.cmd_vel_pub = Mock()
    navigator._publish_stop_velocity = Mock()

    def transform(x: float):
        return SimpleNamespace(transform=SimpleNamespace(
            translation=SimpleNamespace(x=x, y=0.0),
        ))

    navigator.tf_buffer = Mock()
    navigator.tf_buffer.lookup_transform.side_effect = [transform(0.0), transform(0.205)]

    result = navigator.publish_velocity_for_distance(
        linear_x=-0.05,
        distance_m=0.20,
        max_duration_sec=1.0,
        tolerance_m=0.005,
    )

    assert result["ok"] is True
    assert result["reason"] == "distance_reached"
    assert result["distance_m"] == pytest.approx(0.205)
    navigator._publish_stop_velocity.assert_called_once()
