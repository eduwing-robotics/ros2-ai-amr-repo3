from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


class SourceRegistryError(ValueError):
    """Raised when the configured vision source registry is invalid."""


@dataclass(frozen=True)
class PhysicalInput:
    topic: str | None
    message_type: str | None
    content_type: str | None
    preferred_transport: str | None


@dataclass(frozen=True)
class BrowserSurface:
    legacy_topic: str | None
    legacy_message_type: str | None
    primary_transport: str


@dataclass(frozen=True)
class NormalizedTopics:
    image: str
    overlay: str


@dataclass(frozen=True)
class SourceBudgets:
    """Per-source budget semantics for preview media, AI monitor, and evidence.

    `target_fps` remains a legacy field in the source registry.  This additive
    object prevents Main/WebRTC callers from interpreting that legacy value as
    the dashboard preview FPS after the GoPro split-budget work.
    """

    target_fps_semantics: str
    preview_media_fps: float | None
    ai_monitor_fps: float | None
    evidence_imgsz: int | None
    browser_primary_transport_semantics: str

    def as_snapshot(self) -> dict[str, Any]:
        return {
            "target_fps_semantics": self.target_fps_semantics,
            "preview_media_fps": self.preview_media_fps,
            "ai_monitor_fps": self.ai_monitor_fps,
            "evidence_imgsz": self.evidence_imgsz,
            "browser_primary_transport_semantics": self.browser_primary_transport_semantics,
        }


@dataclass(frozen=True)
class SourceViewDefinition:
    view_id: str
    kind: str
    can_confirm_internal_color_indexing: bool
    parent_view: str | None = None

    def as_snapshot(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "view_id": self.view_id,
            "kind": self.kind,
            "can_confirm_internal_color_indexing": self.can_confirm_internal_color_indexing,
        }
        if self.parent_view is not None:
            payload["parent_view"] = self.parent_view
        return payload


@dataclass(frozen=True)
class SourceDefinition:
    source_id: str
    kind: str
    robot_id: str | None
    frame_id: str
    enabled: bool
    target_fps: float | None
    notes: str
    physical_input: PhysicalInput
    browser: BrowserSurface
    normalized_topics: NormalizedTopics
    evidence_event_topic: str
    budgets: SourceBudgets
    views: tuple[SourceViewDefinition, ...] = ()

    @property
    def view_ids(self) -> tuple[str, ...]:
        return tuple(view.view_id for view in self.views)

    def get_view(self, view_id: str) -> SourceViewDefinition:
        for view in self.views:
            if view.view_id == view_id:
                return view
        raise KeyError(view_id)

    def resolve_view(self, view_id: str | None = None) -> SourceViewDefinition:
        return self.get_view(view_id or "full")

    def as_snapshot(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "kind": self.kind,
            "robot_id": self.robot_id,
            "frame_id": self.frame_id,
            "enabled": self.enabled,
            "target_fps": self.target_fps,
            "notes": self.notes,
            "physical_input": {
                "topic": self.physical_input.topic,
                "message_type": self.physical_input.message_type,
                "content_type": self.physical_input.content_type,
                "preferred_transport": self.physical_input.preferred_transport,
            },
            "browser": {
                "legacy_topic": self.browser.legacy_topic,
                "legacy_message_type": self.browser.legacy_message_type,
                "primary_transport": self.browser.primary_transport,
            },
            "normalized_topics": {
                "image": self.normalized_topics.image,
                "overlay": self.normalized_topics.overlay,
            },
            "evidence_event_topic": self.evidence_event_topic,
            "budgets": self.budgets.as_snapshot(),
            "views": [view.as_snapshot() for view in self.views],
        }


@dataclass(frozen=True)
class SourceRegistry:
    schema_version: str
    sources: tuple[SourceDefinition, ...]

    @property
    def source_ids(self) -> list[str]:
        return [source.source_id for source in self.sources if source.enabled]

    @property
    def all_source_ids(self) -> list[str]:
        return [source.source_id for source in self.sources]

    def get(self, source_id: str) -> SourceDefinition:
        for source in self.sources:
            if source.source_id == source_id:
                return source
        raise KeyError(source_id)

    @property
    def source_views(self) -> dict[str, tuple[str, ...]]:
        return {source.source_id: source.view_ids for source in self.sources}

    @property
    def internal_color_indexing_allowed_views(self) -> dict[str, tuple[str, ...]]:
        return {
            source.source_id: tuple(
                view.view_id for view in source.views if view.can_confirm_internal_color_indexing
            )
            for source in self.sources
        }

    def resolve_view(self, source_id: str, view_id: str | None = None) -> SourceViewDefinition:
        return self.get(source_id).resolve_view(view_id)

    def can_confirm_internal_color_indexing(
        self, source_id: str, view_id: str | None = None
    ) -> bool:
        return self.resolve_view(source_id, view_id).can_confirm_internal_color_indexing

    def as_snapshot(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "all_source_ids": self.all_source_ids,
            "source_ids": self.source_ids,
            "source_views": {
                source_id: list(view_ids) for source_id, view_ids in self.source_views.items()
            },
            "internal_color_indexing_allowed_views": {
                source_id: list(view_ids)
                for source_id, view_ids in self.internal_color_indexing_allowed_views.items()
            },
            "sources": [source.as_snapshot() for source in self.sources],
        }


