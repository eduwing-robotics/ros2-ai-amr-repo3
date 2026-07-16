from collections import deque
import math
import time
from threading import Event, Lock, Thread as RealThread
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import logistics_navigator as navigator_module
from logistics_navigator import LogisticsNavigator


def navigator_stub():
    navigator = LogisticsNavigator.__new__(LogisticsNavigator)
    navigator.global_localization_client = MagicMock()
    navigator.global_localization_client.wait_for_service.return_value = True
    navigator.global_localization_client.call_async.return_value = MagicMock()
    navigator.request_nomotion_update_client = MagicMock()
    navigator.request_nomotion_update_client.wait_for_service.return_value = True
    future = MagicMock()
    future.done.return_value = True
    future.result.return_value = object()
    navigator.request_nomotion_update_client.call_async.return_value = future
    navigator.last_nav_failure = None
    navigator.global_localization_lock = __import__("threading").Lock()
    navigator.scan_map_alignment_lock = __import__("threading").RLock()
    navigator.global_localization_stop_event = Event()
    navigator.global_localization_thread = None
    navigator.global_localization_status = {}
    navigator.publish_velocity_for_duration = MagicMock()
    navigator._publish_stop_velocity = MagicMock()
    navigator._wait_for_future = MagicMock(return_value=object())
    navigator._wait_for_new_amcl_sample = MagicMock(return_value=True)
    navigator._global_search_pose_converged = MagicMock(return_value=False)
    navigator.localization_observation = MagicMock(return_value={
        "amcl": {},
        "scan_age_sec": 99.0,
        "tf_age_sec": 99.0,
        "tf_continuous": False,
    })
    return navigator


def observation(receipt, *, covariance=None, x=0.0, y=0.0, yaw=0.0, scan_age=0.1, tf_age=0.1):
    return {
        "amcl": {
            "receipt_monotonic": receipt,
            "covariance": covariance or {"x": 0.1, "y": 0.1, "yaw": 0.1},
            "x": x,
            "y": y,
            "yaw": yaw,
        },
        "scan_age_sec": scan_age,
        "tf_age_sec": tf_age,
        "tf_continuous": True,
    }


def test_global_localization_is_observe_only_by_default():
    navigator = navigator_stub()

    result = navigator.request_global_localization()

    assert result["accepted"] is True
    assert result["strategy"] == "observe_only"
    assert result["motion_started"] is False
    navigator.publish_velocity_for_duration.assert_not_called()
    assert navigator.global_localization_thread is not None
    navigator.global_localization_stop_event.set()
    navigator.global_localization_thread.join(timeout=1.0)
    navigator._publish_stop_velocity.assert_not_called()


def test_map_wide_scan_search_seeds_before_amcl_global_sampling():
    navigator = navigator_stub()
    navigator._map_wide_scan_localization_search = MagicMock()

    result = navigator.request_global_localization({
        "strategy": "observe_only",
        "map_wide_scan_matching": True,
        "active_map_yaml": "map/robot2_map.yaml",
        "scan_map_alignment": {},
    })
    navigator.global_localization_thread.join(timeout=1.0)

    assert result["accepted"] is True
    assert result["reason"] == "map_wide_scan_search_started"
    navigator._map_wide_scan_localization_search.assert_called_once()
    navigator.global_localization_client.call_async.assert_not_called()
    navigator.publish_velocity_for_duration.assert_not_called()


