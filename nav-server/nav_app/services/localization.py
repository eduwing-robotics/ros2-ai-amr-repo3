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
    "max_amcl_age_sec": 1.0,
    "max_covariance_x": 0.25,
    "max_covariance_y": 0.25,
    "max_covariance_yaw": 0.35,
    "consecutive_samples": 3,
    "convergence_timeout_sec": 30.0,
    "persisted_seed_max_age_sec": 3600.0,
    "kidnapped_jump_distance_m": 1.5,
    "stable_min_duration_sec": 3.0,
    "max_pose_jitter_m": 0.08,
    "max_yaw_jitter_rad": 0.15,
}

GLOBAL_SEARCH_DEFAULTS = {
    "default_strategy": "observe_only",
    "allowed_strategies": ["observe_only", "bounded_linear_wiggle"],
    "motion_requires_explicit_request": True,
    "linear_speed_mps": 0.04,
    "max_step_m": 0.05,
    "max_total_m": 0.20,
    "min_front_clearance_m": 0.60,
    "min_rear_clearance_m": 0.60,
    "max_scan_age_sec": 1.0,
    "max_tf_age_sec": 1.0,
    "coarse_nomotion_interval_sec": 0.75,
    "fine_nomotion_interval_sec": 1.0,
    "nomotion_update_timeout_sec": 120.0,
    "coarse_covariance_limits": {"x": 0.50, "y": 0.50, "yaw": 1.0},
    "fine_fallback_covariance_limits": {"x": 0.40, "y": 0.40, "yaw": 0.70},
    "coarse_consecutive_samples": 3,
    "fine_consecutive_samples": 10,
    "coarse_stable_min_duration_sec": 1.5,
    "fine_stable_min_duration_sec": 3.0,
    "coarse_max_pose_jitter_m": 0.15,
    "coarse_max_yaw_jitter_rad": 0.35,
    "fine_max_pose_jitter_m": 0.08,
    "fine_max_yaw_jitter_rad": 0.15,
    "fine_fallback_max_pose_jitter_m": 0.12,
    "fine_fallback_max_yaw_jitter_rad": 0.25,
    "fine_fallback_breaches": 3,
    "max_global_reinitializations": 2,
}


def localization_config(profile: Mapping[str, Any]) -> Dict[str, Any]:
    return {**DEFAULTS, **dict(profile.get("localization") or {})}


