"""Regression coverage for localization history replay at the API boundary."""

import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from logistics_navigator import LogisticsNavigator
from nav_app.runtime import runtime
from nav_app.services import robot_context
from nav_app.services.localization import LocalizationGate

PROFILE = {
    "localization": {
        "map_id": "factory-a",
        "map_metadata_identity": "sha256:map-a",
        "max_scan_age_sec": 1.0,
        "max_tf_age_sec": 1.0,
        "max_amcl_age_sec": 1.0,
        "max_covariance_x": 0.2,
        "max_covariance_y": 0.2,
        "max_covariance_yaw": 0.3,
        "consecutive_samples": 10,
        "convergence_timeout_sec": 120.0,
        "stable_min_duration_sec": 3.0,
        "max_pose_jitter_m": 0.08,
        "max_yaw_jitter_rad": 0.15,
    }
}


def _sample(receipt_monotonic: float, covariance: float = 0.1) -> dict:
    return {
        "x": 1.0,
        "y": 2.0,
        "yaw": 0.1,
        "covariance": {"x": covariance, "y": covariance, "yaw": covariance},
        "receipt_monotonic": receipt_monotonic,
    }


def _observation(samples: list[dict], *, now: float = 110.0, **overrides) -> dict:
    value = {
        "amcl": samples[-1],
        "amcl_samples": samples,
        "scan_age_sec": 0.1,
        "scan_source_age_sec": 0.1,
        "tf_age_sec": 0.1,
        "tf_source_age_sec": 0.1,
        "tf_continuous": True,
        "receipt_monotonic": now,
    }
    value.update(overrides)
    return value


@pytest.fixture
def localization_runtime(monkeypatch):
    gate = LocalizationGate(PROFILE)
    gate.start(None, now_monotonic=99.0)
    navigator = SimpleNamespace(localization_observation=lambda: None)
    monkeypatch.setattr(robot_context, "localization_gate", lambda: gate)
    monkeypatch.setattr(runtime, "navigator", navigator)
    return gate, navigator


def test_delayed_poll_replays_ten_unseen_samples_with_sample_receipt_times(localization_runtime):
    gate, navigator = localization_runtime
    samples = [_sample(100.0 + index * 0.5) for index in range(10)]
    navigator.localization_observation = lambda: _observation(samples)

    health = robot_context.localization_health()

    assert health["localized"] is True
    assert health["sample_count"] == 10
    assert health["stable_duration_sec"] == pytest.approx(4.5)
    assert gate.last_amcl_receipt_monotonic == pytest.approx(104.5)


def test_repeated_stale_history_does_not_reset_localized_gate(localization_runtime):
    gate, navigator = localization_runtime
    samples = [_sample(100.0 + index * 0.5) for index in range(10)]
    current = _observation(samples)
    navigator.localization_observation = lambda: current
    assert robot_context.localization_health()["localized"] is True

    current["amcl_samples"] = [_sample(98.0, covariance=9.0)]
    current["receipt_monotonic"] = 120.0
    health = robot_context.localization_health()

    assert health["localized"] is True
    assert health["sample_count"] == 10
    assert health["reason"] == "converged"
    assert gate.last_amcl_receipt_monotonic == pytest.approx(104.5)


def test_scan_alignment_confirmation_is_fail_closed_without_resetting_amcl_gate(
    localization_runtime, monkeypatch
):
    gate, navigator = localization_runtime
    samples = [_sample(100.0 + index * 0.5) for index in range(10)]
    navigator.localization_observation = lambda: _observation(samples)
    navigator.scan_map_alignment_status = {
        "accepted": False,
        "refinement_required": False,
        "reason": "not_checked",
    }
    navigator.localization_alignment_observation = lambda _profile: {
        "accepted": False,
        "refinement_required": False,
        "reason": "confirmation_pending",
        "confirmation_count": 1,
        "confirmation_required": 3,
    }
    monkeypatch.setattr(robot_context, "alignment_config", lambda _profile: {"enabled": True})

    health = robot_context.localization_health()

    assert gate.state == "LOCALIZED"
    assert health["localized"] is False
    assert health["state"] == "CONVERGING"
    assert health["reason"] == "scan_map_alignment_confirmation_pending"
    assert health["scan_map_alignment"]["confirmation_count"] == 1