def test_map_wide_worker_seeds_only_repeated_top_k_hypothesis(monkeypatch):
    navigator = navigator_stub()
    navigator.scan_lock = Lock()
    navigator.latest_scan = SimpleNamespace(
        ranges=[1.0] * 40,
        angle_min=-1.0,
        angle_increment=0.05,
        range_min=0.05,
        range_max=3.5,
    )
    navigator.latest_scan_monotonic = 1.0
    navigator._scan_mount = MagicMock(return_value={"x": 0.0, "y": 0.0, "yaw": 0.0})
    navigator.set_initial_pose = MagicMock(return_value={})
    navigator.reset_scan_map_alignment = MagicMock()
    navigator._observe_only_localization_search = MagicMock()
    correct = {"x": 0.42, "y": -0.92, "yaw": math.radians(39.0)}
    distractors = [
        {"x": 1.2, "y": 0.1, "yaw": -1.0},
        {"x": -0.8, "y": 0.7, "yaw": 2.1},
        {"x": 0.3, "y": 1.1, "yaw": -2.5},
    ]
    call_count = 0

    def candidate(pose, loss):
        return {
            "absolute_pose": dict(pose),
            "score": {
                "mean_distance_m": loss,
                "match_ratio": 0.92,
                "segment_mismatch_m": 0.005,
            },
        }

    def global_match(**_kwargs):
        nonlocal call_count
        index = call_count
        call_count += 1
        navigator.latest_scan_monotonic += 1.0
        repeated = {
            **correct,
            "x": correct["x"] + (index - 1) * 0.01,
            "yaw": correct["yaw"] + math.radians(index - 1) * 0.4,
        }
        ranked = [candidate(distractors[index], 0.007), candidate(repeated, 0.010)]
        if index == 1:
            ranked.reverse()
        return {
            "accepted": False,
            "reason": "global_match_ambiguous",
            "candidates": ranked,
        }

    monkeypatch.setattr(navigator_module, "global_align_scan_to_map", global_match)

    navigator._map_wide_scan_localization_search({
        "active_map_yaml": "map/robot2_map.yaml",
        "nomotion_update_timeout_sec": 10.0,
        "map_wide_confirmation_scans": 3,
        "map_wide_confirmation_window_scans": 5,
        "scan_map_alignment": {},
    })

    assert call_count == 3
    navigator.set_initial_pose.assert_called_once()
    seeded = navigator.set_initial_pose.call_args.args[0]
    assert seeded["x"] == pytest.approx(correct["x"], abs=0.01)
    assert seeded["y"] == pytest.approx(correct["y"], abs=0.01)
    assert seeded["yaw"] == pytest.approx(correct["yaw"], abs=math.radians(0.5))
    navigator._observe_only_localization_search.assert_called_once()
    fine_search = navigator._observe_only_localization_search.call_args.args[0]
    assert fine_search["_overall_deadline_monotonic"] > time.monotonic()


def test_fine_search_honors_map_wide_overall_deadline():
    navigator = navigator_stub()

    navigator._observe_only_localization_search({
        "coarse_nomotion_interval_sec": 0.01,
        "fine_nomotion_interval_sec": 0.01,
        "nomotion_update_timeout_sec": 0.1,
        "_overall_deadline_monotonic": time.monotonic() - 0.01,
        "start_stage": "fine",
    })

    navigator.request_nomotion_update_client.call_async.assert_not_called()
    assert navigator.global_localization_status["reason"] == "nomotion_update_timeout"
    assert navigator.last_nav_failure == "LOCALIZATION_FAILED"


def test_new_global_search_discards_previous_pose_and_tf_generation():
    navigator = navigator_stub()
    navigator.tf_buffer = MagicMock()
    navigator.last_pose_lock = Lock()
    navigator.last_pose = {"x": 9.0, "y": 9.0, "yaw": 1.0}
    navigator.amcl_pose_history = deque([navigator.last_pose], maxlen=10)
    navigator.latest_tf_monotonic = 123.0
    navigator.latest_tf_header_stamp_sec = 456.0
    navigator.latest_tf_continuous = True

    navigator._reset_global_localization_observations()

    navigator.tf_buffer.clear.assert_called_once_with()
    assert navigator.last_pose is None
    assert list(navigator.amcl_pose_history) == []
    assert navigator.latest_tf_monotonic == 0.0
    assert navigator.latest_tf_header_stamp_sec is None
    assert navigator.latest_tf_continuous is False


def test_observe_only_repeats_nomotion_updates_without_cmd_vel():
    navigator = navigator_stub()

    result = navigator.request_global_localization(
        {"strategy": "observe_only", "nomotion_update_interval_sec": 0.01, "nomotion_update_timeout_sec": 0.04}
    )
    navigator.global_localization_thread.join(timeout=1.0)

    assert result["accepted"] is True
    assert navigator.request_nomotion_update_client.call_async.call_count >= 2
    navigator.publish_velocity_for_duration.assert_not_called()
    navigator._publish_stop_velocity.assert_not_called()
    assert navigator.global_localization_status["reason"] == "nomotion_update_timeout"


