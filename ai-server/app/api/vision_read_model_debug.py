from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..config import get_settings
from ..evidence_cache import DEFAULT_VIEW_ID
from ..runtime_state import RuntimeContext
from .vision_read_model_ros import (
    FrameAgeGetter,
    LatestOverlayImageGetter,
    _count_by,
    _physical_input_topic_for_source,
    _robot_id_for_source,
    _ros_ingest_readiness,
    _ros_topic_exposure_policy,
    _rosbridge_subscription_hints,
    _source_kind,
    _source_topic_exposure,
    _topic_exposure_summary,
    _zero_stream_metrics,
    frame_overlay_sync_status,
    ros_evidence_event_publish_readiness,
    ros_publish_readiness,
)


def debug_sources_summary(source_entries: list[dict[str, Any]]) -> dict[str, Any]:
    health_status_counts = _count_by(source_entries, ("health", "status"))
    ros_ingest_status_counts = _count_by(
        source_entries, ("ros_ingest_readiness", "readiness_state")
    )
    ros_publish_status_counts = _count_by(
        source_entries, ("ros_publish_readiness", "readiness_state")
    )
    return {
        "sources_total": len(source_entries),
        "with_frame_count": sum(1 for item in source_entries if item["latest_frame"] is not None),
        "with_overlay_count": sum(
            1 for item in source_entries if item["latest_overlay"] is not None
        ),
        "overlay_lag_count": sum(
            1
            for item in source_entries
            if isinstance(item.get("overlay_lag_frames"), int) and item["overlay_lag_frames"] > 0
        ),
        "ros_ingest_contract_ready_count": ros_ingest_status_counts.get("contract_ready", 0),
        "ros_publish_ready_count": sum(
            1 for item in source_entries if item["ros_publish_readiness"]["overlay_ready"]
        ),
        "ros_publish_payload_available_count": sum(
            1
            for item in source_entries
            if item["ros_publish_readiness"]["publish_payload_preview"]["payload_available"]
        ),
        "evidence_event_publish_ready_count": sum(
            1
            for item in source_entries
            if item["evidence_event_publish_readiness"]["publish_ready"]
        ),
        "stale_overlay_count": ros_publish_status_counts.get("ready_stale", 0),
        "health_status_counts": health_status_counts,
        "ros_ingest_status_counts": ros_ingest_status_counts,
        "ros_publish_status_counts": ros_publish_status_counts,
    }


def debug_source_snapshot(
    source: str,
    *,
    stream_metrics: dict[str, Any],
    frame_stats: dict[str, Any],
    runtime_context: RuntimeContext,
    latest_overlay_image: LatestOverlayImageGetter,
    frame_age_s: FrameAgeGetter,
    now_dt: Callable[[], Any],
) -> dict[str, Any]:
    settings = get_settings()
    health_snapshot = runtime_context.source_health.snapshot(
        source,
        now=now_dt(),
        stale_after_s=settings.source_stale_after_s,
        offline_after_s=settings.source_offline_after_s,
    )
    frame = runtime_context.frame_store.latest(source)
    overlay = runtime_context.overlay_cache.latest(source)
    physical_topic = _physical_input_topic_for_source(source)
    topic_exposure = _source_topic_exposure(source, physical_topic)
    sync_status = frame_overlay_sync_status(source, runtime_context=runtime_context)
    return {
        "source": source,
        "default_view": DEFAULT_VIEW_ID,
        "available_views": list(settings.source_registry.get(source).view_ids),
        "kind": _source_kind(source),
        "robot_id": _robot_id_for_source(source),
        "health": {
            "enabled": health_snapshot.enabled,
            "status": health_snapshot.status,
            "last_frame_at": health_snapshot.last_frame_at,
            "last_frame_age_s": health_snapshot.last_frame_age_s,
            "last_event_at": health_snapshot.last_event_at,
            "last_event_kind": health_snapshot.last_event_kind,
            "last_event_id": health_snapshot.last_event_id,
            "last_marker_id": health_snapshot.last_marker_id,
            "frame_count": health_snapshot.frame_count,
            "event_count": health_snapshot.event_count,
        },
        "latest_frame": frame.metadata(include_content=True) if frame is not None else None,
        "latest_overlay": overlay,
        "overlay_lag_frames": sync_status["overlay_lag_frames"],
        "topic_exposure": topic_exposure,
        "rosbridge_subscription_hints": _rosbridge_subscription_hints(source, topic_exposure),
        "ros_ingest_readiness": _ros_ingest_readiness(source, physical_topic),
        "ros_publish_readiness": ros_publish_readiness(
            source,
            runtime_context=runtime_context,
            latest_overlay_image=latest_overlay_image,
            frame_age_s=frame_age_s,
        ),
        "evidence_event_publish_readiness": ros_evidence_event_publish_readiness(
            source,
            runtime_context=runtime_context,
        ),
        "debug_paths": {
            "frame_ingest": "/api/v1/vision/frame",
            "mjpeg": f"/api/v1/vision/stream/{source}.mjpeg",
            "mjpeg_default_max_fps": 10,
            "frame_metadata": f"/api/v1/vision/frame/latest?source={source}",
            "frame_image": f"/api/v1/vision/frame/latest/image?source={source}",
            "overlay_metadata": f"/api/v1/vision/overlay/latest?source={source}",
            "overlay_image": f"/api/v1/vision/overlay/latest/image?source={source}",
            "worker_tick": "/api/v1/vision/worker/tick",
            "worker_status": f"/api/v1/vision/worker/status?source={source}",
            "metrics": f"/api/v1/metrics?source={source}",
            "metrics_all": "/api/v1/metrics",
            "ros_handoff": f"/api/v1/vision/ros/topics?source={source}",
            "ros_handoff_all": "/api/v1/vision/ros/topics",
        },
        "stream_metrics": stream_metrics["by_source"].get(source, _zero_stream_metrics()),
        "drop_metrics": {
            "dropped_frames": frame_stats.get("dropped_frames_by_source", {}).get(source, 0)
        },
    }


def build_vision_debug_sources_payload(
    *,
    source: str | None,
    runtime_context: RuntimeContext,
    latest_overlay_image: LatestOverlayImageGetter,
    frame_age_s: FrameAgeGetter,
    now_iso: Callable[[], str],
    now_dt: Callable[[], Any],
) -> dict[str, Any]:
    settings = get_settings()
    sources = [source] if source is not None else list(settings.source_ids)
    stream_metrics = runtime_context.metrics.stream_snapshot()
    frame_stats = runtime_context.frame_store.stats()
    source_entries = [
        debug_source_snapshot(
            item,
            stream_metrics=stream_metrics,
            frame_stats=frame_stats,
            runtime_context=runtime_context,
            latest_overlay_image=latest_overlay_image,
            frame_age_s=frame_age_s,
            now_dt=now_dt,
        )
        for item in sources
    ]
    return {
        "generated_at": now_iso(),
        "requested_source": source,
        "primary_stream_plane": "webrtc",
        "fallback_stream_plane": "http_mjpeg_gateway",
        "stream_base_url": "http://<vision-host>:8090",
        "fallback_stream_base_url": "http://<vision-host>:8090",
        "debug_only": True,
        "summary": debug_sources_summary(source_entries),
        "topic_exposure_policy": _ros_topic_exposure_policy(),
        "topic_exposure_summary": _topic_exposure_summary(source_entries),
        "sources": source_entries,
    }
