"""Robot capability and lift safety contract tests (ROS-free)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from nav_app.config.validation import validate_robot_profile
from nav_app.errors import StageError
from nav_app.models import MovementStep
from nav_app.runtime import runtime
from nav_app.services import docking
from nav_app.services import capabilities


ROOT = Path(__file__).resolve().parents[1]
ROBOTS_JSON = ROOT / "config" / "robots.json"


def _robot(robot_id: str) -> dict:
    data = json.loads(ROBOTS_JSON.read_text(encoding="utf-8"))
    return next(robot for robot in data["robots"] if robot["robot_id"] == robot_id)


def test_robots_json_profiles_declare_capabilities_and_ports():
    tb3_1 = _robot("tb3_burger_01")
    tb3_2 = _robot("tb3_burger_02")

    assert tb3_1["capabilities"] == ["navigate", "charge", "lift"]
    assert tb3_1["api_port"] == 8001
    assert tb3_1["lift"]["enabled"] is True
    assert tb3_1["lift"] == tb3_2["lift"]
    assert tb3_1["field_dispatch"] == tb3_2["field_dispatch"] == {
        "inbound": True,
        "outbound": True,
        "status": "COMMISSIONED_ROBOT2_MAP_PHYSICAL_LEVEL1",
    }
    assert tb3_1["aruco_detector"] == tb3_2["aruco_detector"]

    assert tb3_2["capabilities"] == ["navigate", "charge", "lift"]
    assert tb3_2["api_port"] == 8002
    assert tb3_2["lift"]["enabled"] is True


def test_validation_rejects_bad_capabilities_and_lift_mismatches():
    base = _robot("tb3_burger_02")

    bad_type = {**base, "capabilities": "navigate"}
    assert any("capabilities must be a list of strings" in error for error in validate_robot_profile(bad_type))

    lift_enabled_without_capability = {**base, "capabilities": ["navigate", "charge"], "lift": {**base["lift"], "enabled": True}}
    assert any("lift.enabled requires lift capability" in error for error in validate_robot_profile(lift_enabled_without_capability))

    lift_capability_when_disabled = {**base, "capabilities": ["navigate", "charge", "lift"], "lift": {**base["lift"], "enabled": False}}
    assert any("lift capability requires lift.enabled=true" in error for error in validate_robot_profile(lift_capability_when_disabled))

    inbound_without_lift = {**base, "capabilities": ["navigate", "charge", "inbound"], "lift": {**base["lift"], "enabled": False}}
    assert any("inbound capability requires lift.enabled=true and lift capability" in error for error in validate_robot_profile(inbound_without_lift))


def test_tb1_capability_helper_allows_same_lift_steps_as_tb2():
    profile = _robot("tb3_burger_01")
    capabilities.ensure_steps_supported(
        [MovementStep(action="dock_transfer", payload={"aruco_marker_id": 1, "action": "load", "level": 1})],
        profile=profile,
    )
    capabilities.ensure_steps_supported(
        [
            MovementStep(action="nav2_pose", payload={"goal": {"x": 1, "y": 2, "yaw": 0}}),
            MovementStep(action="aruco_align", payload={"aruco_marker_id": 1, "final": "hold"}),
            MovementStep(action="manual_drive", payload={"command": "stop"}),
        ],
        profile=profile,
    )


def test_lift_status_summary_exposes_ready_reason(monkeypatch):
    lift_profile = _robot("tb3_burger_02")
    monkeypatch.setattr(capabilities, "active_robot_profile", lambda: lift_profile)
    monkeypatch.setattr(runtime, "lift_client", None)
    monkeypatch.setenv("SIMULATION_MODE", "1")

    status = capabilities.active_lift_status()

    assert status["enabled"] is True
    assert status["ready"] is False
    assert status["reason"] == "lift_client_not_initialized"


def test_lift_status_requires_emergency_stop_subscriber(monkeypatch):
    client = MagicMock(enabled=True, position_mm=10.0, direction="STOP", limit_lower=False)
    client._pub_move.get_subscription_count.return_value = 1
    client._pub_home.get_subscription_count.return_value = 1
    client._pub_stop.get_subscription_count.return_value = 0
    client.telemetry_health.return_value = {"ready": True, "reason": "ok"}
    monkeypatch.setattr(runtime, "lift_client", client)

    status = capabilities.active_lift_status(_robot("tb3_burger_02"))

    assert status["ready"] is False
    assert status["reason"] == "lift_bridge_subscriber_not_ready"
    assert status["bridge_subscribers"]["cmd_stop"] is False


def test_execute_lift_action_disabled_client_fails_instead_of_noop(monkeypatch):
    monkeypatch.delenv("LIFT_UP_COMMAND", raising=False)
    monkeypatch.setattr(runtime, "lift_client", MagicMock(enabled=False))

    with pytest.raises(RuntimeError, match="lift client is not enabled"):
        docking.execute_lift_action("load", 1, {})


def test_dock_transfer_checks_lift_readiness_before_insert(monkeypatch):
    monkeypatch.setattr(capabilities, "active_robot_profile", lambda: _robot("tb3_burger_02"))
    monkeypatch.setattr(runtime, "lift_client", None)
    monkeypatch.setattr(runtime, "mission_manager", MagicMock(dry_run=False))
    monkeypatch.setattr(runtime, "navigator", MagicMock())

    calls: list[str] = []
    monkeypatch.setattr(docking, "is_simulation_mode", lambda: False)
    monkeypatch.setattr(docking, "rotate_to_approach_yaw_if_needed", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(docking, "acquire_dock_marker", lambda *_args, **_kwargs: {"marker_id": 1})
    monkeypatch.setattr(docking, "execute_docking_align", lambda *_args, **_kwargs: {"marker_id": 1})
    monkeypatch.setattr(docking, "execute_fork_insert", lambda *_args, **_kwargs: calls.append("insert") or True)

    with pytest.raises(StageError) as excinfo:
        docking.execute_dock_transfer_step(MovementStep(action="dock_transfer", payload={"aruco_marker_id": 1, "action": "load", "level": 1}))

    assert excinfo.value.stage == "lift_ready"
    assert "lift_client_not_initialized" in excinfo.value.reason
    assert calls == []


def test_configured_lift_profile_allows_fake_dock_transfer_in_simulation(monkeypatch):
    navigator = MagicMock()
    navigator.safety.estop = False
    monkeypatch.setattr(capabilities, "active_robot_profile", lambda: _robot("tb3_burger_02"))
    monkeypatch.setattr(runtime, "lift_client", None)
    monkeypatch.setattr(runtime, "mission_manager", MagicMock(dry_run=False))
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setenv("SIMULATION_MODE", "0")
    monkeypatch.setattr(docking, "is_simulation_mode", lambda: True)
    monkeypatch.setattr(docking.time, "sleep", lambda _seconds: None)

    result = docking.execute_dock_transfer_step(
        MovementStep(
            action="dock_transfer",
            payload={"aruco_marker_id": 1, "action": "load", "level": 1},
        )
    )

    assert result is True