def global_search_config(profile: Mapping[str, Any]) -> Dict[str, Any]:
    localization = dict(profile.get("localization") or {})
    return {**GLOBAL_SEARCH_DEFAULTS, **dict(localization.get("global_search") or {})}


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
        self.amcl_age_sec: Optional[float] = None
        self.last_pose: Optional[Dict[str, float]] = None
        self.last_amcl_receipt_monotonic: Optional[float] = None
        self.stable_started_monotonic: Optional[float] = None
        self.pose_window = []
        self.pose_jitter_m: Optional[float] = None
        self.yaw_jitter_rad: Optional[float] = None

    def start(self, seed: Any, now_monotonic: Optional[float] = None, now_epoch_sec: Optional[float] = None) -> str:
        self.started_monotonic = time.monotonic() if now_monotonic is None else now_monotonic
        valid, reason = validate_persisted_seed(seed, self.profile, now_epoch_sec)
        self.sample_count = 0
        self.last_amcl_receipt_monotonic = None
        self.stable_started_monotonic = None
        self.pose_window = []
        self.pose_jitter_m = None
        self.yaw_jitter_rad = None
        self.last_covariance = None
        self.scan_age_sec = None
        self.tf_age_sec = None
        self.amcl_age_sec = None
        self.last_pose = None
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
        if (
            self.scan_age_sec is None
            or self.scan_age_sec < 0
            or self.scan_age_sec > float(self.config["max_scan_age_sec"])
        ):
            return self._degrade("scan_missing_or_stale")
        if (
            self.tf_age_sec is None
            or self.tf_age_sec < 0
            or self.tf_age_sec > float(self.config["max_tf_age_sec"])
        ):
            return self._degrade("tf_missing_or_stale")
        if not observation.get("tf_continuous", False):
            return self._degrade("tf_discontinuous")
        amcl = observation.get("amcl")
        if not isinstance(amcl, Mapping) or not isinstance(amcl.get("covariance"), Mapping):
            return self._degrade("amcl_covariance_missing")
        sample_receipt = _number(amcl.get("receipt_monotonic"))
        if sample_receipt is None:
            self.amcl_age_sec = None
            return self._degrade("amcl_missing_or_stale")
        self.amcl_age_sec = now - sample_receipt
        duplicate_sample = (
            self.last_amcl_receipt_monotonic is not None
            and sample_receipt <= self.last_amcl_receipt_monotonic
        )
        if (
            not math.isfinite(self.amcl_age_sec)
            or self.amcl_age_sec < 0
        ):
            return self._degrade("amcl_missing_or_stale")
        if self.amcl_age_sec > float(self.config["max_amcl_age_sec"]):
            if self.state == LOCALIZED and duplicate_sample:
                return self.health()
            return self._degrade("amcl_missing_or_stale")
        covariance = {key: _number(amcl["covariance"].get(key)) for key in ("x", "y", "yaw")}
        if any(value is None or value < 0 for value in covariance.values()):
            return self._degrade("amcl_covariance_missing")
        self.last_covariance = covariance  # type: ignore[assignment]
        if any(covariance[key] > float(self.config[f"max_covariance_{key}"]) for key in covariance):
            self.sample_count = 0
            self.stable_started_monotonic = None
            self.pose_window = []
            self.state, self.reason = CONVERGING, "covariance_not_converged"
            return self.health()
        pose = {key: _number(amcl.get(key)) for key in ("x", "y", "yaw")}
        if any(value is None for value in pose.values()):
            return self._degrade("amcl_pose_invalid")
        if self.started_monotonic is not None and sample_receipt < self.started_monotonic:
            self.state, self.reason = CONVERGING, "awaiting_post_search_sample"
            return self.health()
        if duplicate_sample:
            if self.state == LOCALIZED:
                return self.health()
            self.state, self.reason = CONVERGING, "awaiting_new_amcl_sample"
            return self.health()
        if self.state == LOCALIZED and self.last_pose and math.hypot(pose["x"] - self.last_pose["x"], pose["y"] - self.last_pose["y"]) > float(self.config["kidnapped_jump_distance_m"]):  # type: ignore[operator]
            self.sample_count, self.state, self.reason = 0, LOST, "kidnapped_pose_jump"
            self.last_pose = pose  # type: ignore[assignment]
            return self.health()
        self.last_amcl_receipt_monotonic = sample_receipt
        self.last_pose = pose  # type: ignore[assignment]
        self.pose_window.append(pose)
        limit = int(self.config["consecutive_samples"])
        self.pose_window = self.pose_window[-limit:]
        anchor = self.pose_window[0]
        self.pose_jitter_m = max(
            math.hypot(item["x"] - anchor["x"], item["y"] - anchor["y"])
            for item in self.pose_window
        )
        self.yaw_jitter_rad = max(
            abs(math.atan2(math.sin(item["yaw"] - anchor["yaw"]), math.cos(item["yaw"] - anchor["yaw"])))
            for item in self.pose_window
        )
        if (
            self.pose_jitter_m > float(self.config["max_pose_jitter_m"])
            or self.yaw_jitter_rad > float(self.config["max_yaw_jitter_rad"])
        ):
            self.pose_window = [pose]
            self.sample_count = 1
            self.stable_started_monotonic = sample_receipt
            self.state, self.reason = CONVERGING, "pose_not_stable"
            return self.health()
        if self.stable_started_monotonic is None:
            self.stable_started_monotonic = sample_receipt
        self.sample_count = len(self.pose_window)
        stable_duration = max(0.0, sample_receipt - self.stable_started_monotonic)
        if self.sample_count >= limit and stable_duration >= float(self.config["stable_min_duration_sec"]):
            self.state, self.reason = LOCALIZED, "converged"
        else:
            self.state, self.reason = CONVERGING, "awaiting_stable_samples"
        return self.health()

    def _degrade(self, reason: str) -> Dict[str, Any]:
        self.sample_count = 0
        self.stable_started_monotonic = None
        self.pose_window = []
        if self.state != FAILED:
            self.state = DEGRADED
        self.reason = reason
        return self.health()

    def ready(self) -> bool:
        return self.state == LOCALIZED

    def reject(self, reason: str) -> Dict[str, Any]:
        """Fail closed when an external localization admission check fails."""
        return self._degrade(str(reason))

    def health(self) -> Dict[str, Any]:
        stable_duration = None
        if self.stable_started_monotonic is not None and self.last_amcl_receipt_monotonic is not None:
            stable_duration = max(0.0, self.last_amcl_receipt_monotonic - self.stable_started_monotonic)
        return {"state": self.state, "map_id": self.config.get("map_id"), "covariance": self.last_covariance,
                "sample_count": self.sample_count, "scan_age_sec": self.scan_age_sec, "tf_age_sec": self.tf_age_sec,
                "amcl_age_sec": self.amcl_age_sec,
                "stable_duration_sec": stable_duration, "pose_jitter_m": self.pose_jitter_m,
                "yaw_jitter_rad": self.yaw_jitter_rad, "reason": self.reason, "localized": self.ready()}


def _number(value: Any) -> Optional[float]:
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (TypeError, ValueError):
        return None
