"""Fail-closed freshness contracts for physical docking and lift motion."""

from __future__ import annotations

import time
from types import SimpleNamespace

import pytest

from nav_app.models import MovementStep
from nav_app.runtime import runtime
from nav_app.services import capabilities, docking
from nav_app.services.lift_client import LiftClient


class _Navigator:
    def __init__(self, health):
        self.health = health
        self.safety = SimpleNamespace(estop=False)

    def docking_sensor_freshness(self, **kwargs):
        self.kwargs = kwargs
        return self.health

    def publish_stop_velocity(self):
        self.stop_calls = getattr(self, "stop_calls", 0) + 1


@pytest.mark.parametrize(
    "reason",
    ["scan_missing", "scan_stale", "scan_timestamp_future", "tf_stale", "aruco_missing_or_stale"],
)
def test_physical_insert_rejects_missing_stale_or_future_sensor_data(monkeypatch, reason):
    navigator = _Navigator({"ok": False, "reason": reason})
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(runtime, "mission_manager", SimpleNamespace(dry_run=False))
    monkeypatch.setattr(docking, "is_simulation_mode", lambda: False)

    with pytest.raises(RuntimeError, match=reason):
        docking.require_docking_motion_freshness({}, "insert", require_aruco=True)
    assert navigator.kwargs["require_aruco"] is True


@pytest.mark.parametrize("stage", ["insert", "reverse", "leave_dock"])
def test_physical_motion_accepts_only_fresh_scan_tf_and_aruco(monkeypatch, stage):
    navigator = _Navigator({"ok": True, "reason": "ok", "scan_age_sec": 0.01, "tf_age_sec": 0.01})
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(runtime, "mission_manager", SimpleNamespace(dry_run=False))
    monkeypatch.setattr(docking, "is_simulation_mode", lambda: False)

    docking.require_docking_motion_freshness({}, stage, require_aruco=stage == "insert")


def test_explicit_dry_run_is_the_only_sensor_bypass(monkeypatch):
    monkeypatch.setattr(runtime, "navigator", _Navigator({"ok": False, "reason": "scan_missing"}))
    monkeypatch.setattr(runtime, "mission_manager", SimpleNamespace(dry_run=False))
    monkeypatch.setattr(docking, "is_simulation_mode", lambda: False)

    docking.require_docking_motion_freshness({"dry_run": True}, "reverse")


def test_align_velocity_degradation_zeros_base_before_abort(monkeypatch):
    navigator = _Navigator({"ok": False, "reason": "tf_stale"})
    # Keep this ROS-free fake explicit rather than relying on MagicMock truthiness.
    stops = []
    navigator.publish_stop_velocity = lambda: stops.append(True)
    navigator.publish_velocity_for_duration = lambda **_kwargs: pytest.fail("velocity must not publish")
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(runtime, "mission_manager", SimpleNamespace(dry_run=False))
    monkeypatch.setattr(docking, "is_simulation_mode", lambda: False)

    with pytest.raises(RuntimeError, match="tf_stale"):
        docking._publish_docking_velocity({}, "aruco_align", require_aruco=True, linear_x=0.0, angular_z=0.1, duration_sec=0.1)
    assert stops == [True]


@pytest.mark.parametrize(
    ("stage", "require_aruco", "degraded_reason"),
    [
        ("aruco_align", True, "aruco_missing_or_stale"),
        ("reverse", False, "localization_missing_or_stale"),
    ],
)
def test_degradation_during_docking_velocity_stops_before_next_segment(
    monkeypatch, stage, require_aruco, degraded_reason
):
    """Long align/reverse bursts must recheck health while the command is active."""
    navigator = _Navigator({"ok": True, "reason": "ok"})
    checks = iter(({"ok": True, "reason": "ok"}, {"ok": False, "reason": degraded_reason}))
    navigator.docking_sensor_freshness = lambda **_kwargs: next(checks)
    bursts = []
    navigator.publish_velocity_for_duration = lambda **kwargs: bursts.append(kwargs) or True
    lift = SimpleNamespace(enabled=True, telemetry_health=lambda: {"ready": True, "reason": "ok"})
    lift.stop = lambda: setattr(lift, "stop_calls", getattr(lift, "stop_calls", 0) + 1)
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(runtime, "lift_client", lift)
    monkeypatch.setattr(runtime, "mission_manager", SimpleNamespace(dry_run=False))
    monkeypatch.setattr(docking, "is_simulation_mode", lambda: False)

    with pytest.raises(RuntimeError, match=degraded_reason):
        docking._publish_docking_velocity(
            {"docking_freshness_segment_sec": 0.1},
            stage,
            require_aruco=require_aruco,
            linear_x=0.0,
            angular_z=0.1,
            duration_sec=0.2,
        )

    assert len(bursts) == 1
    assert navigator.stop_calls == 1
    assert lift.stop_calls == 1


