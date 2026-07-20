"""Physical and synthetic-HIL lift backend selection and provenance."""

from __future__ import annotations

import json
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Optional

from nav_app.services.lift_client import LiftClient
from nav_app.services.lift_phases import (
    resolve_carry_height_mm,
    resolve_post_insert_height_mm,
    resolve_pre_insert_height_mm,
)


PHYSICAL_LIFT_NOT_VERIFIED = "PHYSICAL_LIFT_NOT_VERIFIED"
SYNTHETIC_HIL_ALLOW_ENV = "SF_NAV_ALLOW_SYNTHETIC_HIL"
RESOLVED_PROFILE_ENV = "SF_NAV_RESOLVED_PROFILE_PATH"


def _env_enabled(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def resolved_lift_backend(
    resolved_profile: Mapping[str, Any] | None,
    *,
    robot_id: str | None = None,
    robot_profile: Mapping[str, Any] | None = None,
) -> str:
    """Resolve one robot's explicit lift backend, with a legacy-safe fallback."""
    if isinstance(resolved_profile, Mapping):
        backends = resolved_profile.get("lift_backends")
        selected_id = robot_id or os.getenv("ROBOT_ID")
        if not selected_id:
            robots = resolved_profile.get("robots")
            if isinstance(robots, list) and len(robots) == 1 and isinstance(robots[0], Mapping):
                selected_id = str(robots[0].get("robot_id") or "")
        if isinstance(backends, Mapping) and selected_id and backends.get(selected_id) in {
            "disabled",
            "virtual",
            "physical",
        }:
            return str(backends[selected_id])

    # Resolved profiles produced before the common backend contract remain
    # readable during a rolling update, but never gain a capability.
    if isinstance(resolved_profile, Mapping) and resolved_profile.get("execution_class") == "synthetic_hil":
        return "virtual"
    lift = robot_profile.get("lift") if isinstance(robot_profile, Mapping) else None
    return "physical" if isinstance(lift, Mapping) and lift.get("enabled") is True else "disabled"


def load_resolved_runtime_profile(path: str | Path | None = None) -> Optional[dict[str, Any]]:
    """Load the immutable launcher snapshot selected for this process.

    ``sf_nav.sh`` resolves and validates the mutable manifest/robot files before
    launch, then writes this private snapshot under the run directory.  Runtime
    health and lift requests must keep using that startup contract even when an
    operator edits the repository for the next run.
    """
    selected = path or os.getenv(RESOLVED_PROFILE_ENV)
    if not selected:
        return None
    resolved_path = Path(selected)
    try:
        value = json.loads(resolved_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"invalid resolved runtime profile: {resolved_path}") from exc
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise RuntimeError("invalid resolved runtime profile schema")
    profile_id = value.get("profile_id")
    if not isinstance(profile_id, str) or not profile_id:
        raise RuntimeError("resolved runtime profile must name a profile_id")
    selection_source = value.get("selection_source")
    if selection_source not in {"cli", "environment", "manifest_default"}:
        raise RuntimeError("resolved runtime profile has invalid selection_source")
    robots = value.get("robots")
    if not isinstance(robots, list) or not robots:
        raise RuntimeError("resolved runtime profile must contain selected robots")
    selected_robot_ids: set[str] = set()
    for robot in robots:
        robot_id = robot.get("robot_id") if isinstance(robot, Mapping) else None
        if not isinstance(robot_id, str) or not robot_id or robot_id in selected_robot_ids:
            raise RuntimeError("resolved runtime profile contains invalid selected robots")
        selected_robot_ids.add(robot_id)
    active_robot_id = os.getenv("ROBOT_ID", "tb3_burger_01")
    if active_robot_id not in selected_robot_ids:
        raise RuntimeError(f"resolved runtime profile does not select active robot: {active_robot_id}")
    return value


def synthetic_hil_admitted(
    resolved_profile: Mapping[str, Any] | None = None,
    environment: Mapping[str, str] | None = None,
) -> bool:
    """Return true only when both the validated profile and process gate opt in."""
    resolved = resolved_profile if resolved_profile is not None else load_resolved_runtime_profile()
    env = os.environ if environment is None else environment
    virtual_lift = resolved.get("virtual_lift") if isinstance(resolved, Mapping) else None
    return bool(
        isinstance(resolved, Mapping)
        and resolved.get("execution_class") == "synthetic_hil"
        and resolved.get("evidence_class") == "nonphysical"
        and isinstance(virtual_lift, Mapping)
        and virtual_lift.get("enabled") is True
        and virtual_lift.get("backend") == "deterministic"
        and resolved_lift_backend(resolved) == "virtual"
        and _env_enabled(env.get(SYNTHETIC_HIL_ALLOW_ENV))
    )


def require_synthetic_hil_admission(
    resolved_profile: Mapping[str, Any] | None = None,
    environment: Mapping[str, str] | None = None,
) -> Mapping[str, Any]:
    resolved = resolved_profile if resolved_profile is not None else load_resolved_runtime_profile()
    if not isinstance(resolved, Mapping) or resolved.get("execution_class") != "synthetic_hil":
        raise RuntimeError("synthetic_hil_profile_required")
    if resolved.get("evidence_class") != "nonphysical":
        raise RuntimeError("synthetic_hil_requires_nonphysical_evidence")
    virtual_lift = resolved.get("virtual_lift")
    if not isinstance(virtual_lift, Mapping) or virtual_lift.get("enabled") is not True:
        raise RuntimeError("synthetic_hil_virtual_lift_required")
    if virtual_lift.get("backend") != "deterministic":
        raise RuntimeError("synthetic_hil_backend_not_supported")
    if resolved_lift_backend(resolved) != "virtual":
        raise RuntimeError("synthetic_hil_virtual_backend_required")
    env = os.environ if environment is None else environment
    if not _env_enabled(env.get(SYNTHETIC_HIL_ALLOW_ENV)):
        raise RuntimeError("synthetic_hil_process_gate_required")
    return resolved


def lift_provenance(
    resolved_profile: Mapping[str, Any] | None = None,
    backend: Any = None,
) -> dict[str, Any]:
    resolved = resolved_profile if resolved_profile is not None else load_resolved_runtime_profile()
    execution_class = str(resolved.get("execution_class", "live")) if isinstance(resolved, Mapping) else "live"
    evidence_class = str(resolved.get("evidence_class", "physical")) if isinstance(resolved, Mapping) else "physical"
    backend_name = getattr(backend, "backend_name", resolved_lift_backend(resolved))
    return {
        "execution_class": execution_class,
        "evidence_class": evidence_class,
        "lift_backend": backend_name,
        # Live execution and physical capability describe runtime intent; neither
        # is evidence that a physical lift was actually verified.
        "physical_lift_verified": False,
        "physical_lift_reason": PHYSICAL_LIFT_NOT_VERIFIED,
        "lift_evidence_reason": PHYSICAL_LIFT_NOT_VERIFIED,
    }


class VirtualLiftBackend:
    """Deterministic, ROS-free lift backend for lift-only synthetic HIL."""

    backend_name = "virtual"
    enabled = True

    def __init__(self, config: Mapping[str, Any] | None = None):
        self.config = deepcopy(dict(config or {}))
        self.config["enabled"] = True
        self.position_mm = float(self.config.get("initial_position_mm", 0.0))
        self.direction = "STOP"
        self.limit_lower = self.position_mm <= 0.0
        self.stopped = False
        self.transitions: list[dict[str, Any]] = []

    def telemetry_health(self, max_age_sec: Optional[float] = None) -> dict[str, Any]:
        return {
            "ready": True,
            "reason": "ok",
            "backend": self.backend_name,
            "sequence": len(self.transitions),
        }

    def status(self) -> dict[str, Any]:
        return {
            "enabled": True,
            "ready": True,
            "backend": self.backend_name,
            "position_mm": self.position_mm,
            "direction": self.direction,
            "limit_lower": self.limit_lower,
            "stopped": self.stopped,
            "transitions": deepcopy(self.transitions),
            "telemetry": self.telemetry_health(),
            **lift_provenance(
                {
                    "execution_class": "synthetic_hil",
                    "evidence_class": "nonphysical",
                },
                self,
            ),
        }

    def _record(self, operation: str, **details: Any) -> dict[str, Any]:
        transition = {"sequence": len(self.transitions) + 1, "operation": operation, **details}
        self.transitions.append(transition)
        return self.status()

    def move_to(self, target_mm: float, **_kwargs: Any) -> dict[str, Any]:
        self.position_mm = float(target_mm)
        self.direction = "STOP"
        self.limit_lower = self.position_mm <= 0.0
        self.stopped = False
        return self._record("move_to", target_mm=self.position_mm)

    def move_to_if_needed(self, target_mm: float, **kwargs: Any) -> dict[str, Any]:
        return self.move_to(target_mm, **kwargs)

    def home(self, **_kwargs: Any) -> dict[str, Any]:
        self.position_mm = 0.0
        self.direction = "STOP"
        self.limit_lower = True
        self.stopped = False
        return self._record("home", target_mm=0.0)

    def stop(self) -> None:
        self.direction = "STOP"
        self.stopped = True
        self._record("stop")

    def execute_transfer(self, action: str, level: int, payload: MutableMapping[str, Any]) -> dict[str, Any]:
        action = str(action).lower()
        if action not in {"load", "unload"}:
            raise ValueError(f"unsupported virtual lift action: {action}")
        if action == "unload" and bool(payload.get("home_on_unload", self.config.get("home_on_unload", False))):
            result = self.home()
        else:
            result = self.move_to(resolve_post_insert_height_mm(action, level, payload, self.config))
        self.transitions[-1].update({"phase": "transfer", "action": action, "level": int(level)})
        return result

    def execute_pre_insert(self, action: str, level: int, payload: MutableMapping[str, Any]) -> Optional[dict[str, Any]]:
        target = resolve_pre_insert_height_mm(action, level, payload, self.config)
        if target is None:
            return None
        result = self.move_to(target)
        self.transitions[-1].update({"phase": "pre_insert", "action": str(action), "level": int(level)})
        return result

    def execute_carry_after_load(self, action: str, level: int, payload: MutableMapping[str, Any]) -> Optional[dict[str, Any]]:
        target = resolve_carry_height_mm(action, level, payload, self.config)
        if target is None:
            return None
        result = self.move_to(target)
        self.transitions[-1].update({"phase": "carry", "action": str(action), "level": int(level)})
        return result


class DisabledLiftBackend:
    """Explicit no-lift backend; avoids creating unused ROS lift publishers."""

    backend_name = "disabled"
    enabled = False

    def status(self) -> dict[str, Any]:
        return {
            "enabled": False,
            "ready": False,
            "backend": self.backend_name,
            "reason": "lift_disabled",
            **lift_provenance(backend=self),
        }

    def telemetry_health(self, max_age_sec: Optional[float] = None) -> dict[str, Any]:
        del max_age_sec
        return {"ready": False, "reason": "lift_disabled", "backend": self.backend_name}

    def stop(self) -> None:
        return None

    @staticmethod
    def _disabled(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("lift_disabled")

    move_to = _disabled
    move_to_if_needed = _disabled
    home = _disabled
    execute_transfer = _disabled
    execute_pre_insert = _disabled
    execute_carry_after_load = _disabled

def create_lift_backend(
    node: Any,
    robot_profile: Mapping[str, Any],
    *,
    resolved_profile: Mapping[str, Any] | None = None,
    environment: Mapping[str, str] | None = None,
) -> LiftClient | VirtualLiftBackend | DisabledLiftBackend:
    resolved = resolved_profile if resolved_profile is not None else load_resolved_runtime_profile()
    backend = resolved_lift_backend(
        resolved,
        robot_id=str(robot_profile.get("robot_id") or os.getenv("ROBOT_ID") or "") or None,
        robot_profile=robot_profile,
    )
    if backend == "virtual":
        require_synthetic_hil_admission(resolved, environment)
        config = deepcopy(dict(robot_profile.get("lift") or {}))
        config.update(dict(resolved.get("virtual_lift") or {}))
        return VirtualLiftBackend(config)
    if backend == "physical":
        return LiftClient(node, dict(robot_profile.get("lift") or {}))
    return DisabledLiftBackend()
