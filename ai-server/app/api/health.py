from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, Query

from ..config import get_settings
from ..openapi_schemas import ERROR_RESPONSE_OPENAPI, SOURCE_ID_OPENAPI_EXTRA
from ..runtime_state import RuntimeContext
from ..service_metadata import SERVICE_VERSION
from .dependencies import ContextGetter


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now_dt().isoformat()


def _source_definition(source: str):
    return get_settings().source_registry.get(source)


def _robot_id_for_source(source: str) -> str | None:
    return _source_definition(source).robot_id


def _frame_id_for_source(source: str) -> str:
    return _source_definition(source).frame_id


def _source_kind(source: str) -> str:
    return _source_definition(source).kind


def _source_notes(source: str) -> str:
    return _source_definition(source).notes


def _physical_input_topic_for_source(source: str) -> str | None:
    return _source_definition(source).physical_input.topic


def _physical_input_message_type_for_source(source: str) -> str | None:
    return _source_definition(source).physical_input.message_type


def _physical_input_content_type_for_source(source: str) -> str | None:
    return _source_definition(source).physical_input.content_type


def _vision_model_status(settings) -> str:
    if settings.vision_model_task not in {"segment", "detect"}:
        return "error"
    if not settings.vision_model_path.strip():
        return "disabled"
    if not _vision_model_class_map_valid(settings):
        return "error"
    if not _vision_model_source_config_valid(settings):
        return "error"
    return "loaded"


def _model_worker_enabled(settings) -> bool:
    return bool(settings.vision_model_worker_enabled and settings.vision_model_path.strip())


def _vision_model_class_map_valid(settings) -> bool:
    class_map_json = settings.vision_model_class_map_json.strip()
    if not class_map_json:
        return True
    try:
        parsed = json.loads(class_map_json)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, dict)


def _vision_model_source_config_valid(settings) -> bool:
    source_config_json = settings.vision_model_source_config_json.strip()
    if not source_config_json:
        return True
    try:
        parsed = json.loads(source_config_json)
    except json.JSONDecodeError:
        return False
    if not isinstance(parsed, dict):
        return False
    return all(
        _vision_model_source_override_valid(source, value) for source, value in parsed.items()
    )


def _falsey_json_setting(value: Any) -> bool:
    if value is False:
        return True
    if isinstance(value, str):
        return value.strip().lower() in {"0", "false", "no", "off", "disabled"}
    return False


def _valid_float_setting(
    value: Any, *, min_value: float | None = None, max_value: float | None = None
) -> bool:
    if isinstance(value, bool):
        return False
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return False
    if min_value is not None and parsed < min_value:
        return False
    if max_value is not None and parsed > max_value:
        return False
    return True


def _valid_positive_int_setting(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return False
    return parsed > 0


def _vision_model_source_override_valid(source: Any, value: Any) -> bool:
    if not isinstance(source, str) or not source.strip():
        return False
    if not isinstance(value, dict):
        return False
    if _falsey_json_setting(value.get("enabled")):
        return True
    if "model_path" in value and not isinstance(value["model_path"], str):
        return False
    if "path" in value and not isinstance(value["path"], str):
        return False
    task = value.get("task")
    if task is not None and str(task) not in {"segment", "detect"}:
        return False
    for key in ("image_size", "imgsz"):
        if key in value and not _valid_positive_int_setting(value[key]):
            return False
    for key in ("confidence", "conf", "iou"):
        if key in value and not _valid_float_setting(value[key], min_value=0.0, max_value=1.0):
            return False
    if "class_map" in value and not isinstance(value["class_map"], dict):
        return False
    if "class_map_json" in value:
        class_map_json = value["class_map_json"]
        if not isinstance(class_map_json, str):
            return False
        try:
            parsed_class_map = json.loads(class_map_json)
        except json.JSONDecodeError:
            return False
        if not isinstance(parsed_class_map, dict):
            return False
    return True


def _vision_model_source_overrides(settings) -> list[str]:
    source_config_json = settings.vision_model_source_config_json.strip()
    if not source_config_json:
        return []
    try:
        parsed = json.loads(source_config_json)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, dict):
        return []
    return sorted(str(source) for source, value in parsed.items() if isinstance(value, dict))