def test_missing_scan_timestamp_pair_waits_without_marking_location_lost(
    localization_runtime, monkeypatch
):
    gate, navigator = localization_runtime
    samples = [_sample(100.0 + index * 0.5) for index in range(10)]
    navigator.localization_observation = lambda: _observation(samples)
    navigator.scan_map_alignment_status = {
        "accepted": False,
        "refinement_required": False,
        "reason": "not_checked",
    }
    navigator.localization_alignment_observation = lambda _profile: {
        "accepted": False,
        "refinement_required": False,
        "reason": "temporal_pair_pending",
    }
    monkeypatch.setattr(robot_context, "alignment_config", lambda _profile: {"enabled": True})

    health = robot_context.localization_health()

    assert gate.state == "LOCALIZED"
    assert health["localized"] is False
    assert health["state"] == "CONVERGING"
    assert health["reason"] == "scan_map_alignment_temporal_pair_pending"


@pytest.mark.parametrize(
    "loss_reason",
    ["kidnapped_pose_jump", "scan_map_alignment_refinement_pass_limit"],
)
def test_confirmed_idle_location_loss_starts_one_motionless_global_recovery(
    localization_runtime, monkeypatch, loss_reason
):
    gate, navigator = localization_runtime
    gate.state = "LOST" if loss_reason == "kidnapped_pose_jump" else "DEGRADED"
    gate.reason = loss_reason
    navigator.status = "IDLE"
    navigator.safety = SimpleNamespace(estop=False)
    navigator.scan_map_alignment_status = {"accepted": False, "reason": loss_reason}
    navigator.global_localization_search_active = lambda: False
    navigator.request_global_localization = MagicMock(return_value={
        "accepted": True,
        "strategy": "observe_only",
        "motion_started": False,
        "reason": "map_wide_scan_search_started",
    })
    monkeypatch.setattr(runtime, "active_movement_command_id", None)
    monkeypatch.setattr(runtime, "mission_manager", SimpleNamespace(mission_status="IDLE"))

    health = robot_context.localization_health(refresh_alignment=False)

    assert health["state"] == "GLOBAL_SEARCH"
    assert health["localized"] is False
    assert health["automatic_recovery"]["triggered"] is True
    assert health["automatic_recovery"]["trigger_reason"] == loss_reason
    request = navigator.request_global_localization.call_args.args[0]
    assert request["strategy"] == "observe_only"
    assert request["allow_motion"] is False
    assert request["restart_existing"] is False


@pytest.mark.parametrize(
    "loss_reason",
    ["tf_discontinuous", "scan_map_alignment_temporal_pair_pending", "global_match_ambiguous"],
)
def test_uncertain_localization_signals_never_auto_reset(
    localization_runtime, monkeypatch, loss_reason
):
    gate, navigator = localization_runtime
    gate.state = "DEGRADED"
    gate.reason = loss_reason
    navigator.status = "IDLE"
    navigator.safety = SimpleNamespace(estop=False)
    navigator.scan_map_alignment_status = {"accepted": False, "reason": loss_reason}
    navigator.global_localization_search_active = lambda: False
    navigator.request_global_localization = MagicMock()
    monkeypatch.setattr(runtime, "active_movement_command_id", None)
    monkeypatch.setattr(runtime, "mission_manager", SimpleNamespace(mission_status="IDLE"))

    health = robot_context.localization_health(refresh_alignment=False)

    assert "automatic_recovery" not in health
    navigator.request_global_localization.assert_not_called()


