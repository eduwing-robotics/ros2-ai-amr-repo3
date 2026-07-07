from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request as UrlRequest
from urllib.request import urlopen

from ..config import REPO_ROOT, get_settings
from ..evidence_cache import DEFAULT_VIEW_ID
from ..runtime_state import RuntimeContext
from .vision_read_model_ros import (
    FrameAgeGetter,
    LatestOverlayImageGetter,
    _count_by,
    _physical_input_topic_for_source,
    _ros_ingest_readiness,
    _ros_runtime_policy,
    _ros_topic_exposure_policy,
    _rosbridge_subscription_hints,
    _source_topic_exposure,
    _topic_exposure_summary,
    _zero_stream_metrics,
    frame_overlay_sync_status,
    ros_evidence_event_publish_readiness,
    ros_publish_readiness,
)


def overlay_stream_path(source: str, view: str, *, max_fps: int = 30) -> str:
    """Main-facing public overlay gateway path for one source/view."""

    return "/api/v1/vision/overlay/stream?" + urlencode(
        {"source": source, "view": view, "max_fps": max_fps}
    )


def frame_stream_path(source: str, view: str, *, max_fps: int = 30) -> str:
    """Main-facing public clean/latest-frame gateway path for one source/view."""

    return "/api/v1/vision/frame/stream?" + urlencode(
        {"source": source, "view": view, "max_fps": max_fps}
    )


def overlay_metadata_path(source: str, view: str, *, limit: int = 20) -> str:
    """Diagnostic AI overlay metadata path.

    Public streaming overlays are burned into the video.  This endpoint remains
    useful for debugging and offline inspection, but Main does not need it to
    draw streaming overlays.
    """

    return "/api/v1/vision/overlay/metadata?" + urlencode(
        {"source": source, "view": view, "limit": limit}
    )


def vision_stream_base_url() -> str:
    settings = get_settings()
    return f"http://{settings.vision_public_host}:{settings.vision_stream_gateway_port}"


def vision_api_base_url() -> str:
    settings = get_settings()
    return f"http://{settings.vision_public_host}:{settings.ai_server_port}"


def vision_gateway_url(path: str) -> str:
    return f"{vision_stream_base_url()}{path}"


def vision_api_url(path: str) -> str:
    return f"{vision_api_base_url()}{path}"


def webrtc_offer_path(source: str, view: str) -> str:
    return f"/api/v1/vision/streams/{quote(source, safe='')}/webrtc/offer?" + urlencode(
        {"view": view}
    )


def _slug_path_part(value: str) -> str:
    slugged = re.sub(r"[^A-Za-z0-9_-]", "_", value.strip())
    return slugged.strip("_")


def webrtc_sidecar_path_id(source: str, view: str) -> str:
    return f"{_slug_path_part(source)}_{_slug_path_part(view)}"


def _render_sidecar_url(template: str, *, source: str, view: str) -> str | None:
    template = template.strip()
    if not template:
        return None
    return template.format(
        source=quote(source, safe=""),
        source_id=quote(source, safe=""),
        view=quote(view, safe=""),
        view_id=quote(view, safe=""),
    )


def _parse_stream_specs(raw: str) -> set[tuple[str, str]]:
    raw = raw.strip()
    if not raw:
        return set()
    streams: set[tuple[str, str]] = set()
    for item in raw.split(","):
        spec = item.strip()
        if not spec:
            continue
        if "/" in spec:
            source, view = spec.split("/", 1)
        else:
            source, view = spec, DEFAULT_VIEW_ID
        source = source.strip()
        view = view.strip() or DEFAULT_VIEW_ID
        if source:
            streams.add((source, view))
    return streams


def _configured_sidecar_streams() -> set[tuple[str, str]]:
    return _parse_stream_specs(get_settings().vision_webrtc_sidecar_streams)


def _configured_clean_video_streams() -> set[tuple[str, str]]:
    return _parse_stream_specs(get_settings().vision_webrtc_clean_video_streams)


def _configured_direct_media_streams() -> set[tuple[str, str]]:
    return _parse_stream_specs(get_settings().vision_webrtc_direct_media_streams)


def _configured_compositor_publisher_streams() -> set[tuple[str, str]]:
    return _parse_stream_specs(get_settings().vision_webrtc_compositor_publisher_streams)