def test_nomotion_loop_waits_for_a_new_amcl_sample_after_each_request():
    navigator = navigator_stub()
    calls = 0

    def fresh_after_one_retry(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return calls > 1

    navigator._wait_for_new_amcl_sample.side_effect = fresh_after_one_retry

    navigator.request_global_localization(
        {"strategy": "observe_only", "nomotion_update_interval_sec": 0.01, "nomotion_update_timeout_sec": 0.04}
    )
    navigator.global_localization_thread.join(timeout=1.0)

    assert navigator.request_nomotion_update_client.call_async.call_count >= 2
    assert navigator._wait_for_new_amcl_sample.call_count >= 2
    navigator.publish_velocity_for_duration.assert_not_called()


def test_observe_only_fails_closed_when_nomotion_service_is_missing():
    navigator = navigator_stub()
    navigator.request_nomotion_update_client.wait_for_service.return_value = False

    result = navigator.request_global_localization()

    assert result["accepted"] is False
    assert result["reason"] == "nomotion_update_service_unavailable"
    navigator.global_localization_client.call_async.assert_not_called()
    navigator._publish_stop_velocity.assert_not_called()


def test_motion_requires_explicit_permission():
    navigator = navigator_stub()

    result = navigator.request_global_localization(
        {"strategy": "bounded_linear_wiggle", "allow_motion": False}
    )

    assert result["accepted"] is False
    assert result["reason"] == "motion_permission_required"
    assert navigator.global_localization_thread is None


def test_rotation_strategy_is_not_supported():
    navigator = navigator_stub()

    result = navigator.request_global_localization(
        {"strategy": "rotate", "allow_motion": True}
    )

    assert result["accepted"] is False
    assert result["reason"] == "unsupported_strategy"


def test_repeated_search_does_not_resume_or_replace_still_running_motion():
    navigator = navigator_stub()
    previous = MagicMock()
    previous.is_alive.return_value = True
    navigator.global_localization_thread = previous

    result = navigator.request_global_localization(
        {"strategy": "bounded_linear_wiggle", "allow_motion": True}
    )

    assert result["accepted"] is False
    assert result["reason"] == "previous_search_still_stopping"
    assert navigator.global_localization_stop_event.is_set()
    navigator._publish_stop_velocity.assert_called_once_with()
    previous.join.assert_called_once_with(timeout=0.5)
    navigator.global_localization_client.call_async.assert_not_called()
    assert navigator.global_localization_thread is previous


def test_repeated_observe_only_request_keeps_the_active_search_running():
    navigator = navigator_stub()
    previous = MagicMock()
    previous.is_alive.return_value = True
    navigator.global_localization_thread = previous
    navigator.global_localization_status = {
        "accepted": True,
        "strategy": "observe_only",
        "motion_started": False,
        "reason": "map_wide_candidate_pending",
        "stage": "map_wide",
    }

    result = navigator.request_global_localization(
        {"strategy": "observe_only", "map_wide_scan_matching": True}
    )

    assert result["accepted"] is True
    assert result["reason"] == "search_already_active"
    assert result["stage"] == "map_wide"
    assert navigator.global_localization_stop_event.is_set() is False
    previous.join.assert_not_called()
    navigator.global_localization_client.call_async.assert_not_called()


def test_concurrent_bounded_requests_never_create_two_motion_workers(monkeypatch):
    navigator = navigator_stub()
    first_service_wait_entered = Event()
    allow_first_service_wait = Event()
    service_wait_calls = 0
    service_wait_lock = __import__("threading").Lock()

    def wait_for_service(*, timeout_sec):
        nonlocal service_wait_calls
        with service_wait_lock:
            service_wait_calls += 1
            call_number = service_wait_calls
        if call_number == 1:
            first_service_wait_entered.set()
            assert allow_first_service_wait.wait(timeout=1.0)
        return True

    navigator.global_localization_client.wait_for_service.side_effect = wait_for_service

    class FakeMotionThread:
        alive_count = 0
        max_alive_count = 0
        start_count = 0

        def __init__(self, **_kwargs):
            self.alive = False

        def start(self):
            self.alive = True
            type(self).start_count += 1
            type(self).alive_count += 1
            type(self).max_alive_count = max(type(self).max_alive_count, type(self).alive_count)

        def is_alive(self):
            return self.alive

        def join(self, timeout=None):
            if self.alive:
                self.alive = False
                type(self).alive_count -= 1

    monkeypatch.setattr(navigator_module, "threading", SimpleNamespace(Thread=FakeMotionThread))
    request = {"strategy": "bounded_linear_wiggle", "allow_motion": True}
    results = []
    first = RealThread(target=lambda: results.append(navigator.request_global_localization(request)))
    second = RealThread(target=lambda: results.append(navigator.request_global_localization(request)))

    first.start()
    assert first_service_wait_entered.wait(timeout=1.0)
    second.start()
    allow_first_service_wait.set()
    first.join(timeout=1.0)
    second.join(timeout=1.0)

    assert len(results) == 2
    assert sum(result["accepted"] for result in results) == 1
    assert {result["reason"] for result in results} == {
        "bounded_motion_started",
        "concurrent_search_already_active",
    }
    assert FakeMotionThread.start_count == 1
    assert FakeMotionThread.max_alive_count == 1
    assert navigator.global_localization_client.call_async.call_count == 1


def test_bounded_started_status_is_published_before_worker_start(monkeypatch):
    navigator = navigator_stub()

    class CompletingThread:
        def __init__(self, *, target, args, **_kwargs):
            self.target = target
            self.args = args

        def start(self):
            self.target(*self.args)

        def is_alive(self):
            return False

    navigator._bounded_linear_localization_search = MagicMock(
        side_effect=lambda _search: navigator._set_global_localization_status(
            True, "bounded_linear_wiggle", False, "motion_budget_exhausted"
        )
    )
    monkeypatch.setattr(navigator_module, "threading", SimpleNamespace(Thread=CompletingThread))

    result = navigator.request_global_localization(
        {"strategy": "bounded_linear_wiggle", "allow_motion": True}
    )

    assert result["reason"] == "bounded_motion_started"
    assert navigator.global_localization_status["reason"] == "motion_budget_exhausted"


def test_coarse_requires_three_distinct_stable_samples_before_fine():
    navigator = navigator_stub()
    samples = []
    outcomes = []
    for receipt in (1.0, 1.75, 2.5):
        navigator.localization_observation.return_value = observation(receipt)
        outcomes.append(navigator._global_search_stage_update({}, "coarse", samples))

    assert outcomes == ["awaiting_samples", "awaiting_samples", "converged"]
    assert len(samples) == 3


def test_duplicate_and_stale_samples_never_converge_or_reinitialize():
    navigator = navigator_stub()
    samples = []
    navigator.localization_observation.return_value = observation(1.0)
    assert navigator._global_search_stage_update({}, "coarse", samples) == "awaiting_samples"
    assert navigator._global_search_stage_update({}, "coarse", samples) == "duplicate_sample"
    navigator.localization_observation.return_value = observation(2.0, tf_age=2.0)
    assert navigator._global_search_stage_update({}, "coarse", samples) == "sensor_data_stale"
    assert navigator.global_localization_client.call_async.call_count == 0


def test_fine_gate_requires_ten_distinct_samples_and_three_seconds_stability():
    navigator = navigator_stub()
    samples = []
    outcomes = []
    for index in range(10):
        navigator.localization_observation.return_value = observation(10.0 + index / 3.0)
        outcomes.append(navigator._global_search_stage_update({}, "fine", samples))

    assert outcomes[-2] == "awaiting_samples"
    assert outcomes[-1] == "converged"


def test_bounded_fallback_reuses_fine_sample_window_until_converged():
    navigator = navigator_stub()
    samples = []
    outcomes = []
    for index in range(10):
        navigator.localization_observation.return_value = observation(10.0 + index / 3.0)
        outcomes.append(LogisticsNavigator._global_search_pose_converged(navigator, {}, samples))

    assert outcomes == [False] * 9 + [True]
    assert len(samples) == 10


def test_bounded_fallback_checks_convergence_before_motion_publish():
    navigator = navigator_stub()
    navigator.safety = MagicMock(estop=False)
    navigator.cmd_vel_pub = MagicMock()
    navigator._global_search_pose_converged.return_value = True

    result = navigator._bounded_linear_localization_search(
        {
            "linear_speed_mps": 0.04,
            "max_step_m": 0.05,
            "max_total_m": 0.2,
            "max_scan_age_sec": 1.0,
            "min_front_clearance_m": 0.6,
            "min_rear_clearance_m": 0.6,
        }
    )

    assert result["reason"] == "converged"
    navigator.cmd_vel_pub.publish.assert_not_called()
    navigator.publish_velocity_for_duration.assert_not_called()


def test_bounded_fallback_samples_during_motion_until_converged(monkeypatch):
    navigator = navigator_stub()
    navigator.safety = MagicMock(estop=False)
    navigator.cmd_vel_pub = MagicMock()
    navigator.front_min_range = MagicMock(return_value=1.0)
    navigator.rear_min_range = MagicMock(return_value=1.0)
    navigator.get_clock = MagicMock()
    navigator.get_clock.return_value.now.return_value.to_msg.return_value = MagicMock()
    navigator._global_search_pose_converged.side_effect = [False] * 9 + [True]
    clock = [0.0]
    monkeypatch.setattr(navigator_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(navigator_module.time, "sleep", lambda seconds: clock.__setitem__(0, clock[0] + seconds))

    result = navigator._bounded_linear_localization_search(
        {
            "linear_speed_mps": 0.04,
            "max_step_m": 0.05,
            "max_total_m": 0.2,
            "max_scan_age_sec": 1.0,
            "min_front_clearance_m": 0.6,
            "min_rear_clearance_m": 0.6,
            "fine_consecutive_samples": 10,
            "fine_stable_min_duration_sec": 3.0,
        }
    )

    assert result["reason"] == "converged"
    assert navigator._global_search_pose_converged.call_count == 10
    assert navigator.cmd_vel_pub.publish.call_count > 0
    assert navigator._publish_stop_velocity.call_count >= 1


def test_bounded_fallback_uses_the_open_direction_when_reverse_is_too_close(monkeypatch):
    navigator = navigator_stub()
    navigator.safety = MagicMock(estop=False)
    navigator.cmd_vel_pub = MagicMock()
    navigator.front_min_range = MagicMock(return_value=1.0)
    navigator.rear_min_range = MagicMock(return_value=0.5)
    navigator.get_clock = MagicMock()
    navigator.get_clock.return_value.now.return_value.to_msg.return_value = MagicMock()
    clock = [0.0]
    monkeypatch.setattr(navigator_module.time, "monotonic", lambda: clock[0])
    monkeypatch.setattr(
        navigator_module.time,
        "sleep",
        lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )

    result = navigator._bounded_linear_localization_search(
        {
            "linear_speed_mps": 0.04,
            "max_step_m": 0.05,
            "max_total_m": 0.1,
            "max_scan_age_sec": 1.0,
            "min_front_clearance_m": 0.6,
            "min_rear_clearance_m": 0.6,
        }
    )

    assert result["reason"] == "motion_budget_exhausted"
    assert result["moved_m"] == pytest.approx(0.1)
    assert navigator.cmd_vel_pub.publish.call_count > 0
    assert all(
        call.args[0].twist.linear.x > 0.0
        for call in navigator.cmd_vel_pub.publish.call_args_list
    )


def test_fine_covariance_breach_requests_hysteresis_fallback_without_motion():
    navigator = navigator_stub()
    navigator.localization_observation.return_value = observation(
        1.0,
        covariance={"x": 0.41, "y": 0.1, "yaw": 0.1},
    )

    assert navigator._global_search_stage_update({}, "fine", []) == "fine_breach"
    navigator.publish_velocity_for_duration.assert_not_called()
    navigator._publish_stop_velocity.assert_not_called()


def test_observe_only_loop_completes_coarse_to_fine_without_cmd_vel():
    navigator = navigator_stub()
    statuses = []
    original_set_status = navigator._set_global_localization_status
    navigator._set_global_localization_status = MagicMock(
        side_effect=lambda *args, **kwargs: statuses.append(original_set_status(*args, **kwargs)) or statuses[-1]
    )
    navigator._global_search_stage_update = MagicMock(side_effect=["converged", "converged"])

    navigator._observe_only_localization_search(
        {
            "coarse_nomotion_interval_sec": 0.01,
            "fine_nomotion_interval_sec": 0.01,
            "nomotion_update_timeout_sec": 0.1,
        }
    )

    assert [(item["reason"], item.get("stage")) for item in statuses] == [
        ("coarse_converged", "fine"),
        ("converged", "fine"),
    ]
    assert navigator.global_localization_status["reason"] == "converged"
    assert navigator.last_nav_failure is None
    navigator.publish_velocity_for_duration.assert_not_called()
    navigator._publish_stop_velocity.assert_not_called()


def test_stale_sensor_pause_does_not_consume_reinitialization_attempt():
    navigator = navigator_stub()
    navigator._global_search_stage_update = MagicMock(return_value="sensor_data_stale")

    navigator._observe_only_localization_search(
        {
            "coarse_nomotion_interval_sec": 0.01,
            "nomotion_update_timeout_sec": 0.04,
            "max_global_reinitializations": 2,
        }
    )

    navigator.global_localization_client.call_async.assert_not_called()
    assert navigator.global_localization_status["reason"] == "nomotion_update_timeout"
    assert navigator.last_nav_failure == "LOCALIZATION_FAILED"
    navigator.publish_velocity_for_duration.assert_not_called()
    navigator._publish_stop_velocity.assert_not_called()


def test_observe_only_uses_at_most_one_retry_after_initial_reinitialization():
    navigator = navigator_stub()
    navigator._global_search_stage_update = MagicMock(return_value="awaiting_covariance")

    navigator._observe_only_localization_search(
        {
            "coarse_nomotion_interval_sec": 0.01,
            "nomotion_update_timeout_sec": 0.05,
            "max_global_reinitializations": 2,
        }
    )

    # request_global_localization performs the initial call; this worker loop
    # may perform only one additional global reinitialization.
    navigator.global_localization_client.call_async.assert_called_once()
    assert navigator.global_localization_status["reason"] == "nomotion_update_timeout"
    navigator.publish_velocity_for_duration.assert_not_called()
    navigator._publish_stop_velocity.assert_not_called()


def test_three_consecutive_fine_breaches_fall_back_to_coarse():
    navigator = navigator_stub()
    statuses = []
    original_set_status = navigator._set_global_localization_status
    navigator._set_global_localization_status = MagicMock(
        side_effect=lambda *args, **kwargs: statuses.append(original_set_status(*args, **kwargs)) or statuses[-1]
    )
    outcomes = iter(["converged", "fine_breach", "fine_breach", "fine_breach"])

    def stage_update(*_args):
        try:
            return next(outcomes)
        except StopIteration:
            navigator.global_localization_stop_event.set()
            return "sensor_data_stale"

    navigator._global_search_stage_update = MagicMock(side_effect=stage_update)

    navigator._observe_only_localization_search(
        {
            "coarse_nomotion_interval_sec": 0.01,
            "fine_nomotion_interval_sec": 0.01,
            "nomotion_update_timeout_sec": 0.2,
            "fine_fallback_breaches": 3,
        }
    )

    assert [item["reason"] for item in statuses].count("fine_fallback_to_coarse") == 1
    fallback = next(item for item in statuses if item["reason"] == "fine_fallback_to_coarse")
    assert fallback["stage"] == "coarse"
    navigator.publish_velocity_for_duration.assert_not_called()
    navigator._publish_stop_velocity.assert_not_called()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("scan_age_sec", -0.1),
        ("scan_age_sec", float("nan")),
        ("tf_age_sec", float("inf")),
    ],
)
def test_nonfinite_or_negative_sensor_age_never_converges(field, value):
    navigator = navigator_stub()
    samples = []
    current = observation(1.0)
    current[field] = value
    navigator.localization_observation.return_value = current

    assert navigator._global_search_stage_update({}, "coarse", samples) == "sensor_data_stale"
    assert samples == []


@pytest.mark.parametrize(
    "amcl_update",
    [
        {"covariance": {"x": float("nan"), "y": 0.1, "yaw": 0.1}},
        {"covariance": {"x": -0.1, "y": 0.1, "yaw": 0.1}},
        {"x": float("inf")},
        {"receipt_monotonic": float("nan")},
    ],
)
def test_invalid_amcl_sample_resets_progress_and_never_converges(amcl_update):
    navigator = navigator_stub()
    samples = [(0.0, 0.0, 0.0, 0.0), (0.5, 0.0, 0.0, 0.0)]
    current = observation(1.0)
    current["amcl"] = {**current["amcl"], **amcl_update}
    navigator.localization_observation.return_value = current

    assert navigator._global_search_stage_update({}, "coarse", samples) != "converged"
    assert samples == []