def test_dropped_lift_telemetry_is_stale_before_motion():
    client = LiftClient(SimpleNamespace(), {"enabled": False, "telemetry_max_age_sec": 0.01})
    client.position_mm = 50.0
    client.direction = "STOP"
    client.limit_lower = False
    old = time.monotonic() - 1.0
    client._telemetry_receipt_monotonic = {"position": old, "direction": old, "limit_lower": old}

    health = client.telemetry_health()
    assert not health["ready"]
    assert health["reason"].startswith("telemetry_stale:")
    with pytest.raises(RuntimeError, match="lift_telemetry_stale"):
        client._require_fresh_telemetry()


def test_lift_ack_timeout_is_fail_closed(monkeypatch):
    client = LiftClient(SimpleNamespace(), {"enabled": False, "ack_timeout_sec": 0.0})
    now = time.monotonic()
    client._telemetry_receipt_monotonic = {"position": now, "direction": now, "limit_lower": now}
    client._last_command_monotonic = now - 1.0
    monkeypatch.setattr(client, "_publish_stop", lambda: None)

    with pytest.raises(RuntimeError, match="lift_ack_stale"):
        client._wait_until(lambda: False, 0.1, "unexpected", {"position": 0, "direction": 0, "limit_lower": 0})


def test_non_lift_hold_insert_intent_is_rejected_by_capability_gate():
    profile = {"capabilities": ["navigate", "charge"], "lift": {"enabled": False}}
    step = MovementStep(action="aruco_align", payload={"final": "hold", "fork_insert_on_hold": True})

    with pytest.raises(Exception) as excinfo:
        capabilities.ensure_steps_supported([step], profile)
    assert "robot_missing_capability:lift" in str(excinfo.value.detail)


def test_stale_lift_telemetry_aborts_docking_and_stops_base_and_lift(monkeypatch):
    navigator = _Navigator({"ok": True, "reason": "ok"})
    lift = SimpleNamespace(enabled=True, telemetry_health=lambda: {"ready": False, "reason": "telemetry_stale"})
    lift.stop = lambda: setattr(lift, "stop_calls", getattr(lift, "stop_calls", 0) + 1)
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(runtime, "lift_client", lift)
    monkeypatch.setattr(runtime, "mission_manager", SimpleNamespace(dry_run=False))
    monkeypatch.setattr(docking, "is_simulation_mode", lambda: False)

    with pytest.raises(RuntimeError, match="lift_telemetry_stale"):
        docking._publish_docking_velocity({}, "align", linear_x=0.0, angular_z=0.1, duration_sec=0.1)

    assert navigator.stop_calls == 1
    assert lift.stop_calls == 1


def test_lift_phase_telemetry_degradation_stops_base_and_lift(monkeypatch):
    """A stale lift reading before a lift phase blocks the lift command itself."""
    navigator = _Navigator({"ok": True, "reason": "ok"})
    lift = SimpleNamespace(enabled=True, telemetry_health=lambda: {"ready": False, "reason": "telemetry_stale"})
    lift.stop = lambda: setattr(lift, "stop_calls", getattr(lift, "stop_calls", 0) + 1)
    lift.execute_transfer = lambda *_args: pytest.fail("lift command must not publish")
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(runtime, "lift_client", lift)
    monkeypatch.setattr(runtime, "mission_manager", SimpleNamespace(dry_run=False))
    monkeypatch.setattr(docking, "is_simulation_mode", lambda: False)

    with pytest.raises(RuntimeError, match="lift_telemetry_stale"):
        docking.execute_lift_action("load", 1, {})

    assert navigator.stop_calls == 1
    assert lift.stop_calls == 1