def test_confirmed_location_loss_waits_for_idle_before_auto_reset(localization_runtime, monkeypatch):
    gate, navigator = localization_runtime
    gate.state = "LOST"
    gate.reason = "kidnapped_pose_jump"
    navigator.status = "MOVING"
    navigator.safety = SimpleNamespace(estop=False)
    navigator.scan_map_alignment_status = {"accepted": False, "reason": "kidnapped_pose_jump"}
    navigator.global_localization_search_active = lambda: False
    navigator.request_global_localization = MagicMock()
    monkeypatch.setattr(runtime, "active_movement_command_id", "active-command")
    monkeypatch.setattr(runtime, "mission_manager", SimpleNamespace(mission_status="RUNNING"))

    health = robot_context.localization_health(refresh_alignment=False)

    assert health["state"] == "LOST"
    assert "automatic_recovery" not in health
    navigator.request_global_localization.assert_not_called()


def test_lightweight_localization_refresh_reuses_cached_alignment(localization_runtime, monkeypatch):
    gate, navigator = localization_runtime
    samples = [_sample(100.0 + index * 0.5) for index in range(10)]
    navigator.localization_observation = lambda: _observation(samples)
    navigator.scan_map_alignment_status = {
        "accepted": True,
        "refinement_required": False,
        "reason": "localized_recheck_ok",
    }
    navigator.localization_alignment_observation = MagicMock()
    monkeypatch.setattr(robot_context, "alignment_config", lambda _profile: {"enabled": True})

    health = robot_context.localization_health(refresh_alignment=False)

    assert gate.state == "LOCALIZED"
    assert health["localized"] is True
    assert health["scan_map_alignment"]["reason"] == "localized_recheck_ok"
    navigator.localization_alignment_observation.assert_not_called()


@pytest.mark.parametrize(
    ("gate_state", "gate_reason"),
    [
        ("DEGRADED", "tf_missing_or_stale"),
        ("FAILED", "convergence_timeout"),
    ],
)
@pytest.mark.parametrize(
    "alignment_reason",
    ["confirmation_pending", "global_localization_search_active"],
)
def test_stale_scan_alignment_status_does_not_mask_nonlocalized_gate(
    localization_runtime, monkeypatch, gate_state, gate_reason, alignment_reason
):
    gate, navigator = localization_runtime
    gate.state = gate_state
    gate.reason = gate_reason
    navigator.scan_map_alignment_status = {
        "accepted": False,
        "refinement_required": False,
        "reason": alignment_reason,
        "confirmation_count": 2,
        "confirmation_required": 3,
    }
    navigator.localization_alignment_observation = MagicMock()
    monkeypatch.setattr(robot_context, "alignment_config", lambda _profile: {"enabled": True})

    health = robot_context.localization_health()

    assert health["localized"] is False
    assert health["state"] == gate_state
    assert health["reason"] == gate_reason
    assert health["scan_map_alignment"]["reason"] == alignment_reason
    navigator.localization_alignment_observation.assert_not_called()


def test_scan_alignment_does_not_start_refinement_while_global_search_owns_localization(
    localization_runtime, monkeypatch
):
    gate, navigator = localization_runtime
    samples = [_sample(100.0 + index * 0.5) for index in range(10)]
    navigator.localization_observation = lambda: _observation(samples)
    navigator.scan_map_alignment_status = {"accepted": False, "reason": "not_checked"}
    navigator.localization_alignment_observation = MagicMock()
    navigator.global_localization_search_active = lambda: True
    navigator.global_localization_search_status = lambda: {
        "reason": "map_wide_candidate_pending",
        "stage": "map_wide",
    }
    monkeypatch.setattr(robot_context, "alignment_config", lambda _profile: {"enabled": True})

    health = robot_context.localization_health()

    assert gate.state == "LOCALIZED"
    assert health["localized"] is False
    assert health["state"] == "CONVERGING"
    assert health["reason"] == "global_localization_search_active"
    navigator.localization_alignment_observation.assert_not_called()


