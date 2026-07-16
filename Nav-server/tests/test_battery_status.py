import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from nav_app.runtime import runtime
from nav_app.services import robot_context


def test_opencr_sensor_voltage_updates_battery_snapshot():
    from logistics_navigator import LogisticsNavigator

    navigator = object.__new__(LogisticsNavigator)
    navigator.battery_level = None
    navigator.battery_voltage = None
    navigator.battery_received_monotonic = None
    navigator.battery_sampled_at = None
    navigator.battery_lock = threading.Lock()

    LogisticsNavigator._sensor_state_callback(navigator, SimpleNamespace(battery=11.7))
    snapshot = LogisticsNavigator.get_battery_snapshot(navigator)

    assert snapshot["battery_voltage"] == pytest.approx(11.7)
    assert snapshot["battery"] == pytest.approx(50.0)
    assert snapshot["battery_received_monotonic"] is not None
    assert snapshot["battery_sampled_at"].endswith("+00:00")



@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1.0])
def test_opencr_invalid_voltage_clears_battery(value):
    from logistics_navigator import LogisticsNavigator

    navigator = object.__new__(LogisticsNavigator)
    navigator.battery_level = 75.0
    navigator.battery_voltage = 12.0
    navigator.battery_received_monotonic = None
    navigator.battery_sampled_at = None
    navigator.battery_lock = threading.Lock()

    LogisticsNavigator._sensor_state_callback(navigator, SimpleNamespace(battery=value))

    assert LogisticsNavigator.get_battery_snapshot(navigator)["battery"] is None


@pytest.mark.parametrize(
    ("percent", "age_sec", "expected"),
    [(58.4, 0.1, 58), (58.5, 0.1, 59), (-5.0, 0.1, 0), (105.0, 0.1, 100), (58.0, 5.1, None)],
)
def test_current_battery_percent_contract(monkeypatch, percent, age_sec, expected):
    navigator = MagicMock()
    navigator.get_battery_snapshot.return_value = {
        "battery": percent,
        "battery_received_monotonic": time.monotonic() - age_sec,
    }
    monkeypatch.setattr(runtime, "navigator", navigator)

    result = robot_context.current_battery_percent()

    assert result == expected
    assert result is None or isinstance(result, int)



def test_opencr_median_rejects_single_voltage_spike():
    from logistics_navigator import LogisticsNavigator

    navigator = object.__new__(LogisticsNavigator)
    navigator.battery_level = None
    navigator.battery_voltage = None
    navigator.battery_received_monotonic = None
    navigator.battery_sampled_at = None
    navigator.battery_lock = threading.Lock()
    for voltage in (11.7, 11.7, 11.7, 12.6):
        LogisticsNavigator._sensor_state_callback(navigator, SimpleNamespace(battery=voltage))

    snapshot = LogisticsNavigator.get_battery_snapshot(navigator)
    assert snapshot["battery_voltage"] == pytest.approx(11.7)
    assert snapshot["battery"] == pytest.approx(50.0)
    assert snapshot["battery_source"] == "sensor_state"


def test_battery_state_does_not_override_fresh_sensor_state():
    from logistics_navigator import LogisticsNavigator

    navigator = object.__new__(LogisticsNavigator)
    navigator.battery_level = None
    navigator.battery_voltage = None
    navigator.battery_received_monotonic = None
    navigator.battery_sampled_at = None
    navigator.battery_lock = threading.Lock()
    LogisticsNavigator._sensor_state_callback(navigator, SimpleNamespace(battery=11.7))
    LogisticsNavigator._battery_callback(navigator, SimpleNamespace(percentage=0.9, voltage=12.5))

    snapshot = LogisticsNavigator.get_battery_snapshot(navigator)
    assert snapshot["battery"] == pytest.approx(50.0)
    assert snapshot["battery_source"] == "sensor_state"


def test_battery_slew_limits_large_changes():
    from logistics_navigator import LogisticsNavigator

    navigator = object.__new__(LogisticsNavigator)
    navigator.battery_level = 50.0
    navigator.battery_voltage = 11.7
    navigator.battery_received_monotonic = None
    navigator.battery_sampled_at = None
    navigator.battery_source = None
    navigator.battery_lock = threading.Lock()
    LogisticsNavigator._record_battery_sample(navigator, percentage=80.0, voltage=12.2, source="sensor_state")
    assert navigator.battery_level == pytest.approx(51.0)
    LogisticsNavigator._record_battery_sample(navigator, percentage=10.0, voltage=11.0, source="sensor_state")
    assert navigator.battery_level == pytest.approx(48.0)


def test_current_battery_percent_is_none_before_first_sample(monkeypatch):
    navigator = MagicMock()
    navigator.get_battery_snapshot.return_value = {
        "battery": None,
        "battery_received_monotonic": None,
    }
    monkeypatch.setattr(runtime, "navigator", navigator)

    assert robot_context.current_battery_percent() is None


def _set_runtime_battery(monkeypatch, *, percent, voltage, age_sec):
    navigator = MagicMock()
    navigator.get_battery_snapshot.return_value = {
        "battery": percent,
        "battery_voltage": voltage,
        "battery_received_monotonic": time.monotonic() - age_sec,
        "battery_sampled_at": "2026-07-16T10:30:00+00:00",
    }
    mission_manager = MagicMock()
    mission_manager.mission_status = "IDLE"
    mission_manager.get_status_snapshot.return_value = {"battery": percent, "pose": None}
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(runtime, "mission_manager", mission_manager)
    monkeypatch.setattr(robot_context, "active_robot_online", lambda: True)
    monkeypatch.setattr(robot_context, "command_accepting", lambda: True)
    monkeypatch.setattr(robot_context, "cmd_vel_subscriber_count", lambda: 0)
    monkeypatch.setattr(robot_context, "cmd_vel_subscribers", lambda: [])


def test_robot_status_payload_contains_fresh_battery_fields(monkeypatch):
    _set_runtime_battery(monkeypatch, percent=58.0, voltage=11.844, age_sec=0.2)

    payload = robot_context.movement_robot_status_payload("tb3_2")

    assert payload["battery"] == 58
    assert payload["battery_voltage"] == 11.844
    assert payload["battery_status"] == "normal"
    assert payload["battery_stale"] is False
    assert payload["battery_age_sec"] == pytest.approx(0.2, abs=0.1)


def test_robot_status_payload_marks_old_sample_unknown(monkeypatch):
    _set_runtime_battery(monkeypatch, percent=18.0, voltage=11.124, age_sec=10.0)

    payload = robot_context.movement_robot_status_payload("tb3_2")

    assert payload["battery"] is None
    assert payload["battery_status"] == "unknown"
    assert payload["battery_stale"] is True


def test_robot_status_payload_classifies_fresh_critical_sample(monkeypatch):
    _set_runtime_battery(monkeypatch, percent=18.0, voltage=11.124, age_sec=0.1)

    payload = robot_context.movement_robot_status_payload("tb3_2")

    assert payload["battery_status"] == "critical"
    assert payload["battery_stale"] is False
