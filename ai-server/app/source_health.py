from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from threading import Lock
from typing import Any, Iterable


@dataclass(frozen=True)
class SourceHealthSnapshot:
    source: str
    enabled: bool
    status: str
    last_frame_at: str | None
    last_event_at: str | None
    last_event_kind: str | None
    last_event_id: str | None
    last_marker_id: str | None
    frame_count: int
    event_count: int
    last_frame_age_s: float | None


@dataclass
class _SourceHealthRecord:
    enabled: bool = True
    last_frame_at: datetime | None = None
    last_event_at: datetime | None = None
    last_event_kind: str | None = None
    last_event_id: str | None = None
    last_marker_id: str | None = None
    frame_count: int = 0
    event_count: int = 0


def normalize_datetime(value: datetime | str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc).astimezone()
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value)
    else:
        parsed = value
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def isoformat_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def source_status(
    *,
    enabled: bool,
    last_frame_at: datetime | None,
    now: datetime,
    stale_after_s: float,
    offline_after_s: float,
) -> tuple[str, float | None]:
    """Classify one source from frame freshness.

    Status semantics:
    - disabled: configured but intentionally disabled.
    - offline: no valid frame has ever been seen, or the last frame is older
      than offline_after_s.
    - stale: a valid frame was seen, but it is older than stale_after_s.
    - online: a valid frame is fresh enough.
    """

    if not enabled:
        return "disabled", None
    if last_frame_at is None:
        return "offline", None

    age_s = max(0.0, (now - last_frame_at).total_seconds())
    if age_s > offline_after_s:
        return "offline", age_s
    if age_s > stale_after_s:
        return "stale", age_s
    return "online", age_s


class InMemorySourceHealthTracker:
    """Thread-safe source freshness tracker for camera/image evidence paths."""

    def __init__(self) -> None:
        self._records: dict[str, _SourceHealthRecord] = {}
        self._lock = Lock()

    def reset(self) -> None:
        with self._lock:
            self._records.clear()

    def set_enabled(self, source: str, enabled: bool) -> None:
        with self._lock:
            self._record_for(source).enabled = bool(enabled)

    def record_frame(self, source: str, *, at: datetime | str | None = None) -> None:
        timestamp = normalize_datetime(at)
        with self._lock:
            record = self._record_for(source)
            record.last_frame_at = timestamp
            record.frame_count += 1

    def record_event(self, event: dict[str, Any], *, at: datetime | str | None = None) -> None:
        source = str(event.get("source") or "")
        if not source:
            return
        timestamp = normalize_datetime(at or event.get("timestamp"))
        with self._lock:
            record = self._record_for(source)
            record.last_event_at = timestamp
            record.last_event_kind = str(event.get("event_kind") or "") or None
            record.last_event_id = str(event.get("event_id") or "") or None
            record.last_marker_id = str(event.get("marker_id") or "") or None
            record.event_count += 1

    def snapshot(
        self,
        source: str,
        *,
        now: datetime | str | None = None,
        stale_after_s: float,
        offline_after_s: float,
    ) -> SourceHealthSnapshot:
        current = normalize_datetime(now)
        with self._lock:
            record = self._copy_record(source)
        status, age_s = source_status(
            enabled=record.enabled,
            last_frame_at=record.last_frame_at,
            now=current,
            stale_after_s=stale_after_s,
            offline_after_s=offline_after_s,
        )
        return SourceHealthSnapshot(
            source=source,
            enabled=record.enabled,
            status=status,
            last_frame_at=isoformat_or_none(record.last_frame_at),
            last_event_at=isoformat_or_none(record.last_event_at),
            last_event_kind=record.last_event_kind,
            last_event_id=record.last_event_id,
            last_marker_id=record.last_marker_id,
            frame_count=record.frame_count,
            event_count=record.event_count,
            last_frame_age_s=round(age_s, 3) if age_s is not None else None,
        )

    def summary(
        self,
        sources: Iterable[str],
        *,
        now: datetime | str | None = None,
        stale_after_s: float,
        offline_after_s: float,
    ) -> dict[str, int]:
        current = normalize_datetime(now)
        counts = {
            "configured": 0,
            "online": 0,
            "stale": 0,
            "disabled": 0,
            "offline": 0,
        }
        for source in sources:
            counts["configured"] += 1
            snapshot = self.snapshot(
                source,
                now=current,
                stale_after_s=stale_after_s,
                offline_after_s=offline_after_s,
            )
            counts[snapshot.status] += 1
        return counts

    def _record_for(self, source: str) -> _SourceHealthRecord:
        if source not in self._records:
            self._records[source] = _SourceHealthRecord()
        return self._records[source]

    def _copy_record(self, source: str) -> _SourceHealthRecord:
        original = self._records.get(source)
        if original is None:
            return _SourceHealthRecord()
        return _SourceHealthRecord(
            enabled=original.enabled,
            last_frame_at=original.last_frame_at,
            last_event_at=original.last_event_at,
            last_event_kind=original.last_event_kind,
            last_event_id=original.last_event_id,
            last_marker_id=original.last_marker_id,
            frame_count=original.frame_count,
            event_count=original.event_count,
        )
