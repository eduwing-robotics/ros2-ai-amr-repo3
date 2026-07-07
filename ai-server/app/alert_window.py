from __future__ import annotations

from typing import Any

ALERT_WINDOW_REASON_CODES = {
    "DROPPED_ITEM_DETECTED",
    "LOW_PIXEL_BUDGET",
    "LOW_QUALITY_EVIDENCE",
}

DEFAULT_ALERT_WINDOW_PRE_ROLL_S = 1.0
DEFAULT_ALERT_WINDOW_POST_ROLL_S = 2.0
DEFAULT_ALERT_WINDOW_MAX_FRAMES = 30
DEFAULT_ALERT_WINDOW_RETENTION_HOURS = 24


def reason_requests_alert_window(reason_code: str) -> bool:
    """Return true when an advisory evaluation should carry sparse evidence hints."""

    return str(reason_code or "").upper() in ALERT_WINDOW_REASON_CODES


def build_alert_window_metadata(
    *,
    source: str,
    view: str,
    operation: str,
    reason_code: str,
    observed_at: str,
    pre_roll_s: float = DEFAULT_ALERT_WINDOW_PRE_ROLL_S,
    post_roll_s: float = DEFAULT_ALERT_WINDOW_POST_ROLL_S,
    max_frames: int = DEFAULT_ALERT_WINDOW_MAX_FRAMES,
    retention_hours: int = DEFAULT_ALERT_WINDOW_RETENTION_HOURS,
) -> dict[str, Any] | None:
    """Build bounded alert-window metadata without storing frames or touching Main.

    The metadata is intentionally small and advisory. It tells a connector or
    later sidecar how much sparse proof context is worth retaining, while
    avoiding a default policy of increasing continuous AI FPS/imgsz.
    """

    normalized_reason = str(reason_code or "").upper()
    if normalized_reason not in ALERT_WINDOW_REASON_CODES:
        return None
    if pre_roll_s < 0 or post_roll_s < 0:
        raise ValueError("alert-window roll durations must be non-negative")
    if max_frames <= 0:
        raise ValueError("alert-window max_frames must be positive")
    if retention_hours <= 0:
        raise ValueError("alert-window retention_hours must be positive")

    return {
        "policy_version": "gopro-sparse-alert-window.v1",
        "source": source,
        "view": view,
        "operation": operation,
        "trigger_reason_code": normalized_reason,
        "observed_at": observed_at,
        "pre_roll_s": round(float(pre_roll_s), 3),
        "post_roll_s": round(float(post_roll_s), 3),
        "max_frames": int(max_frames),
        "retention_hours": int(retention_hours),
        "advisory_only": True,
    }


__all__ = [
    "ALERT_WINDOW_REASON_CODES",
    "build_alert_window_metadata",
    "reason_requests_alert_window",
]
