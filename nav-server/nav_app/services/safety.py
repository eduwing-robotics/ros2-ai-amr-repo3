"""Fail-safe physical-stop closure shared by Nav command entry points."""
from __future__ import annotations

import logging

from nav_app.runtime import runtime

logger = logging.getLogger(__name__)


def engage_estop() -> None:
    """Stop Nav2, base velocity, and an enabled lift without weakening E-stop.

    The operation is deliberately idempotent.  A lift bridge failure is logged
    but never prevents the base-stop and emergency latch from taking effect.
    """
    navigator = runtime.navigator
    if navigator:
        navigator.safety.enable_estop()
        try:
            navigator.nav.cancelTask()
        except Exception:
            logger.exception("failed to cancel Nav2 during E-stop")
        try:
            navigator.publish_stop_velocity()
        except Exception:
            logger.exception("failed to publish base stop during E-stop")
    lift_client = runtime.lift_client
    if lift_client and getattr(lift_client, "enabled", False):
        try:
            lift_client.stop()
        except Exception:
            logger.exception("failed to stop lift during E-stop")
