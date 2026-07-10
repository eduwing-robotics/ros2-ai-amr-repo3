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
        "max_covariance_x": 0.2,
        "max_covariance_y": 0.2,
        "max_covariance_yaw": 0.3,
        "consecutive_samples": 2,
        "convergence_timeout_sec": 10.0,
        "persisted_seed_max_age_sec": 60.0,
        "kidnapped_jump_distance_m": 1.0,
    }
}


def observation(**overrides):
    value = {
        "amcl": {"x": 1.0, "y": 2.0, "covariance": {"x": 0.1, "y": 0.1, "yaw": 0.1}, "header_stamp_sec": 5.0},
        "scan_age_sec": 0.1,
        "tf_age_sec": 0.1,
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
    gate.start(None)
    assert gate.observe(observation())["state"] != LOCALIZED
    assert gate.observe(observation(receipt_monotonic=10.1))["state"] == LOCALIZED


def test_stale_scan_tf_and_missing_covariance_fail_closed():
    gate = LocalizationGate(PROFILE)
    gate.start(None)
    assert gate.observe(observation(scan_age_sec=2.0))["state"] != LOCALIZED
    assert gate.observe(observation(tf_age_sec=2.0))["state"] != LOCALIZED
    assert gate.observe(observation(amcl={"x": 1.0, "y": 2.0}))["state"] != LOCALIZED


def test_kidnapped_jump_marks_lost():
    gate = LocalizationGate(PROFILE)
    gate.start(None)
    gate.observe(observation())
    gate.observe(observation(receipt_monotonic=10.1))
    assert gate.observe(observation(amcl={"x": 9.0, "y": 2.0, "covariance": {"x": 0.1, "y": 0.1, "yaw": 0.1}}, receipt_monotonic=10.2))["state"] == LOST