def _sidecar_stream_is_allowed(source: str, view: str) -> bool:
    configured_streams = _configured_sidecar_streams()
    return not configured_streams or (source, view) in configured_streams


def _stream_is_clean_video(source: str, view: str) -> bool:
    return (source, view) in _configured_clean_video_streams()


def _stream_is_direct_media(source: str, view: str) -> bool:
    return (source, view) in _configured_direct_media_streams()


def _webrtc_media_profile(source: str, view: str) -> dict[str, Any]:
    clean_video_requested = _stream_is_clean_video(source, view)
    direct_media_requested = _stream_is_direct_media(source, view)
    return {
        "transport_origin": "vision_pc_compositor_publisher",
        "transport_class": "raw_frame_compositor_h264_webrtc",
        "transport_rank": 1,
        "video_composition": "burned_overlay_video",
        "overlay_mode": "burned_in_video",
        "preferred_until_direct_media_ready": False,
        "legacy_clean_video_config_ignored": clean_video_requested,
        "legacy_direct_media_config_ignored": direct_media_requested,
    }


def _compositor_required_for_stream(source: str, view: str) -> bool:
    configured = _configured_compositor_publisher_streams()
    if configured:
        return (source, view) in configured
    return _sidecar_stream_is_allowed(source, view)


def _compositor_metrics_path(source: str, view: str) -> str:
    settings = get_settings()
    path_id = webrtc_sidecar_path_id(source, view)
    metrics_dir = settings.vision_webrtc_compositor_metrics_dir.expanduser()
    if not metrics_dir.is_absolute():
        metrics_dir = REPO_ROOT / metrics_dir
    return str(metrics_dir / f"{path_id}.json")


def webrtc_sidecar_descriptor(source: str, view: str) -> dict[str, Any]:
    settings = get_settings()
    configured_streams = _configured_sidecar_streams()
    compositor_streams = _configured_compositor_publisher_streams()
    stream_allowed = _sidecar_stream_is_allowed(source, view)
    offer_url = _render_sidecar_url(
        settings.vision_webrtc_sidecar_offer_url_template,
        source=source,
        view=view,
    )
    whep_url = _render_sidecar_url(
        settings.vision_webrtc_sidecar_whep_url_template,
        source=source,
        view=view,
    )
    browser_url = _render_sidecar_url(
        settings.vision_webrtc_sidecar_browser_url_template,
        source=source,
        view=view,
    )
    configured = stream_allowed and bool(offer_url or whep_url or browser_url)
    health_url = settings.vision_webrtc_sidecar_health_url.strip() or None
    if health_url:
        runtime_health = "check_required"
    elif configured and settings.vision_webrtc_sidecar_assume_healthy_without_health_url:
        runtime_health = "assume_healthy"
    elif configured:
        runtime_health = "unknown"
    else:
        runtime_health = "not_configured"
    return {
        "status": "configured" if configured else "not_configured",
        "path_id": webrtc_sidecar_path_id(source, view),
        "url_configured": bool(offer_url or whep_url or browser_url),
        "stream_configured": stream_allowed,
        "configured_streams": [f"{item[0]}/{item[1]}" for item in sorted(configured_streams)],
        "compositor_required": _compositor_required_for_stream(source, view),
        "compositor_configured_streams": [
            f"{item[0]}/{item[1]}" for item in sorted(compositor_streams)
        ],
        "compositor_metrics_path": _compositor_metrics_path(source, view),
        "compositor_heartbeat_max_age_s": settings.vision_webrtc_compositor_heartbeat_max_age_s,
        "runtime_health": runtime_health,
        "runtime_health_url": health_url,
        "offer_url": offer_url if configured else None,
        "whep_url": whep_url if configured else None,
        "browser_url": browser_url if configured else None,
        "owner": "media_sidecar",
        "proxy_mode": "descriptor_only",
    }


def _parse_epoch_from_metrics(payload: dict[str, Any]) -> float | None:
    for key in ("updated_at_epoch_s", "timestamp_epoch_s", "ts_epoch_s", "heartbeat_epoch_s"):
        value = payload.get(key)
        if isinstance(value, (int, float)):
            return float(value)
    for key in ("updated_at", "timestamp", "ts", "heartbeat_at"):
        value = payload.get(key)
        if not isinstance(value, str) or not value.strip():
            continue
        raw = value.strip().replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(raw)
        except ValueError:
            continue
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.timestamp()
    return None


