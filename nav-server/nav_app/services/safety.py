"""Fail-safe physical-stop closure shared by Nav command entry points."""
from __future__ import annotations

import logging

from nav_app.runtime import runtime

logger = logging.getLogger(__name__)


def stop_active_motion() -> dict[str, bool]:
    """Cancel autonomy and stop base/lift motion without latching E-stop."""
    navigator = runtime.navigator
    nav_cancelled = False
    base_stopped = False
    if navigator:
        try:
            nav_cancelled = navigator.nav.cancelTask() is not False
        except Exception:
            logger.exception("failed to cancel Nav2 during motion stop")
        try:
            base_stopped = navigator.publish_stop_velocity() is not False
        except Exception:
            logger.exception("failed to publish base stop during motion stop")
    lift_client = runtime.lift_client
    lift_required = bool(lift_client and getattr(lift_client, "enabled", False))
    lift_stopped = not lift_required
    if lift_required:
        try:
            lift_stopped = lift_client.stop() is not False
        except Exception:
            logger.exception("failed to stop lift during motion stop")
    return {
        "nav_cancelled": nav_cancelled,
        "base_stopped": base_stopped,
        "lift_stopped": lift_stopped,
        "confirmed": nav_cancelled and base_stopped and lift_stopped,
    }


def engage_estop() -> None:
    """Latch E-stop, then stop Nav2, base velocity, and an enabled lift.

    The operation is deliberately idempotent.  A lift bridge failure is logged
    but never prevents the base-stop and emergency latch from taking effect.
    """
    if runtime.navigator:
        runtime.navigator.safety.enable_estop()
    stop_active_motion()
