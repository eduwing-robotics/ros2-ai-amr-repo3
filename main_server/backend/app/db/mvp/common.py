from __future__ import annotations

from typing import Any

ACTIVE_TASK_STATUSES = ("CREATED", "QUEUED", "ASSIGNED", "RUNNING")
# 슬롯(층)당 파레트 1개만 둔다(다른 품목 혼적 금지). quantity는 파레트에 실린 물품 개수 표기.
DEFAULT_FLOOR = 1
MAP_MARKER_TYPES = ("inbound", "outbound", "storage", "home", "charge", "dock", "transit", "scan")
_WAYPOINT_TO_LOCATION = {"approach": "scan", "move": "dock", "pickup": "dock", "dropoff": "dock"}
_LOCATION_TO_WAYPOINT = {"scan": "approach"}


class MarkerInUseError(Exception):
    """Raised when a location cannot be deleted because inventory/tasks reference it."""

    def __init__(self, usage: dict[str, Any]) -> None:
        self.usage = usage
        super().__init__(usage.get("location_id", "marker_in_use"))


def _row_ts(value: Any) -> str | None:
    if value is None:
        return None
    return value.isoformat() if hasattr(value, "isoformat") else str(value)