_REQUIRED_SOURCE_FIELDS = {
    "source_id",
    "kind",
    "robot_id",
    "frame_id",
    "enabled",
    "notes",
    "physical_input",
    "browser",
    "normalized_topics",
    "evidence_event_topic",
}


def _require_mapping(value: Any, *, path: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SourceRegistryError(f"{path} must be an object")
    return value


def _require_string(value: Any, *, path: str, allow_empty: bool = False) -> str:
    if not isinstance(value, str):
        raise SourceRegistryError(f"{path} must be a string")
    if not allow_empty and not value.strip():
        raise SourceRegistryError(f"{path} must not be empty")
    return value


def _optional_string(value: Any, *, path: str) -> str | None:
    if value is None:
        return None
    return _require_string(value, path=path)


def _optional_positive_float(value: Any, *, path: str) -> float | None:
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise SourceRegistryError(f"{path} must be a positive number")
    return float(value)


def _optional_positive_int(value: Any, *, path: str) -> int | None:
    if value is None:
        return None
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise SourceRegistryError(f"{path} must be a positive integer")
    return int(value)


def _parse_budgets(
    raw: Any,
    *,
    index: int,
    target_fps: float | None,
) -> SourceBudgets:
    if raw is None:
        raw = {}
    budgets = _require_mapping(raw, path=f"sources[{index}].budgets")
    return SourceBudgets(
        target_fps_semantics=_require_string(
            budgets.get("target_fps_semantics", "legacy_ai_ingest_default"),
            path=f"sources[{index}].budgets.target_fps_semantics",
        ),
        preview_media_fps=_optional_positive_float(
            budgets.get("preview_media_fps", target_fps),
            path=f"sources[{index}].budgets.preview_media_fps",
        ),
        ai_monitor_fps=_optional_positive_float(
            budgets.get("ai_monitor_fps", target_fps),
            path=f"sources[{index}].budgets.ai_monitor_fps",
        ),
        evidence_imgsz=_optional_positive_int(
            budgets.get("evidence_imgsz"),
            path=f"sources[{index}].budgets.evidence_imgsz",
        ),
        browser_primary_transport_semantics=_require_string(
            budgets.get(
                "browser_primary_transport_semantics",
                "legacy_internal_browser_metadata",
            ),
            path=f"sources[{index}].budgets.browser_primary_transport_semantics",
        ),
    )


def _parse_views(raw: Any, *, source_id: str, index: int) -> tuple[SourceViewDefinition, ...]:
    if raw is None:
        raw = [
            {
                "view_id": "full",
                "kind": "full_frame",
                "can_confirm_internal_color_indexing": False,
            }
        ]
    if not isinstance(raw, list) or not raw:
        raise SourceRegistryError(f"sources[{index}].views must be a non-empty list")

    views: list[SourceViewDefinition] = []
    seen: set[str] = set()
    for view_index, view_raw in enumerate(raw):
        view = _require_mapping(view_raw, path=f"sources[{index}].views[{view_index}]")
        view_id = _require_string(
            view.get("view_id"), path=f"sources[{index}].views[{view_index}].view_id"
        )
        if view_id in seen:
            raise SourceRegistryError(f"sources[{index}].views duplicate view_id: {view_id}")
        seen.add(view_id)
        can_confirm = view.get("can_confirm_internal_color_indexing", False)
        if not isinstance(can_confirm, bool):
            raise SourceRegistryError(
                f"sources[{index}].views[{view_index}].can_confirm_internal_color_indexing must be a boolean"
            )
        views.append(
            SourceViewDefinition(
                view_id=view_id,
                kind=_require_string(
                    view.get("kind"), path=f"sources[{index}].views[{view_index}].kind"
                ),
                can_confirm_internal_color_indexing=can_confirm,
                parent_view=_optional_string(
                    view.get("parent_view"),
                    path=f"sources[{index}].views[{view_index}].parent_view",
                ),
            )
        )

    if "full" not in seen:
        raise SourceRegistryError(f"sources[{index}].views must include full")
    for view in views:
        if view.parent_view is not None and view.parent_view not in seen:
            raise SourceRegistryError(
                f"sources[{index}].views[{view.view_id}].parent_view must reference an existing view"
            )
        if view.view_id == "full" and view.can_confirm_internal_color_indexing:
            raise SourceRegistryError(f"{source_id}/full cannot confirm internal color indexing")
    return tuple(views)


def _parse_source(raw: Any, *, index: int) -> SourceDefinition:
    item = _require_mapping(raw, path=f"sources[{index}]")
    missing = sorted(_REQUIRED_SOURCE_FIELDS - set(item))
    if missing:
        raise SourceRegistryError(f"sources[{index}] missing required fields: {', '.join(missing)}")

    source_id = _require_string(item["source_id"], path=f"sources[{index}].source_id")
    physical = _require_mapping(item["physical_input"], path=f"sources[{index}].physical_input")
    browser = _require_mapping(item["browser"], path=f"sources[{index}].browser")
    normalized = _require_mapping(
        item["normalized_topics"], path=f"sources[{index}].normalized_topics"
    )

    enabled = item["enabled"]
    if not isinstance(enabled, bool):
        raise SourceRegistryError(f"sources[{index}].enabled must be a boolean")

    target_fps = _optional_positive_float(
        item.get("target_fps"), path=f"sources[{index}].target_fps"
    )

    return SourceDefinition(
        source_id=source_id,
        kind=_require_string(item["kind"], path=f"sources[{index}].kind"),
        robot_id=_optional_string(item["robot_id"], path=f"sources[{index}].robot_id"),
        frame_id=_require_string(item["frame_id"], path=f"sources[{index}].frame_id"),
        enabled=enabled,
        target_fps=target_fps,
        notes=_require_string(item["notes"], path=f"sources[{index}].notes", allow_empty=True),
        physical_input=PhysicalInput(
            topic=_optional_string(
                physical.get("topic"), path=f"sources[{index}].physical_input.topic"
            ),
            message_type=_optional_string(
                physical.get("message_type"), path=f"sources[{index}].physical_input.message_type"
            ),
            content_type=_optional_string(
                physical.get("content_type"), path=f"sources[{index}].physical_input.content_type"
            ),
            preferred_transport=_optional_string(
                physical.get("preferred_transport"),
                path=f"sources[{index}].physical_input.preferred_transport",
            ),
        ),
        browser=BrowserSurface(
            legacy_topic=_optional_string(
                browser.get("legacy_topic"), path=f"sources[{index}].browser.legacy_topic"
            ),
            legacy_message_type=_optional_string(
                browser.get("legacy_message_type"),
                path=f"sources[{index}].browser.legacy_message_type",
            ),
            primary_transport=_require_string(
                browser.get("primary_transport", "rosbridge"),
                path=f"sources[{index}].browser.primary_transport",
            ),
        ),
        normalized_topics=NormalizedTopics(
            image=_require_string(
                normalized.get("image"), path=f"sources[{index}].normalized_topics.image"
            ),
            overlay=_require_string(
                normalized.get("overlay"), path=f"sources[{index}].normalized_topics.overlay"
            ),
        ),
        evidence_event_topic=_require_string(
            item["evidence_event_topic"], path=f"sources[{index}].evidence_event_topic"
        ),
        budgets=_parse_budgets(
            item.get("budgets"),
            index=index,
            target_fps=target_fps,
        ),
        views=_parse_views(item.get("views"), source_id=source_id, index=index),
    )


def load_source_registry(path: Path) -> SourceRegistry:
    if not path.exists():
        raise SourceRegistryError(f"source registry not found: {path}")
    loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
    data = _require_mapping(loaded, path=str(path))
    schema_version = _require_string(data.get("schema_version"), path="schema_version")
    raw_sources = data.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise SourceRegistryError("sources must be a non-empty list")

    sources = tuple(_parse_source(raw, index=index) for index, raw in enumerate(raw_sources))
    seen: set[str] = set()
    duplicates: list[str] = []
    for source in sources:
        if source.source_id in seen:
            duplicates.append(source.source_id)
        seen.add(source.source_id)
    if duplicates:
        raise SourceRegistryError(f"duplicate source_id values: {', '.join(sorted(duplicates))}")

    return SourceRegistry(schema_version=schema_version, sources=sources)


@lru_cache(maxsize=8)
def load_source_registry_cached(path: str) -> SourceRegistry:
    return load_source_registry(Path(path))
