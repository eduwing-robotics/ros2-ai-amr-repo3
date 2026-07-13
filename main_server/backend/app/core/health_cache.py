"""TTL cache for external health probes (stale-while-revalidate)."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

_LOCK = threading.Lock()
_CACHE: dict[str, tuple[float, object]] = {}
_DEFAULT_TTL_SEC = 2.5


def get_cached_swr(key: str, fetcher: Callable[[], T], ttl: float = _DEFAULT_TTL_SEC, *, force: bool = False) -> T:
    """Return cached value; refresh in background when stale unless force is set."""
    now = time.monotonic()
    stale: T | None = None
    if not force:
        with _LOCK:
            entry = _CACHE.get(key)
            if entry is not None:
                ts, value = entry
                if now - ts < ttl:
                    return value  # type: ignore[return-value]
                stale = value  # type: ignore[assignment]

    if stale is not None:

        def _refresh() -> None:
            try:
                fresh = fetcher()
            except Exception:
                return
            with _LOCK:
                _CACHE[key] = (time.monotonic(), fresh)

        threading.Thread(target=_refresh, daemon=True).start()
        return stale

    value = fetcher()
    with _LOCK:
        _CACHE[key] = (now, value)
    return value


def clear_cache() -> None:
    """Test helper — drop all cached health snapshots."""
    with _LOCK:
        _CACHE.clear()
