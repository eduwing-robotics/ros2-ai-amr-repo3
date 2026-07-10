"""ROS-free localization admission state machine.

The gate deliberately consumes receipt-monotonic freshness data rather than
comparing ROS time to wall clock: simulation and `/use_sim_time` make those
clocks incomparable.
"""
from __future__ import annotations

import math
import time
from typing import Any, Dict, Mapping, Optional, Tuple

UNLOCALIZED = "UNLOCALIZED"
SEEDING = "SEEDING"
GLOBAL_SEARCH = "GLOBAL_SEARCH"
CONVERGING = "CONVERGING"
LOCALIZED = "LOCALIZED"
DEGRADED = "DEGRADED"
LOST = "LOST"
FAILED = "FAILED"
STATES = (UNLOCALIZED, SEEDING, GLOBAL_SEARCH, CONVERGING, LOCALIZED, DEGRADED, LOST, FAILED)

DEFAULTS = {
    "max_scan_age_sec": 1.0,
    "max_tf_age_sec": 1.0,
    "max_covariance_x": 0.25,
    "max_covariance_y": 0.25,
    "max_covariance_yaw": 0.35,
    "consecutive_samples": 3,
    "convergence_timeout_sec": 30.0,
    "persisted_seed_max_age_sec": 3600.0,
    "kidnapped_jump_distance_m": 1.5,
}


def localization_config(profile: Mapping[str, Any]) -> Dict[str, Any]:
    return {**DEFAULTS, **dict(profile.get("localization") or {})}


def validate_persisted_seed(seed: Any, profile: Mapping[str, Any], now_epoch_sec: Optional[float] = None) -> Tuple[bool, str]:
    """Validate only; persistence remains an explicitly pluggable interface."""
    if not isinstance(seed, Mapping):
        return False, "seed_absent"
    config = localization_config(profile)
    if seed.get("map_id") != config.get("map_id"):
        return False, "seed_map_id_mismatch"
    if seed.get("map_metadata_identity") != config.get("map_metadata_identity"):
        return False, "seed_map_metadata_mismatch"
    try:
        saved_at = float(seed["saved_at_epoch_sec"])
    except (KeyError, TypeError, ValueError):
        return False, "seed_saved_at_missing"
    age = (time.time() if now_epoch_sec is None else now_epoch_sec) - saved_at
    if age < 0 or age > float(config["persisted_seed_max_age_sec"]):
        return False, "seed_stale"
    return True, "ok"


class LocalizationGate:
    def __init__(self, profile: Mapping[str, Any]) -> None:
        self.profile = profile
        self.config = localization_config(profile)
        self.state = UNLOCALIZED
        self.reason = "not_started"
        self.sample_count = 0
        self.started_monotonic: Optional[float] = None
        self.last_covariance: Optional[Dict[str, float]] = None
        self.scan_age_sec: Optional[float] = None
        self.tf_age_sec: Optional[float] = None
        self.last_pose: Optional[Dict[str, float]] = None

    def start(self, seed: Any, now_monotonic: Optional[float] = None, now_epoch_sec: Optional[float] = None) -> str:
        self.started_monotonic = time.monotonic() if now_monotonic is None else now_monotonic
        valid, reason = validate_persisted_seed(seed, self.profile, now_epoch_sec)
        self.sample_count = 0
        self.reason = "seed_accepted" if valid else reason
        self.state = SEEDING if valid else GLOBAL_SEARCH
        return self.state

    def observe(self, observation: Mapping[str, Any], now_monotonic: Optional[float] = None) -> Dict[str, Any]:
        now = float(observation.get("receipt_monotonic", time.monotonic() if now_monotonic is None else now_monotonic))
        self.scan_age_sec = _number(observation.get("scan_age_sec"))
        self.tf_age_sec = _number(observation.get("tf_age_sec"))
        if self.started_monotonic is not None and now - self.started_monotonic > float(self.config["convergence_timeout_sec"]):
            if self.state != LOCALIZED:
                self.state, self.reason = FAILED, "convergence_timeout"
                return self.health()
        if self.scan_age_sec is None or self.scan_age_sec > float(self.config["max_scan_age_sec"]):
            return self._degrade("scan_missing_or_stale")
        if self.tf_age_sec is None or self.tf_age_sec > float(self.config["max_tf_age_sec"]):
            return self._degrade("tf_missing_or_stale")
        if not observation.get("tf_continuous", False):
            return self._degrade("tf_discontinuous")
        amcl = observation.get("amcl")
        if not isinstance(amcl, Mapping) or not isinstance(amcl.get("covariance"), Mapping):
            return self._degrade("amcl_covariance_missing")
        covariance = {key: _number(amcl["covariance"].get(key)) for key in ("x", "y", "yaw")}
        if any(value is None for value in covariance.values()):
            return self._degrade("amcl_covariance_missing")
        self.last_covariance = covariance  # type: ignore[assignment]
        if any(covariance[key] > float(self.config[f"max_covariance_{key}"]) for key in covariance):
            self.sample_count = 0
            self.state, self.reason = CONVERGING, "covariance_not_converged"
            return self.health()
        pose = {key: _number(amcl.get(key)) for key in ("x", "y")}
        if any(value is None for value in pose.values()):
            return self._degrade("amcl_pose_invalid")
        if self.state == LOCALIZED and self.last_pose and math.hypot(pose["x"] - self.last_pose["x"], pose["y"] - self.last_pose["y"]) > float(self.config["kidnapped_jump_distance_m"]):  # type: ignore[operator]
            self.sample_count, self.state, self.reason = 0, LOST, "kidnapped_pose_jump"
            self.last_pose = pose  # type: ignore[assignment]
            return self.health()
        self.last_pose = pose  # type: ignore[assignment]
        self.sample_count += 1
        if self.sample_count >= int(self.config["consecutive_samples"]):
            self.state, self.reason = LOCALIZED, "converged"
        else:
            self.state, self.reason = CONVERGING, "awaiting_consecutive_samples"
        return self.health()

    def _degrade(self, reason: str) -> Dict[str, Any]:
        self.sample_count = 0
        if self.state != FAILED:
            self.state = DEGRADED
        self.reason = reason
        return self.health()

    def ready(self) -> bool:
        return self.state == LOCALIZED

    def health(self) -> Dict[str, Any]:
        return {"state": self.state, "map_id": self.config.get("map_id"), "covariance": self.last_covariance,
                "sample_count": self.sample_count, "scan_age_sec": self.scan_age_sec, "tf_age_sec": self.tf_age_sec,
                "reason": self.reason, "localized": self.ready()}


def _number(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
