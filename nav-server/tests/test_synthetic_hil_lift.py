"""Lift-only synthetic-HIL admission, backend, and provenance contracts."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from nav_app.config.runtime_profiles import resolve_runtime_profile
from nav_app.models import MovementStep, RobotCommandRequest
from nav_app.routers import movement_api, robot_commands as robot_command_routes
from nav_app.runtime import runtime
from nav_app.services import capabilities, command_state, docking
from nav_app.services.lift_backends import (
    DisabledLiftBackend,
    PHYSICAL_LIFT_NOT_VERIFIED,
    VirtualLiftBackend,
    create_lift_backend,
    lift_provenance,
    load_resolved_runtime_profile,
    synthetic_hil_admitted,
)
from nav_app.services.safety import engage_estop


ROOT = Path(__file__).resolve().parents[1]


def _tb1() -> dict:
    robots = json.loads((ROOT / "config" / "robots.json").read_text(encoding="utf-8"))["robots"]
    return next(robot for robot in robots if robot["robot_id"] == "tb3_burger_01")


def _resolved(**updates) -> dict:
    value = resolve_runtime_profile(cli_profile="tb1-synthetic-hil")
    value.update(updates)
    return value


def _install_resolved_profile(tmp_path: Path, monkeypatch, resolved: dict | None = None) -> Path:
    path = tmp_path / "resolved-profile.json"
    path.write_text(json.dumps(resolved or _resolved()), encoding="utf-8")
    monkeypatch.setenv("SF_NAV_RESOLVED_PROFILE_PATH", str(path))
    return path


def _admitted_synthetic_hil(tmp_path: Path, monkeypatch) -> None:
    _install_resolved_profile(tmp_path, monkeypatch)
    monkeypatch.setenv("SF_NAV_ALLOW_SYNTHETIC_HIL", "1")
    monkeypatch.setenv("ROBOT_ID", "tb3_burger_01")
    monkeypatch.setenv("SIMULATION_MODE", "0")


def test_virtual_lift_backend_is_ros_free_deterministic_and_stoppable():
    backend = VirtualLiftBackend(_tb1()["lift"])

    transfer = backend.execute_transfer("load", 1, {})
    backend.stop()

    assert transfer["position_mm"] == 43.0
    assert [item["operation"] for item in backend.transitions] == ["move_to", "stop"]
    assert backend.transitions[0]["phase"] == "transfer"
    assert backend.status()["stopped"] is True
    assert backend.status()["physical_lift_verified"] is False
    assert backend.status()["physical_lift_reason"] == PHYSICAL_LIFT_NOT_VERIFIED
    assert backend.status()["lift_evidence_reason"] == PHYSICAL_LIFT_NOT_VERIFIED
    assert not hasattr(backend, "_pub_move")


def test_live_execution_and_physical_capability_do_not_claim_lift_verification(monkeypatch):
    robots = json.loads((ROOT / "config" / "robots.json").read_text())["robots"]
    tb2 = next(robot for robot in robots if robot["robot_id"] == "tb3_burger_02")
    monkeypatch.delenv("SF_NAV_RESOLVED_PROFILE_PATH", raising=False)
    monkeypatch.setattr(runtime, "lift_client", None)
    provenance = lift_provenance(
        resolved_profile={"execution_class": "live", "evidence_class": "physical"},
        backend=SimpleNamespace(backend_name="physical"),
    )
    tb1_status = capabilities.active_lift_status(_tb1())

    assert "lift" in tb2["capabilities"]
    assert provenance["physical_lift_verified"] is False
    assert provenance["physical_lift_reason"] == PHYSICAL_LIFT_NOT_VERIFIED
    assert provenance["lift_evidence_reason"] == PHYSICAL_LIFT_NOT_VERIFIED
    assert "lift" in _tb1()["capabilities"]
    assert tb1_status["reason"] == "lift_client_not_initialized"
    assert tb1_status["physical_lift_verified"] is False
    assert tb1_status["physical_lift_reason"] == PHYSICAL_LIFT_NOT_VERIFIED


def test_unexpected_subscriber_inspection_errors_are_not_masked():
    publisher = MagicMock()
    publisher.get_subscription_count.side_effect = RuntimeError("graph unavailable")

    with pytest.raises(RuntimeError, match="graph unavailable"):
        capabilities._publisher_has_subscriber(publisher)


def test_resolved_profile_snapshot_survives_repository_edits_after_launch(tmp_path, monkeypatch):
    resolved = _resolved()
    _install_resolved_profile(tmp_path, monkeypatch, resolved)
    # Runtime requests must not re-read mutable inputs after the launcher has
    # already validated and snapshotted them for this process.
    monkeypatch.setenv("SF_NAV_MANIFEST_PATH", str(tmp_path / "edited-or-removed-manifest.json"))
    monkeypatch.setenv("SF_NAV_ROBOTS_PATH", str(tmp_path / "edited-or-removed-robots.json"))
    monkeypatch.setenv("ROBOT_ID", "tb3_burger_01")

    assert load_resolved_runtime_profile() == resolved


@pytest.mark.parametrize(
    "resolved,environment,reason",
    [
        (_resolved(), {}, "process_gate_required"),
        (_resolved(execution_class="live", evidence_class="physical"), {"SF_NAV_ALLOW_SYNTHETIC_HIL": "1"}, None),
        (_resolved(evidence_class="physical"), {"SF_NAV_ALLOW_SYNTHETIC_HIL": "1"}, "nonphysical"),
        (_resolved(virtual_lift={"enabled": False, "backend": "deterministic"}), {"SF_NAV_ALLOW_SYNTHETIC_HIL": "1"}, "virtual_lift_required"),
    ],
)
def test_backend_selection_is_two_key_fail_closed(resolved, environment, reason):
    if reason is None:
        resolved["lift_backends"] = {"tb3_burger_01": "disabled"}
        backend = create_lift_backend(MagicMock(), _tb1(), resolved_profile=resolved, environment=environment)
        assert isinstance(backend, DisabledLiftBackend)
        assert backend.enabled is False
        assert backend.status()["reason"] == "lift_disabled"
        with pytest.raises(RuntimeError, match="lift_disabled"):
            backend.execute_transfer("load", 1, {})
        return
    with pytest.raises(RuntimeError, match=reason):
        create_lift_backend(MagicMock(), _tb1(), resolved_profile=resolved, environment=environment)


def test_synthetic_profile_keeps_tb1_hardware_capability_while_selecting_virtual_backend(monkeypatch):
    profile = _tb1()
    assert profile["capabilities"] == ["navigate", "charge", "lift"]
    monkeypatch.setattr(capabilities, "synthetic_hil_admitted", lambda: True)

    capabilities.ensure_steps_supported(
        [MovementStep(action="dock_transfer", payload={"aruco_marker_id": 1, "action": "load", "level": 1})],
        profile=profile,
    )
    assert _resolved()["lift_backends"] == {"tb3_burger_01": "virtual"}
    assert capabilities.profile_capabilities(profile) == ["navigate", "charge", "lift"]


@pytest.mark.parametrize(
    "mutation,error",
    [
        (lambda resolved: resolved.__setitem__("schema_version", 2), "schema"),
        (lambda resolved: resolved.__setitem__("profile_id", ""), "profile_id"),
        (lambda resolved: resolved.__setitem__("selection_source", "unknown"), "selection_source"),
        (lambda resolved: resolved.__setitem__("robots", []), "selected robots"),
        (lambda resolved: resolved["robots"][0].__setitem__("robot_id", ""), "selected robots"),
    ],
)
def test_resolved_profile_snapshot_rejects_invalid_runtime_structure(
    tmp_path, monkeypatch, mutation, error,
):
    resolved = _resolved()
    mutation(resolved)
    _install_resolved_profile(tmp_path, monkeypatch, resolved)
    monkeypatch.setenv("SF_NAV_ALLOW_SYNTHETIC_HIL", "1")
    monkeypatch.setenv("ROBOT_ID", "tb3_burger_01")

    with pytest.raises(RuntimeError, match=error):
        synthetic_hil_admitted()


def test_resolved_profile_must_select_active_robot(tmp_path, monkeypatch):
    _install_resolved_profile(tmp_path, monkeypatch)
    monkeypatch.setenv("SF_NAV_ALLOW_SYNTHETIC_HIL", "1")
    monkeypatch.setenv("ROBOT_ID", "tb3_burger_02")

    with pytest.raises(RuntimeError, match="active robot"):
        synthetic_hil_admitted()


def test_main_robot_commands_path_accepts_explicit_synthetic_profile(tmp_path, monkeypatch):
    _admitted_synthetic_hil(tmp_path, monkeypatch)
    navigator = MagicMock()
    navigator.ensure_nav2_ready.return_value = True
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(runtime, "mission_manager", SimpleNamespace(dry_run=False))
    monkeypatch.setattr(runtime, "movement_commands", {})
    monkeypatch.setattr(capabilities, "active_robot_profile", _tb1)
    consume_gate = MagicMock(return_value={"command_id": "arrived-1", "traffic_segments": []})
    monkeypatch.setattr(robot_command_routes.robot_commands, "_consume_arrived_gate", consume_gate)
    monkeypatch.setattr(movement_api.robot_context, "active_robot_online", lambda: True)
    monkeypatch.setattr(movement_api.robot_context, "localization_health", lambda: {"localized": True})
    monkeypatch.setattr(movement_api.robot_context, "report_movement_robot_status", lambda *_args: None)
    monkeypatch.setattr(movement_api.command_state, "report_command_callback", lambda *_args: None)
    req = RobotCommandRequest(
        command_id="main-hil-1",
        robot_id="tb3_1",
        kind="dock_transfer",
        params={"aruco_marker_id": 1, "action": "load", "level": 1},
    )

    response = robot_command_routes.accept_robot_command(req, MagicMock())

    assert response["accepted"] is True
    assert capabilities.profile_capabilities(_tb1()) == ["navigate", "charge", "lift"]


@pytest.mark.parametrize("bypass", ["request", "process", "mission"])
def test_synthetic_hil_rejects_every_dry_run_or_simulation_bypass(tmp_path, monkeypatch, bypass):
    _admitted_synthetic_hil(tmp_path, monkeypatch)
    navigator = MagicMock()
    navigator.ensure_nav2_ready.return_value = True
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(runtime, "mission_manager", SimpleNamespace(dry_run=bypass == "mission"))
    monkeypatch.setattr(runtime, "movement_commands", {})
    monkeypatch.setattr(capabilities, "active_robot_profile", _tb1)
    consume_gate = MagicMock(return_value={"command_id": "arrived-1", "traffic_segments": []})
    monkeypatch.setattr(robot_command_routes.robot_commands, "_consume_arrived_gate", consume_gate)
    if bypass == "process":
        monkeypatch.setenv("SIMULATION_MODE", "1")
    req = RobotCommandRequest(
        command_id=f"hil-bypass-{bypass}",
        robot_id="tb3_1",
        kind="dock_transfer",
        dry_run=bypass == "request",
        params={"aruco_marker_id": 1, "action": "load", "level": 1},
    )

    with pytest.raises(HTTPException) as excinfo:
        robot_command_routes.accept_robot_command(req, MagicMock())

    assert excinfo.value.status_code == 409
    assert excinfo.value.detail["code"] == "synthetic_hil_simulation_forbidden"
    consume_gate.assert_not_called()


def test_synthetic_hil_runs_real_docking_and_only_virtualizes_lift(tmp_path, monkeypatch):
    _install_resolved_profile(tmp_path, monkeypatch)
    monkeypatch.setenv("SF_NAV_ALLOW_SYNTHETIC_HIL", "1")
    monkeypatch.setenv("SIMULATION_MODE", "0")
    backend = create_lift_backend(MagicMock(), _tb1())
    navigator = MagicMock()
    navigator.safety.estop = False
    navigator.docking_sensor_freshness.return_value = {"ok": True, "reason": "ok"}
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(runtime, "mission_manager", SimpleNamespace(dry_run=False))
    monkeypatch.setattr(runtime, "lift_client", backend)
    monkeypatch.setattr(capabilities, "active_robot_profile", _tb1)
    monkeypatch.setattr(docking, "is_simulation_mode", lambda: False)

    calls: list[str] = []
    monkeypatch.setattr(docking, "apply_slot_fork_defaults", lambda *_: None)
    monkeypatch.setattr(docking, "apply_slot_lift_defaults", lambda *_: None)
    monkeypatch.setattr(docking, "apply_slot_aruco_defaults", lambda *_: None)
    monkeypatch.setattr(docking, "rotate_to_approach_yaw_if_needed", lambda *_args, **_kwargs: calls.append("rotate") or True)
    monkeypatch.setattr(docking, "acquire_dock_marker", lambda *_args, **_kwargs: calls.append("marker") or {"marker_id": 1})
    monkeypatch.setattr(docking, "execute_docking_align", lambda *_args, **_kwargs: calls.append("align") or {"marker_id": 1})
    monkeypatch.setattr(docking, "execute_pre_insert_lift", lambda action, level, payload: backend.execute_pre_insert(action, level, payload))
    monkeypatch.setattr(docking, "execute_fork_insert", lambda *_: calls.append("insert") or True)
    monkeypatch.setattr(docking, "execute_post_insert_dwell", lambda *_: calls.append("dwell"))
    monkeypatch.setattr(docking, "execute_carry_after_load", lambda action, level, payload: backend.execute_carry_after_load(action, level, payload))
    monkeypatch.setattr(docking, "execute_dock_reverse", lambda *_: calls.append("reverse") or True)

    result = docking.execute_dock_transfer_step(
        MovementStep(action="dock_transfer", payload={"aruco_marker_id": 1, "action": "load", "level": 2})
    )

    assert result is True
    assert calls == ["rotate", "marker", "align", "insert", "dwell", "reverse"]
    assert [item.get("phase") for item in backend.transitions] == ["pre_insert", "transfer"]
    assert all(item["operation"] == "move_to" for item in backend.transitions)


def test_health_events_and_estop_preserve_nonphysical_provenance(tmp_path, monkeypatch):
    _install_resolved_profile(tmp_path, monkeypatch)
    monkeypatch.setenv("SF_NAV_ALLOW_SYNTHETIC_HIL", "1")
    backend = create_lift_backend(MagicMock(), _tb1())
    navigator = MagicMock()
    navigator.safety = MagicMock()
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(runtime, "lift_client", backend)
    monkeypatch.setattr(capabilities, "active_robot_profile", _tb1)

    status = capabilities.active_lift_status(_tb1())
    event = command_state.command_callback_payload({"command_id": "hil-1", "state": "DONE"}, "DONE")
    engage_estop()

    for payload in (status, event, lift_provenance(backend=backend)):
        assert payload["execution_class"] == "synthetic_hil"
        assert payload["evidence_class"] == "nonphysical"
        assert payload["lift_backend"] == "virtual"
        assert payload["physical_lift_verified"] is False
        assert payload["physical_lift_reason"] == PHYSICAL_LIFT_NOT_VERIFIED
        assert payload["lift_evidence_reason"] == PHYSICAL_LIFT_NOT_VERIFIED
    assert backend.transitions[-1]["operation"] == "stop"
    navigator.nav.cancelTask.assert_called_once()
    navigator.publish_stop_velocity.assert_called_once()