def _webrtc_compositor_runtime_health(sidecar: dict[str, Any]) -> str:
    if sidecar.get("status") != "configured":
        return "not_configured"
    if not sidecar.get("compositor_required"):
        return "not_required"
    metrics_path = str(sidecar.get("compositor_metrics_path") or "")
    if not metrics_path:
        return "missing_metrics_path"
    try:
        with open(metrics_path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except FileNotFoundError:
        return "missing"
    except (OSError, ValueError, json.JSONDecodeError):
        return "unreadable"
    if not isinstance(payload, dict):
        return "invalid"
    status = str(payload.get("status") or "running").lower()
    if status in {"error", "failed", "stopped", "dead"}:
        return status
    epoch = _parse_epoch_from_metrics(payload)
    if epoch is None:
        return "missing_timestamp"
    max_age = float(get_settings().vision_webrtc_compositor_heartbeat_max_age_s)
    age = max(0.0, time.time() - epoch)
    sidecar["compositor_heartbeat_age_s"] = round(age, 3)
    if age > max_age:
        return "stale"
    return "alive"


def _webrtc_sidecar_runtime_health(sidecar: dict[str, Any]) -> str:
    """Return live WebRTC sidecar HTTP health for discovery readiness."""

    settings = get_settings()
    if sidecar.get("status") != "configured":
        return "not_configured"
    health_url = sidecar.get("runtime_health_url")
    if not health_url:
        if settings.vision_webrtc_sidecar_assume_healthy_without_health_url:
            return "assume_healthy"
        return "unknown"
    request = UrlRequest(str(health_url), method="GET")
    try:
        with urlopen(request, timeout=settings.vision_webrtc_sidecar_health_timeout_s) as response:
            status = getattr(response, "status", 200)
            return "healthy" if status < 500 else "unhealthy"
    except HTTPError as exc:
        return "healthy" if exc.code < 500 else "unhealthy"
    except (OSError, TimeoutError, URLError):
        return "unhealthy"


def _webrtc_sidecar_path_runtime_health(sidecar: dict[str, Any]) -> str:
    """Return whether the requested MediaMTX path is online.

    MediaMTX versions do not all expose the same readiness field.  Treat any
    explicit truthy path-readiness marker as enough to prefer WebRTC, matching
    the sidecar/startup guard instead of requiring every marker simultaneously.
    """

    if sidecar.get("status") != "configured":
        return "not_configured"
    settings = get_settings()
    paths_api_url = settings.vision_webrtc_sidecar_paths_api_url.strip()
    if not paths_api_url:
        return "not_checked"
    path_id = str(sidecar.get("path_id") or "")
    if not path_id:
        return "missing_path_id"
    request = UrlRequest(paths_api_url, method="GET")
    try:
        with urlopen(request, timeout=settings.vision_webrtc_sidecar_health_timeout_s) as response:
            status = getattr(response, "status", 200)
            if status >= 500:
                return "api_unhealthy"
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return "api_unhealthy" if exc.code >= 500 else "api_unavailable"
    except (OSError, TimeoutError, URLError, ValueError, json.JSONDecodeError):
        return "api_unavailable"

    items = payload.get("items", []) if isinstance(payload, dict) else []
    for item in items:
        if not isinstance(item, dict) or item.get("name") != path_id:
            continue
        if any(bool(item.get(key)) for key in ("ready", "available", "online", "sourceReady")):
            return "online"
        return "offline"
    return "missing"


def _webrtc_transport_status(sidecar: dict[str, Any]) -> dict[str, Any]:
    """Compute Main-facing WebRTC discovery gates from live sidecar state."""

    settings = get_settings()
    answer_capable = bool(sidecar.get("whep_url"))
    configured = bool(
        settings.vision_webrtc_enabled and sidecar.get("status") == "configured" and answer_capable
    )
    runtime_health = _webrtc_sidecar_runtime_health(sidecar)
    path_runtime_health = _webrtc_sidecar_path_runtime_health(sidecar)
    compositor_runtime_health = _webrtc_compositor_runtime_health(sidecar)
    runtime_ok = runtime_health in {"healthy", "assume_healthy"}
    path_ok = path_runtime_health == "online"
    compositor_ok = compositor_runtime_health in {"alive", "not_required"}
    ready = configured and runtime_ok and path_ok and compositor_ok
    sidecar["answer_capable"] = answer_capable
    sidecar["runtime_health"] = runtime_health
    sidecar["path_runtime_health"] = path_runtime_health
    sidecar["compositor_runtime_health"] = compositor_runtime_health
    if ready:
        sidecar["status"] = "healthy"
    return {
        "configured": configured,
        "healthy": ready,
        "status": "ready"
        if ready
        else ("candidate" if settings.vision_webrtc_enabled else "disabled"),
    }


def stream_transports_for_source(source: str) -> list[dict[str, Any]]:
    settings = get_settings()
    source_definition = settings.source_registry.get(source)
    transports: list[dict[str, Any]] = []
    for view in source_definition.view_ids:
        fallback_path = overlay_stream_path(source, view)
        clean_path = frame_stream_path(source, view)
        metadata_path = overlay_metadata_path(source, view)
        media_profile = _webrtc_media_profile(source, view)
        transports.append(
            {
                "kind": "mjpeg",
                "status": "fallback_stable",
                "source": source,
                "view": view,
                "url": vision_gateway_url(fallback_path),
                "path": fallback_path,
                "fallback_path": fallback_path,
                "transport_origin": "http_mjpeg_gateway",
                "transport_class": "http_mjpeg_gateway",
                "transport_rank": 2,
                "transport_rank_order": "lower_is_preferred",
                "production_compatible_fallback": True,
                "media_only": True,
                "db_writes": False,
                "evidence_truth_mutation": False,
                "motion_command_allowed": False,
                "control_topics_published": [],
            }
        )
        sidecar = webrtc_sidecar_descriptor(source, view)
        transport_status = _webrtc_transport_status(sidecar)
        transports.append(
            {
                "kind": "webrtc",
                "configured": transport_status["configured"],
                "healthy": transport_status["healthy"],
                "status": transport_status["status"],
                "source": source,
                "view": view,
                "signaling": "http-post-offer-or-sidecar-whep",
                "offer_path": webrtc_offer_path(source, view),
                "fallback_path": fallback_path,
                "fallback_kind": "mjpeg",
                "clean_video_path": clean_path,
                "clean_video_url": vision_gateway_url(clean_path),
                "clean_video_role": "diagnostic_latest_frame_only_not_main_streaming_overlay_contract",
                "transport_origin": media_profile["transport_origin"],
                "transport_class": media_profile["transport_class"],
                "transport_rank": media_profile["transport_rank"],
                "transport_rank_order": "lower_is_preferred",
                "preferred_until_direct_media_ready": media_profile[
                    "preferred_until_direct_media_ready"
                ],
                "video_composition": media_profile["video_composition"],
                "overlay_mode": media_profile["overlay_mode"],
                "legacy_clean_video_config_ignored": media_profile[
                    "legacy_clean_video_config_ignored"
                ],
                "legacy_direct_media_config_ignored": media_profile[
                    "legacy_direct_media_config_ignored"
                ],
                "overlay_metadata": {
                    "kind": "vision_event_canvas_layer_diagnostic",
                    "path": metadata_path,
                    "url": vision_api_url(metadata_path),
                    "events_path": f"/api/v1/detections/latest?source={quote(source, safe='')}&limit=20",
                    "events_url": vision_api_url(
                        f"/api/v1/detections/latest?source={quote(source, safe='')}&limit=20"
                    ),
                    "recommended_refresh_fps": get_settings().vision_webrtc_overlay_refresh_fps,
                    "video_frame_reference": "latest_frame_seq",
                    "client_rendering": "diagnostic_only_not_required_for_main_streaming",
                    "recommended_for_main_streaming": False,
                    "diagnostic_only": True,
                },
                "media_only": True,
                "sidecar_required": True,
                "sidecar": sidecar,
                "db_writes": False,
                "evidence_truth_mutation": False,
                "motion_command_allowed": False,
                "control_topics_published": [],
            }
        )
    return transports


def webrtc_transport_policy() -> dict[str, Any]:
    return {
        "status": "primary_with_mjpeg_fallback",
        "primary_until_parity": "raw_frame_compositor_h264_webrtc",
        "production_compatible_fallback": "http_mjpeg_gateway",
        "preferred_order": [
            "raw_frame_compositor_h264_webrtc",
            "http_mjpeg_gateway",
        ],
        "legacy_or_internal_only": [
            "direct_clean_media_webrtc",
            "camera_input_h264_transcode_webrtc",
            "mjpeg_overlay_h264_transcode_webrtc",
            "client_canvas_metadata_overlay",
        ],
        "transport_rank_order": "lower_is_preferred",
        "promotion_gate": {
            "requires_backward_compatible_fields": True,
            "requires_health_check": True,
            "requires_latency_or_quality_evidence": True,
            "must_keep_mjpeg_fallback": True,
        },
        "current_webrtc_transport_origin": "vision_pc_compositor_publisher",
        "target_webrtc_transport_origin": "vision_pc_compositor_publisher",
        "target_webrtc_video_composition": "burned_overlay_video",
        "overlay_strategy": {
            "preferred": "burned_in_video",
            "metadata_endpoint": "/api/v1/vision/overlay/metadata?source={source}&view={view}",
            "metadata_endpoint_role": "diagnostic_only_not_required_for_main_streaming",
            "ai_refresh_fps": get_settings().vision_webrtc_overlay_refresh_fps,
            "video_refresh_fps_target": 30,
            "fallback": "http_mjpeg_overlay",
        },
        "browser_preference_order": ["webrtc", "mjpeg"],
        "fallback_kind": "mjpeg",
        "primary_stream_plane": "webrtc",
        "fallback_stream_plane": "http_mjpeg_gateway",
        "signaling_scope": "ephemeral_media_session_only",
        "media_only": True,
        "db_writes": False,
        "evidence_truth_mutation": False,
        "motion_command_allowed": False,
        "control_topics_published": [],
        "forbidden_capabilities": [
            "motion_command_publish",
            "nav2_action_call",
            "parameter_mutation",
            "full_rosbridge_graph_exposure",
            "db_write",
            "evidence_truth_mutation",
        ],
    }


def vision_stream_source_entry(
    source: str,
    *,
    stream_metrics: dict[str, Any],
    runtime_context: RuntimeContext,
    latest_overlay_image: LatestOverlayImageGetter,
    frame_age_s: FrameAgeGetter,
) -> dict[str, Any]:
    source_definition = get_settings().source_registry.get(source)
    physical_topic = _physical_input_topic_for_source(source)
    topic_exposure = _source_topic_exposure(source, physical_topic)
    return {
        "source": source,
        "default_view": DEFAULT_VIEW_ID,
        "available_views": list(source_definition.view_ids),
        "budgets": source_definition.budgets.as_snapshot(),
        "has_frame": runtime_context.frame_store.latest(source) is not None,
        "has_overlay": runtime_context.overlay_cache.latest(source) is not None,
        **frame_overlay_sync_status(source, runtime_context=runtime_context),
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
        "frame_ingest_path": "/api/v1/vision/frame",
        "mjpeg_path": f"/api/v1/vision/stream/{source}.mjpeg",
        "mjpeg_default_max_fps": 10,
        "frame_metadata_path": f"/api/v1/vision/frame/latest?source={source}",
        "frame_image_path": f"/api/v1/vision/frame/latest/image?source={source}",
        "overlay_metadata_path": f"/api/v1/vision/overlay/latest?source={source}",
        "overlay_image_path": f"/api/v1/vision/overlay/latest/image?source={source}",
        "source_snapshot_path": f"/api/v1/vision/debug/sources?source={source}",
        "worker_status_path": f"/api/v1/vision/worker/status?source={source}",
        "metrics_path": f"/api/v1/metrics?source={source}",
        "ros_handoff_path": "/api/v1/vision/ros/topics",
        "ros_handoff_source_path": f"/api/v1/vision/ros/topics?source={source}",
        "stream_metrics": stream_metrics["by_source"].get(source, _zero_stream_metrics()),
        "stream_transports": stream_transports_for_source(source),
    }


def vision_streams_summary(source_entries: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "sources_total": len(source_entries),
        "with_frame_count": sum(1 for item in source_entries if item["has_frame"]),
        "with_overlay_count": sum(1 for item in source_entries if item["has_overlay"]),
        "overlay_lag_count": sum(
            1
            for item in source_entries
            if isinstance(item.get("overlay_lag_frames"), int) and item["overlay_lag_frames"] > 0
        ),
        "synced_overlay_count": sum(
            1 for item in source_entries if item.get("overlay_lag_frames") == 0
        ),
        "stale_overlay_count": sum(
            1 for item in source_entries if item.get("overlay_visual_state") == "stale"
        ),
        "ros_ingest_contract_ready_count": sum(
            1
            for item in source_entries
            if item["ros_ingest_readiness"]["readiness_state"] == "contract_ready"
        ),
        "ros_ingest_runtime_subscriber_active_count": sum(
            1
            for item in source_entries
            if item["ros_ingest_readiness"]["runtime_subscriber_active"]
        ),
        "ros_ingest_status_counts": _count_by(
            source_entries, ("ros_ingest_readiness", "readiness_state")
        ),
        "ros_publish_ready_count": sum(
            1 for item in source_entries if item["ros_publish_readiness"]["overlay_ready"]
        ),
        "ros_publish_payload_available_count": sum(
            1
            for item in source_entries
            if item["ros_publish_readiness"]["publish_payload_preview"]["payload_available"]
        ),
        "ros_publish_payload_blocked_count": sum(
            1
            for item in source_entries
            if not item["ros_publish_readiness"]["publish_payload_preview"]["payload_available"]
        ),
        "ros_publish_status_counts": _count_by(
            source_entries, ("ros_publish_readiness", "readiness_state")
        ),
        "evidence_event_publish_ready_count": sum(
            1
            for item in source_entries
            if item["evidence_event_publish_readiness"]["publish_ready"]
        ),
    }


def build_vision_streams_payload(
    *,
    source: str | None,
    runtime_context: RuntimeContext,
    latest_overlay_image: LatestOverlayImageGetter,
    frame_age_s: FrameAgeGetter,
    now_iso: Callable[[], str],
) -> dict[str, Any]:
    settings = get_settings()
    stream_metrics = runtime_context.metrics.stream_snapshot()
    selected_sources = [
        source_id for source_id in settings.source_ids if source is None or source_id == source
    ]
    source_entries = [
        vision_stream_source_entry(
            source_id,
            stream_metrics=stream_metrics,
            runtime_context=runtime_context,
            latest_overlay_image=latest_overlay_image,
            frame_age_s=frame_age_s,
        )
        for source_id in selected_sources
    ]
    return {
        "generated_at": now_iso(),
        "requested_source": source,
        "primary_stream_plane": "webrtc",
        "fallback_stream_plane": "http_mjpeg_gateway",
        "candidate_stream_plane": "webrtc",
        "stream_base_url": vision_stream_base_url(),
        "fallback_stream_base_url": vision_stream_base_url(),
        "debug_only": False,
        "motion_command_allowed": False,
        "internal_rosbridge": {
            "scope": "operator_prototype_only",
            "url": "ws://<vision-host>:9090",
            "exposes_all_topics": False,
        },
        "control_topics_published": [],
        "webrtc_policy": webrtc_transport_policy(),
        "summary": vision_streams_summary(source_entries),
        "topic_exposure_policy": _ros_topic_exposure_policy(),
        "topic_exposure_summary": _topic_exposure_summary(source_entries),
        "runtime_policy": _ros_runtime_policy(),
        "debug_fallback": {
            "frame_ingest_path": "/api/v1/vision/frame",
            "mjpeg_path_template": "/api/v1/vision/stream/{source}.mjpeg",
            "mjpeg_max_fps_default": 10,
            "mjpeg_max_fps_limit": 30,
            "frame_metadata_path": "/api/v1/vision/frame/latest?source={source}",
            "frame_image_path": "/api/v1/vision/frame/latest/image?source={source}",
            "overlay_metadata_path": "/api/v1/vision/overlay/latest?source={source}",
            "overlay_image_path": "/api/v1/vision/overlay/latest/image?source={source}",
            "metrics_path": "/api/v1/metrics",
            "source_snapshot_path": "/api/v1/vision/debug/sources",
            "worker_status_path": "/api/v1/vision/worker/status",
            "ros_handoff_path": "/api/v1/vision/ros/topics",
        },
        "sources": source_entries,
    }
