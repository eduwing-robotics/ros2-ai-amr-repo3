from __future__ import annotations

from collections import deque
from threading import Lock
from typing import Any

DEFAULT_VIEW_ID = "full"
SourceViewKey = tuple[str, str]


def normalize_view_id(view: str | None = None) -> str:
    if view is None:
        return DEFAULT_VIEW_ID
    view_id = str(view).strip()
    return view_id or DEFAULT_VIEW_ID


def source_view_key(source: str, view: str | None = None) -> SourceViewKey:
    if not isinstance(source, str) or not source:
        raise ValueError("source must be a non-empty string")
    return source, normalize_view_id(view)


class LatestEvidenceCache:
    """Thread-safe latest evidence/overlay metadata cache per source view."""

    def __init__(self, maxlen_per_source: int = 20) -> None:
        if maxlen_per_source <= 0:
            raise ValueError("maxlen_per_source must be positive")
        self._maxlen = maxlen_per_source
        self._items: dict[SourceViewKey, deque[dict[str, Any]]] = {}
        self._lock = Lock()

    def add(self, item: dict[str, Any], *, view: str | None = None) -> None:
        source = item.get("source")
        if not isinstance(source, str) or not source:
            raise ValueError("evidence item must include source")
        view_id = normalize_view_id(view if view is not None else item.get("view"))
        stored_item = dict(item)
        stored_item["view"] = view_id
        with self._lock:
            bucket = self._items.setdefault(
                source_view_key(source, view_id),
                deque(maxlen=self._maxlen),
            )
            bucket.appendleft(stored_item)

    def latest(self, source: str, *, view: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            bucket = self._items.get(source_view_key(source, view))
            if not bucket:
                return None
            return dict(bucket[0])

    def latest_all(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(bucket[0]) for bucket in self._items.values() if bucket]

    def reset(self) -> None:
        with self._lock:
            self._items.clear()
