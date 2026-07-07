from __future__ import annotations

import logging
from dataclasses import dataclass, field
from threading import Lock
from typing import Any

from .config import get_settings
from .event_store import InMemoryEventStore
from .evidence_cache import LatestEvidenceCache, SourceViewKey
from .frame_store import LatestFrameStore
from .observability import InMemoryMetrics
from .overlay import OverlayRenderResult
from .source_health import InMemorySourceHealthTracker
from .vision_monitor_state import VisionMonitorStateStore


@dataclass(slots=True)
class RuntimeContext:
    """Runtime-owned mutable state for one AI Server app instance.

    The default ``app.main:app`` still uses ``default_runtime_context`` for
    compatibility, while tests or future embedded deployments can inject an
    explicit context through ``create_app(runtime_context=...)``.
    """

    logger: logging.Logger = field(
        default_factory=lambda: logging.getLogger("smartfactory.ai_server")
    )
    store: InMemoryEventStore = field(
        default_factory=lambda: InMemoryEventStore(maxlen=get_settings().event_store_maxlen)
    )
    source_health: InMemorySourceHealthTracker = field(default_factory=InMemorySourceHealthTracker)
    metrics: InMemoryMetrics = field(default_factory=InMemoryMetrics)
    frame_store: LatestFrameStore = field(default_factory=LatestFrameStore)
    overlay_cache: LatestEvidenceCache = field(
        default_factory=lambda: LatestEvidenceCache(maxlen_per_source=20)
    )
    overlay_images: dict[str | SourceViewKey, OverlayRenderResult] = field(default_factory=dict)
    overlay_event_layers: dict[str | SourceViewKey, tuple[int, list[dict[str, Any]]]] = field(
        default_factory=dict
    )
    overlay_images_lock: Lock = field(default_factory=Lock)
    monitor_states: VisionMonitorStateStore = field(default_factory=VisionMonitorStateStore)
    map_roi_trackers: dict[str, object] = field(default_factory=dict)
    map_roi_trackers_lock: Lock = field(default_factory=Lock)


def create_runtime_context() -> RuntimeContext:
    """Create an isolated runtime context for app factory injection."""

    return RuntimeContext()


default_runtime_context = create_runtime_context()

# Backward-compatible aliases for existing tests/tools that import runtime state
# directly. Runtime routes should use the injected/context-bound object instead.
logger = default_runtime_context.logger
store = default_runtime_context.store
source_health = default_runtime_context.source_health
metrics = default_runtime_context.metrics
frame_store = default_runtime_context.frame_store
overlay_cache = default_runtime_context.overlay_cache
_overlay_images = default_runtime_context.overlay_images
_overlay_images_lock = default_runtime_context.overlay_images_lock
monitor_states = default_runtime_context.monitor_states

__all__ = [
    "RuntimeContext",
    "_overlay_images",
    "_overlay_images_lock",
    "create_runtime_context",
    "default_runtime_context",
    "frame_store",
    "logger",
    "metrics",
    "monitor_states",
    "overlay_cache",
    "source_health",
    "store",
]
