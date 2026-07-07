from __future__ import annotations

from collections import deque
from threading import Lock
from typing import Any


class InMemoryEventStore:
    """Small thread-safe ring buffer for latest detections during MVP1 scaffolding."""

    def __init__(self, maxlen: int = 200) -> None:
        if maxlen <= 0:
            raise ValueError("maxlen must be positive")
        self._events: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._lock = Lock()

    def add(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._events.appendleft(event)

    def latest(self, *, source: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            events = list(self._events)
        if source:
            events = [event for event in events if event.get("source") == source]
        return events[:limit]

    @property
    def maxlen(self) -> int:
        configured_maxlen = self._events.maxlen
        assert configured_maxlen is not None
        return configured_maxlen

    def __len__(self) -> int:
        with self._lock:
            return len(self._events)

    def reset(self) -> None:
        with self._lock:
            self._events.clear()

    def stats(self) -> dict[str, int]:
        with self._lock:
            current_size = len(self._events)
            configured_maxlen = self._events.maxlen
        assert configured_maxlen is not None
        return {
            "current_size": current_size,
            "max_size": configured_maxlen,
        }
