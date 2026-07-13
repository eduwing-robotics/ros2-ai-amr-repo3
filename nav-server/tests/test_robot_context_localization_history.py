"""Regression coverage for localization history replay at the API boundary."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

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
