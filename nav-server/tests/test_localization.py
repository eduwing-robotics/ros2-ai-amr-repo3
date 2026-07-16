import pytest

from nav_app.services.localization import (
    GLOBAL_SEARCH,
    LOCALIZED,
    LOST,
    UNLOCALIZED,
    LocalizationGate,
    validate_persisted_seed,
)


PROFILE = {
    "localization": {
        "map_id": "factory-a",
        "map_metadata_identity": "sha256:map-a",
        "base_frame": "base_footprint",
        "max_scan_age_sec": 1.0,
        "max_tf_age_sec": 1.0,
        "max_amcl_age_sec": 1.0,
        "max_covariance_x": 0.2,
        "max_covariance_y": 0.2,
        "max_covariance_yaw": 0.3,
        "consecutive_samples": 2,
        "convergence_timeout_sec": 10.0,
        "persisted_seed_max_age_sec": 60.0,
        "kidnapped_jump_distance_m": 1.0,
        "stable_min_duration_sec": 0.1,
        "max_pose_jitter_m": 0.08,
        "max_yaw_jitter_rad": 0.15,
    }
}


def observation(**overrides):
    value = {
        "amcl": {"x": 1.0, "y": 2.0, "yaw": 0.1, "covariance": {"x": 0.1, "y": 0.1, "yaw": 0.1}, "header_stamp_sec": 5.0, "receipt_monotonic": 9.9},
        "scan_age_sec": 0.1,
        "scan_source_age_sec": 0.1,
        "tf_age_sec": 0.1,
        "tf_source_age_sec": 0.1,
        "tf_continuous": True,
        "receipt_monotonic": 10.0,
    }
    value.update(overrides)
    return value


def test_persisted_seed_requires_matching_map_identity_and_age():
    valid = {"map_id": "factory-a", "map_metadata_identity": "sha256:map-a", "saved_at_epoch_sec": 100.0}
    assert validate_persisted_seed(valid, PROFILE, now_epoch_sec=120.0)[0]
    assert not validate_persisted_seed({**valid, "map_id": "wrong"}, PROFILE, now_epoch_sec=120.0)[0]
    assert not validate_persisted_seed({**valid, "saved_at_epoch_sec": 1.0}, PROFILE, now_epoch_sec=120.0)[0]


def test_no_seed_starts_global_search():
    gate = LocalizationGate(PROFILE)
    assert gate.state == UNLOCALIZED
    assert gate.start(None) == GLOBAL_SEARCH
    assert gate.state == GLOBAL_SEARCH


def test_covariance_requires_consecutive_fresh_samples():
    gate = LocalizationGate(PROFILE)
    gate.start(None, now_monotonic=9.0)
    assert gate.observe(observation())["state"] != LOCALIZED
    second = observation(receipt_monotonic=10.1)
    second["amcl"] = {**second["amcl"], "receipt_monotonic": 10.1}
    assert gate.observe(second)["state"] == LOCALIZED


def test_duplicate_amcl_sample_does_not_count_twice():
    gate = LocalizationGate(PROFILE)
    gate.start(None, now_monotonic=9.0)
    first = observation(receipt_monotonic=10.0)
    gate.observe(first)

    duplicate = observation(receipt_monotonic=10.5)
    result = gate.observe(duplicate)

    assert result["sample_count"] == 1
    assert result["reason"] == "awaiting_new_amcl_sample"


def test_duplicate_poll_does_not_revoke_localized_state():
    gate = LocalizationGate(PROFILE)
    gate.start(None, now_monotonic=9.0)
    gate.observe(observation())
    second = observation(receipt_monotonic=10.1)
    second["amcl"] = {**second["amcl"], "receipt_monotonic": 10.1}
    assert gate.observe(second)["state"] == LOCALIZED

    repeated = observation(receipt_monotonic=10.2)
    repeated["amcl"] = dict(second["amcl"])
    result = gate.observe(repeated)

    assert result["state"] == LOCALIZED
    assert result["localized"] is True
    assert result["reason"] == "converged"


def test_localized_idle_duplicate_stays_valid_with_fresh_scan_and_tf():
    gate = LocalizationGate(PROFILE)
    gate.start(None, now_monotonic=9.0)
    gate.observe(observation())
    second = observation(receipt_monotonic=10.1)
    second["amcl"] = {**second["amcl"], "receipt_monotonic": 10.1}
    assert gate.observe(second)["state"] == LOCALIZED

    frozen = observation(receipt_monotonic=11.2, scan_age_sec=0.01, tf_age_sec=0.01)
    frozen["amcl"] = dict(second["amcl"])
    result = gate.observe(frozen)

    assert result["state"] == LOCALIZED
    assert result["localized"] is True
    assert result["reason"] == "converged"
    assert result["amcl_age_sec"] == pytest.approx(1.1)


def test_transient_scan_gap_after_pass_recovers_without_restarting_admission():
    gate = LocalizationGate(PROFILE)
    gate.start(None, now_monotonic=9.0)
    gate.observe(observation())
    second = observation(receipt_monotonic=10.1)
    second["amcl"] = {**second["amcl"], "receipt_monotonic": 10.1}
    assert gate.observe(second)["state"] == LOCALIZED
    assert gate.started_monotonic is None

    # Long after the original convergence timeout, one stale scan must still
    # fail closed for that sample without poisoning the completed admission.
    stale = observation(receipt_monotonic=25.0, scan_age_sec=2.0)
    stale["amcl"] = dict(second["amcl"])
    degraded = gate.observe(stale)
    assert degraded["localized"] is False
    assert degraded["reason"] == "scan_missing_or_stale"

    recovered = observation(receipt_monotonic=25.1, scan_age_sec=0.01, tf_age_sec=0.01)
    recovered["amcl"] = dict(second["amcl"])
    result = gate.observe(recovered)
    assert result["state"] == LOCALIZED
    assert result["localized"] is True
    assert result["reason"] == "converged"


