"""Robot capability and lift-readiness helpers."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from fastapi import HTTPException

from nav_app.config import active_robot_profile
from nav_app.models import MovementStep
from nav_app.runtime import runtime


def profile_capabilities(profile: Mapping[str, Any] | None = None) -> list[str]:
    profile = profile or active_robot_profile()
    capabilities = profile.get("capabilities") or []
    return [str(capability) for capability in capabilities if isinstance(capability, str)]


def has_capability(capability: str, profile: Mapping[str, Any] | None = None) -> bool:
    return capability in profile_capabilities(profile)


def missing_capability_error(capability: str) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": f"robot_missing_capability:{capability}",
            "message": f"active robot profile does not support capability: {capability}",
            "capability": capability,
        },
    )


def ensure_capability(capability: str, profile: Mapping[str, Any] | None = None) -> None:
    if not has_capability(capability, profile):
        raise missing_capability_error(capability)


def required_capabilities_for_step(step: MovementStep) -> Sequence[str]:
    action = str(step.action).strip().lower()
    if action == "dock_transfer":
        return ("lift",)
    if action == "aruco_align" and str(step.payload.get("final", "hold")).lower() == "hold":
        # A hold alignment may be used for parking/charge, but only lift-capable
        # profiles may request the physical fork-insert default.
        insert = step.payload.get("fork_insert_on_hold", step.payload.get("park_fork_insert", False))
        if str(insert).strip().lower() not in ("", "0", "false", "no", "off", "none"):
            return ("lift",)
    return ()


def ensure_steps_supported(steps: Iterable[MovementStep], profile: Mapping[str, Any] | None = None) -> None:
    profile = profile or active_robot_profile()
    for step in steps:
        for capability in required_capabilities_for_step(step):
            ensure_capability(capability, profile)


def _publisher_has_subscriber(publisher: Any) -> bool:
    if publisher is None or not hasattr(publisher, "get_subscription_count"):
        return False
    try:
        return int(publisher.get_subscription_count()) > 0
    except Exception:
        return False


def active_lift_status(profile: Mapping[str, Any] | None = None) -> dict[str, Any]:
    profile = profile or active_robot_profile()
    lift = profile.get("lift") if isinstance(profile.get("lift"), Mapping) else {}
    enabled = bool(lift.get("enabled", False))
    lift_capable = has_capability("lift", profile)
    client = getattr(runtime, "lift_client", None)
    base = {
        "enabled": enabled,
        "capable": lift_capable,
        "ready": False,
        "reason": "ok",
    }
    if not lift_capable:
        return {**base, "reason": "robot_missing_capability:lift"}
    if not enabled:
        return {**base, "reason": "lift_disabled"}
    if client is None:
        return {**base, "reason": "lift_client_not_initialized"}
    if not getattr(client, "enabled", False):
        return {**base, "reason": "lift_client_disabled"}

    move_ready = _publisher_has_subscriber(getattr(client, "_pub_move", None))
    home_ready = _publisher_has_subscriber(getattr(client, "_pub_home", None))
    if not (move_ready and home_ready):
        return {**base, "reason": "lift_bridge_subscriber_not_ready", "bridge_subscribers": {"cmd_move": move_ready, "cmd_home": home_ready}}

    position_ready = getattr(client, "position_mm", None) is not None
    direction_ready = getattr(client, "direction", None) is not None
    limit_ready = getattr(client, "limit_lower", None) is not None
    telemetry_ready = position_ready and direction_ready and limit_ready
    if not telemetry_ready:
        return {
            **base,
            "reason": "lift_telemetry_not_ready",
            "telemetry": {"position": position_ready, "direction": direction_ready, "limit_lower": limit_ready},
        }

    telemetry_health = client.telemetry_health() if hasattr(client, "telemetry_health") else {"ready": True, "reason": "ok"}
    if not telemetry_health.get("ready", False):
        return {**base, "reason": f"lift_{telemetry_health.get('reason', 'telemetry_stale')}", "telemetry": telemetry_health}

    status = client.status() if hasattr(client, "status") else {}
    return {**base, "ready": True, "reason": "ok", **status, "telemetry": telemetry_health, "capable": lift_capable}


def ensure_lift_ready_for_dock_transfer(
    profile: Mapping[str, Any] | None = None,
    *,
    simulation: bool = False,
) -> None:
    status = active_lift_status(profile)
    if status["ready"]:
        return
    if simulation and status["capable"] and status["enabled"]:
        return
    reason = str(status.get("reason") or "lift_not_ready")
    if reason.startswith("robot_missing_capability"):
        raise RuntimeError(reason)
    raise RuntimeError(f"lift_not_ready:{reason}")