def test_concurrent_alignment_admission_claims_one_refinement(localization_runtime, monkeypatch):
    gate, _ = localization_runtime
    gate.state = "LOCALIZED"
    gate.reason = "converged"
    alignment = {
        "accepted": False,
        "refinement_required": True,
        "reason": "correction_available",
        "attempts": 0,
        "last_confirmation_scan_token": 20.0,
        "corrected_pose": {"x": 1.0, "y": 2.0, "yaw": 0.1},
    }
    navigator = LogisticsNavigator.__new__(LogisticsNavigator)
    navigator.scan_map_alignment_lock = threading.RLock()
    navigator.scan_map_alignment_status = dict(alignment)
    navigator.global_localization_search_active = lambda: False
    both_observed = threading.Barrier(2)

    def observe(_profile):
        both_observed.wait(timeout=2.0)
        return dict(alignment)

    navigator.localization_alignment_observation = observe
    apply_calls = []
    apply_lock = threading.Lock()

    def apply(claimed, _search):
        with apply_lock:
            apply_calls.append(dict(claimed))
        return dict(claimed["corrected_pose"])

    navigator.apply_scan_map_refinement = apply
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(robot_context, "alignment_config", lambda _profile: {
        "enabled": True,
        "max_refinement_passes": 3,
        "initial_covariance": {"x": 0.02, "y": 0.02, "yaw": 0.01},
    })
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(robot_context._scan_map_alignment_admission(gate)))
        for _ in range(2)
    ]

    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=3.0)

    assert all(not thread.is_alive() for thread in threads)
    assert len(apply_calls) == 1
    assert apply_calls[0]["refinement_claimed"] is True
    assert len(results) == 2


def test_live_command_acceptance_requires_background_nav2_readiness(monkeypatch):
    navigator = SimpleNamespace(nav2_ready=False)
    mission_manager = SimpleNamespace(dry_run=False)
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(runtime, "mission_manager", mission_manager)
    monkeypatch.setattr(robot_context, "active_robot_online", lambda: True)
    monkeypatch.setattr(robot_context, "localization_health", lambda: {"localized": True})
    monkeypatch.setattr(robot_context, "is_simulation_mode", lambda: False)

    assert robot_context.command_accepting() is False

    navigator.nav2_ready = True
    assert robot_context.command_accepting() is True


@pytest.mark.parametrize("simulation_mode,dry_run", [(True, False), (False, True)])
def test_nonphysical_command_acceptance_does_not_require_amcl(monkeypatch, simulation_mode, dry_run):
    navigator = SimpleNamespace(nav2_ready=False)
    mission_manager = SimpleNamespace(dry_run=dry_run)
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(runtime, "mission_manager", mission_manager)
    monkeypatch.setattr(robot_context, "active_robot_online", lambda: True)
    monkeypatch.setattr(robot_context, "localization_health", lambda: {"localized": False})
    monkeypatch.setattr(robot_context, "is_simulation_mode", lambda: simulation_mode)

    assert robot_context.command_accepting() is True


def test_nonphysical_command_acceptance_still_blocks_estop(monkeypatch):
    navigator = SimpleNamespace(nav2_ready=False)
    mission_manager = SimpleNamespace(dry_run=True)
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(runtime, "mission_manager", mission_manager)
    monkeypatch.setattr(robot_context, "active_robot_online", lambda: True)
    monkeypatch.setattr(robot_context, "localization_health", lambda: {"localized": False})
    monkeypatch.setattr(robot_context, "is_simulation_mode", lambda: False)

    assert robot_context.command_accepting(is_emergency=True) is False


def test_physical_command_acceptance_still_requires_amcl(monkeypatch):
    navigator = SimpleNamespace(nav2_ready=True)
    mission_manager = SimpleNamespace(dry_run=False)
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(runtime, "mission_manager", mission_manager)
    monkeypatch.setattr(robot_context, "active_robot_online", lambda: True)
    monkeypatch.setattr(robot_context, "localization_health", lambda: {"localized": False})
    monkeypatch.setattr(robot_context, "is_simulation_mode", lambda: False)

    assert robot_context.command_accepting() is False


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"tf_age_sec": 2.0}, "tf_missing_or_stale"),
        ({"tf_continuous": False}, "tf_discontinuous"),
    ],
)
def test_current_tf_failure_revokes_localized_history(localization_runtime, overrides, reason):
    _, navigator = localization_runtime
    samples = [_sample(100.0 + index * 0.5) for index in range(10)]
    navigator.localization_observation = lambda: _observation(samples, **overrides)

    health = robot_context.localization_health()

    assert health["localized"] is False
    assert health["reason"] == reason