def test_convergence_timeout_still_fails_an_unfinished_admission():
    gate = LocalizationGate(PROFILE)
    gate.start(None, now_monotonic=0.0)

    result = gate.observe(observation(receipt_monotonic=10.1))

    assert result["state"] == "FAILED"
    assert result["localized"] is False
    assert result["reason"] == "convergence_timeout"


@pytest.mark.parametrize(
    "overrides, reason",
    [
        ({"tf_age_sec": 2.0}, "tf_missing_or_stale"),
        ({"tf_continuous": False}, "tf_discontinuous"),
    ],
)
def test_localized_idle_duplicate_is_revoked_by_stale_or_discontinuous_tf(overrides, reason):
    gate = LocalizationGate(PROFILE)
    gate.start(None, now_monotonic=9.0)
    gate.observe(observation())
    second = observation(receipt_monotonic=10.1)
    second["amcl"] = {**second["amcl"], "receipt_monotonic": 10.1}
    assert gate.observe(second)["state"] == LOCALIZED

    repeated = observation(receipt_monotonic=10.2, **overrides)
    repeated["amcl"] = dict(second["amcl"])
    result = gate.observe(repeated)

    assert result["localized"] is False
    assert result["reason"] == reason


def test_ros_source_clock_age_is_diagnostic_not_localization_freshness():
    gate = LocalizationGate(PROFILE)
    gate.start(None, now_monotonic=9.0)
    first = observation(tf_source_age_sec=-1.5, scan_source_age_sec=20.0)
    gate.observe(first)
    second = observation(receipt_monotonic=10.1, tf_source_age_sec=-1.5, scan_source_age_sec=20.0)
    second["amcl"] = {**second["amcl"], "receipt_monotonic": 10.1}

    result = gate.observe(second)

    assert result["localized"] is True
    assert result["reason"] == "converged"


def test_pose_jitter_resets_stability_window():
    gate = LocalizationGate(PROFILE)
    gate.start(None, now_monotonic=9.0)
    gate.observe(observation(receipt_monotonic=10.0))
    shifted = observation(receipt_monotonic=10.2)
    shifted["amcl"] = {**shifted["amcl"], "x": 1.2, "receipt_monotonic": 10.2}

    result = gate.observe(shifted)

    assert result["state"] != LOCALIZED
    assert result["sample_count"] == 1
    assert result["reason"] == "pose_not_stable"


def test_localized_gate_accepts_continuous_commanded_motion():
    gate = LocalizationGate(PROFILE)
    gate.start(None, now_monotonic=9.0)
    gate.observe(observation())
    second = observation(receipt_monotonic=10.1)
    second["amcl"] = {**second["amcl"], "receipt_monotonic": 10.1}
    assert gate.observe(second)["state"] == LOCALIZED

    moving = observation(receipt_monotonic=10.2)
    moving["amcl"] = {
        **moving["amcl"],
        "x": 1.12,
        "receipt_monotonic": 10.2,
    }
    result = gate.observe(moving)

    assert result["state"] == LOCALIZED
    assert result["localized"] is True
    assert result["reason"] == "converged"


def test_stale_scan_tf_and_missing_covariance_fail_closed():
    gate = LocalizationGate(PROFILE)
    gate.start(None)
    assert gate.observe(observation(scan_age_sec=2.0))["state"] != LOCALIZED
    assert gate.observe(observation(tf_age_sec=2.0))["state"] != LOCALIZED
    assert gate.observe(observation(amcl={"x": 1.0, "y": 2.0}))["state"] != LOCALIZED


def test_nonfinite_negative_sensor_values_fail_closed():
    gate = LocalizationGate(PROFILE)
    gate.start(None, now_monotonic=9.0)
    assert gate.observe(observation(scan_age_sec=-0.1))["reason"] == "scan_missing_or_stale"
    assert gate.observe(observation(tf_age_sec=float("nan")))["reason"] == "tf_missing_or_stale"
    invalid = observation()
    invalid["amcl"] = {
        **invalid["amcl"],
        "covariance": {"x": -0.1, "y": 0.1, "yaw": 0.1},
    }
    assert gate.observe(invalid)["reason"] == "amcl_covariance_missing"


def test_restart_clears_attempt_diagnostics():
    gate = LocalizationGate(PROFILE)
    gate.start(None, now_monotonic=9.0)
    gate.observe(observation())

    gate.start(None, now_monotonic=11.0)
    health = gate.health()

    assert health["covariance"] is None
    assert health["scan_age_sec"] is None
    assert health["tf_age_sec"] is None
    assert gate.last_pose is None


def test_kidnapped_jump_marks_lost():
    gate = LocalizationGate(PROFILE)
    gate.start(None, now_monotonic=9.0)
    gate.observe(observation())
    second = observation(receipt_monotonic=10.1)
    second["amcl"] = {**second["amcl"], "receipt_monotonic": 10.1}
    gate.observe(second)
    jumped = observation(receipt_monotonic=10.2)
    jumped["amcl"] = {**jumped["amcl"], "x": 9.0, "receipt_monotonic": 10.2}
    assert gate.observe(jumped)["state"] == LOST