def _health(context: RuntimeContext) -> dict[str, Any]:
    settings = get_settings()
    source_summary = context.source_health.summary(
        settings.source_ids,
        now=_now_dt(),
        stale_after_s=settings.source_stale_after_s,
        offline_after_s=settings.source_offline_after_s,
    )
    lift_roi_model_status = _vision_model_status(settings)
    return {
        "service": "ai-server",
        "status": "ok",
        "service_version": SERVICE_VERSION,
        "contract_version": settings.vision_event_schema_version,
        "model_status": "loaded",
        "models": {
            "marker": {"status": "loaded", "name": settings.model_name},
            "lift_roi": {
                "status": lift_roi_model_status,
                "task": settings.vision_model_task,
                "path_configured": bool(settings.vision_model_path.strip()),
                "device": settings.vision_model_device,
                "worker_enabled": settings.vision_model_worker_enabled,
                "worker_active": _model_worker_enabled(settings),
                "class_map_configured": bool(settings.vision_model_class_map_json.strip()),
                "class_map_valid": _vision_model_class_map_valid(settings),
                "source_config_configured": bool(settings.vision_model_source_config_json.strip()),
                "source_config_valid": _vision_model_source_config_valid(settings),
                "source_overrides": _vision_model_source_overrides(settings),
                "unmapped_class": settings.vision_model_unmapped_class,
                "max_events": settings.vision_model_max_events,
            },
        },
        "source_summary": source_summary,
        "event_retention": context.store.stats(),
        "version": SERVICE_VERSION,
        "schema_version": settings.vision_event_schema_version,
        "main_server_url": settings.main_server_url,
        "sources": settings.source_ids,
    }


def _sources(context: RuntimeContext) -> dict[str, Any]:
    settings = get_settings()
    source_items = []
    now = _now_dt()
    for source in settings.source_ids:
        health_snapshot = context.source_health.snapshot(
            source,
            now=now,
            stale_after_s=settings.source_stale_after_s,
            offline_after_s=settings.source_offline_after_s,
        )
        source_items.append(
            {
                "source": source,
                "source_id": source,
                "kind": _source_kind(source),
                "robot_id": _robot_id_for_source(source),
                "enabled": health_snapshot.enabled,
                "status": health_snapshot.status,
                "frame_id": _frame_id_for_source(source),
                "last_frame_at": health_snapshot.last_frame_at,
                "last_frame_age_s": health_snapshot.last_frame_age_s,
                "last_event_at": health_snapshot.last_event_at,
                "last_event_kind": health_snapshot.last_event_kind,
                "last_event_id": health_snapshot.last_event_id,
                "last_marker_id": health_snapshot.last_marker_id,
                "frame_count": health_snapshot.frame_count,
                "event_count": health_snapshot.event_count,
                "target_fps": _source_definition(source).target_fps or settings.source_target_fps,
                "notes": _source_notes(source),
                "ros_topic": _physical_input_topic_for_source(source),
                "ros_message_type": _physical_input_message_type_for_source(source),
                "ros_content_type": _physical_input_content_type_for_source(source),
            }
        )
    return {"sources": source_items}


def _latest_detections(
    context: RuntimeContext,
    *,
    source: str | None,
    limit: int,
) -> dict[str, Any]:
    settings = get_settings()
    if source is not None and source not in settings.source_ids:
        raise HTTPException(status_code=400, detail=f"unknown source: {source}")
    return {"generated_at": _now_iso(), "events": context.store.latest(source=source, limit=limit)}


def register_health_routes(
    app,
    *,
    context_getter: ContextGetter,
) -> None:
    """Register health/source/detection-list routes for the AI Server app."""

    def health() -> dict[str, Any]:
        return _health(context_getter())

    def sources() -> dict[str, Any]:
        return _sources(context_getter())

    def latest_detections(
        source: str | None = Query(default=None, json_schema_extra=SOURCE_ID_OPENAPI_EXTRA),
        limit: int = Query(default=10, ge=1, le=50),
    ) -> dict[str, Any]:
        return _latest_detections(context_getter(), source=source, limit=limit)

    app.get("/api/v1/health", responses={500: ERROR_RESPONSE_OPENAPI})(health)
    app.get("/api/v1/sources")(sources)
    app.get(
        "/api/v1/detections/latest",
        responses={400: ERROR_RESPONSE_OPENAPI, 422: ERROR_RESPONSE_OPENAPI},
    )(latest_detections)


__all__ = ["register_health_routes"]
