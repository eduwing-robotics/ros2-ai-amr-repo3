from __future__ import annotations

import json
from asyncio import sleep as async_sleep
from collections.abc import Callable
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from functools import lru_cache, wraps
from inspect import isawaitable
from pathlib import Path
from time import perf_counter
from typing import Any, Literal
from urllib.error import HTTPError, URLError
from urllib.request import Request as UrlRequest
from urllib.request import urlopen
from uuid import uuid4

import cv2
from fastapi import Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from starlette.concurrency import run_in_threadpool

from ..config import REPO_ROOT, get_settings
from ..contracts import (
    ContractValidationError,
    validate_vision_event,
    validate_vision_monitor_event,
)
from ..detectors import (
    MarkerDetection,
    decode_image,
    detect_markers,
    generate_synthetic_aruco_frame,
)
from ..docking import CameraIntrinsics, MarkerPose, estimate_marker_pose
from ..evidence_cache import DEFAULT_VIEW_ID, normalize_view_id, source_view_key
from ..frame_store import StoredFrame
from ..map_roi import MapRoiTracker, map_roi_config_from_settings, snapshot_to_overlay_event
from ..model_adapters import ModelAdapterError, UltralyticsSegmenterAdapter, VisionModelConfig
from ..observability import structured_log
from ..openapi_schemas import (
    ERROR_RESPONSE_OPENAPI,
    METRICS_RESPONSE_OPENAPI,
    SOURCE_ID_OPENAPI_EXTRA,
    _debug_sources_response_schema,
    _detect_image_response_schema,
    _frame_ingest_response_schema,
    _frame_process_response_schema,
    _json_response_openapi,
    _latest_frame_response_schema,
    _lift_load_evaluate_response_schema,
    _overlay_canvas_metadata_response_schema,
    _person_hazard_latest_response_schema,
    _ros_handoff_response_schema,
    _synthetic_frame_response_schema,
    _vision_monitor_state_response_schema,
    _vision_monitor_states_response_schema,
    _vision_streams_response_schema,
    _worker_status_response_schema,
)
from ..overlay import OverlayRenderResult, render_overlay
from ..pose_profiles import ArucoPoseProfile, PoseProfileError, get_pose_profile
from ..runtime_state import RuntimeContext, default_runtime_context
from ..security import (
    require_main_hmac,
    require_vision_gateway_hmac,
)
from ..smart_roi import (
    ROI_CROP_VIEW_KINDS,
    SmartRoiSelection,
    crop_smart_roi,
    event_for_roi_overlay,
    select_smart_roi,
    translate_detector_result_from_roi_to_full,
)
from ..vision_interfaces import DetectorResult
from ..vision_monitor_policies import evaluate_lift_load_marker_burst
from ..vision_monitor_profiles import (
    LIFT_EVIDENCE_PROFILE_ID,
    LIFT_EVIDENCE_THRESHOLD_SET_ID,
    PERSON_DRIVE_PROFILE_ID,
    PERSON_DRIVE_THRESHOLD_SET_ID,
)
from ..vision_monitor_profiles import (
    POLICY_VERSION as VISION_MONITOR_POLICY_VERSION,
)
from ..vision_monitor_state import VisionMonitorStateError
from ..wms_client import emit_vision_events as default_emit_vision_events
from ..zone_roi import (
    ZoneRoi,
    ZoneRoiConfig,
    find_zone_by_id,
    load_zone_roi_config_cached,
    zone_contains_pixel,
    zone_roi_overlay_events,
)
from .dependencies import ContextGetter
from .vision_detection_endpoints import build_detect_image_response
from .vision_frame_endpoints import (
    build_frame_ingest_response,
    build_frame_process_response,
    build_latest_frame_image_response,
    build_latest_frame_response,
)
from .vision_overlay_endpoints import (
    build_debug_overlay_mjpeg_stream_response,
    build_latest_overlay_image_response,
    mjpeg_latest_overlay_generator,
)
from .vision_read_models import (
    _frame_id_for_source,
    _robot_id_for_source,
    _webrtc_compositor_runtime_health,
    build_metrics_snapshot_payload,
    build_vision_debug_sources_payload,
    build_vision_ros_topics_payload,
    build_vision_streams_payload,
    build_vision_worker_status_payload,
    overlay_metadata_path,
    overlay_publish_payload_preview_for_source,
    overlay_stream_path,
    vision_gateway_url,
    webrtc_offer_path,
    webrtc_sidecar_descriptor,
)

PoseRequest = tuple[float, CameraIntrinsics] | ArucoPoseProfile

_context_getter_var: ContextVar[ContextGetter] = ContextVar(
    "smartfactory_ai_server_vision_context_getter",
    default=lambda: default_runtime_context,
)
_emit_vision_events_getter_var: ContextVar[Callable[[], Any]] = ContextVar(
    "smartfactory_ai_server_vision_emit_vision_events_getter",
    default=lambda: default_emit_vision_events,
)
_lift_roi_segmenter_getter_var: ContextVar[Callable[[], Any]] = ContextVar(
    "smartfactory_ai_server_vision_lift_roi_segmenter_getter",
    default=lambda: _get_lift_roi_segmenter,
)


def _runtime_context() -> RuntimeContext:
    return _context_getter_var.get()()


def _emit_vision_events():
    return _emit_vision_events_getter_var.get()()


def _lift_roi_segmenter():
    return _lift_roi_segmenter_getter_var.get()()


def _map_roi_overlay_events(
    *,
    source: str,
    detections: list[MarkerDetection],
    image_width: int,
    image_height: int,
    frame_seq: int | None,
) -> list[dict[str, Any]]:
    try:
        config = map_roi_config_from_settings(get_settings())
    except ValueError as exc:
        _runtime_context().logger.warning("invalid Map ROI overlay config: %s", exc)
        return []
    if not config.enabled or source != config.source:
        return []
    context = _runtime_context()
    with context.map_roi_trackers_lock:
        tracker = context.map_roi_trackers.get(source)
        if not isinstance(tracker, MapRoiTracker):
            tracker = MapRoiTracker()
            context.map_roi_trackers[source] = tracker
        snapshot = tracker.update(
            source=source,
            detections=detections,
            image_width=image_width,
            image_height=image_height,
            config=config,
        )
    if snapshot is None:
        return []
    event = snapshot_to_overlay_event(
        snapshot, label=config.label, frame_seq=frame_seq, timestamp=_now_iso()
    )
    return [event] if event is not None else []


def _zone_roi_config_from_settings(settings: Any) -> ZoneRoiConfig | None:
    enabled = bool(getattr(settings, "vision_zone_roi_enabled", False))
    if not enabled:
        return None
    path = Path(getattr(settings, "vision_zone_roi_config_path", ""))
    if not path.is_absolute():
        path = REPO_ROOT / path
    try:
        config = load_zone_roi_config_cached(str(path), enabled)
    except (OSError, ValueError) as exc:
        _runtime_context().logger.warning("invalid Zone ROI overlay config: %s", exc)
        return None
    source_override = str(getattr(settings, "vision_zone_roi_source", "") or "").strip()
    if source_override and source_override != config.source:
        return ZoneRoiConfig(
            enabled=config.enabled,
            source=source_override,
            coordinate_space=config.coordinate_space,
            zones=config.zones,
            status=config.status,
        )
    return config


def _zone_roi_overlay_events(
    *,
    source: str,
    image_width: int,
    image_height: int,
    frame_seq: int | None,
) -> list[dict[str, Any]]:
    config = _zone_roi_config_from_settings(get_settings())
    if config is None:
        return []
    return zone_roi_overlay_events(
        config,
        source=source,
        image_width=image_width,
        image_height=image_height,
        frame_seq=frame_seq,
        timestamp=_now_iso(),
    )


class SyntheticFrameRequest(BaseModel):
    """Robot-free synthetic frame ingest request for Lane B debug validation."""

    source: str = Field(..., json_schema_extra=SOURCE_ID_OPENAPI_EXTRA)
    marker_id: int = Field(default=7, ge=0, le=49)
    marker_size: int = Field(default=96, ge=16, le=512)
    padding: int = Field(default=32, ge=0, le=512)
    stale: bool = False
    emit: bool = False


class VisionWorkerTickRequest(BaseModel):
    """Controlled one-shot latest-frame processing tick for Lane B validation."""

    source: str | None = Field(default=None, json_schema_extra=SOURCE_ID_OPENAPI_EXTRA)
    force: bool = False
    stale: bool = False
    max_frame_age_s: float | None = Field(default=None, ge=0)


class VisionMonitorStateRequest(BaseModel):
    """No-hardware monitor enable/disable/update request.

    This stores advisory monitor intent only. It does not start motion, issue
    HOLD/E-stop commands, write Main DB rows, or run model inference.
    """

    enabled: bool = True
    source: str | None = Field(default=None, json_schema_extra=SOURCE_ID_OPENAPI_EXTRA)
    robot_id: str | None = None
    task_id: int | str | None = None
    operation_state: str = "UNKNOWN"
    target_fps: float | None = Field(default=None, gt=0)
    profile_id: str | None = None
    policy_version: str = VISION_MONITOR_POLICY_VERSION
    threshold_set_id: str | None = None


class LiftLoadEvaluateRequest(BaseModel):
    """Main-facing one-shot lift/load evidence request.

    Main owns task/command/location identity. AI Server only maps the requested
    ZoneROI plus expected ArUco marker observations into compact evidence.
    """

    model_config = ConfigDict(extra="forbid")

    source: Literal["global_cam_01"] = "global_cam_01"
    robot_id: Literal["tb3_1", "tb3_2"]
    task_id: int | str | None = None
    command_id: int | str | None = None
    operation: Literal[
        "PICK_UP",
        "PICKUP",
        "DROP_OFF",
        "DROPOFF",
        "PRE_DROP_OFF",
        "PRE_DROPOFF",
    ]
    expected_item_id: str | None = None
    expected_marker_id: str | int | None = None
    expected_marker_ids: list[str | int] | None = None
    expected_item_count: int = Field(default=1, ge=1, le=10)
    location_id: str | None = None
    vision_zone_id: str | None = None
    burst_frames: int = Field(default=10, ge=1, le=10)
    min_pass_frames: int = Field(default=1, ge=1, le=10)
    sample_interval_ms: int = Field(default=80, ge=0, le=500)
    max_frame_age_s: float = Field(default=2.0, ge=0)

    @model_validator(mode="after")
    def _validate_burst_threshold(self) -> "LiftLoadEvaluateRequest":
        if self.min_pass_frames is not None and self.min_pass_frames > self.burst_frames:
            raise ValueError("min_pass_frames must be <= burst_frames")
        return self


class WebRtcOfferRequest(BaseModel):
    """Media-only WebRTC offer probe request.

    The AI Server route is an additive media-only broker. It never publishes
    ROS control, mutates evidence truth, or writes Main DB state. When a WHEP
    sidecar is configured, this endpoint proxies the browser SDP offer to that
    sidecar and returns the SDP answer in the Main-facing contract.
    """

    sdp: str | None = None
    type: str = Field(default="offer")
    force_fallback: bool = False


@dataclass(frozen=True)
class ResolvedVisionModelConfig:
    model_path: str
    task: str
    confidence: float
    iou: float
    image_size: int
    device: str
    class_map_json: str
    unmapped_class: str


@lru_cache(maxsize=16)
def _parse_vision_model_class_map(class_map_json: str) -> dict[str, str]:
    if not class_map_json.strip():
        return {}
    try:
        parsed = json.loads(class_map_json)
    except json.JSONDecodeError as exc:
        raise ModelAdapterError("vision model class map must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ModelAdapterError("vision model class map must be a JSON object")
    return {str(key): str(value) for key, value in parsed.items()}


@lru_cache(maxsize=1)
def _parse_vision_model_source_config(source_config_json: str) -> dict[str, dict[str, Any]]:
    if not source_config_json.strip():
        return {}
    try:
        parsed = json.loads(source_config_json)
    except json.JSONDecodeError as exc:
        raise ModelAdapterError("vision model source config must be valid JSON") from exc
    if not isinstance(parsed, dict):
        raise ModelAdapterError("vision model source config must be a JSON object")
    configs: dict[str, dict[str, Any]] = {}
    for source, raw_config in parsed.items():
        if not isinstance(raw_config, dict):
            raise ModelAdapterError("each vision model source config must be a JSON object")
        configs[str(source)] = dict(raw_config)
    return configs


def _truthy_json_value(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() not in {"0", "false", "no", "off", "disabled"}
    return default


def _source_class_map_json(raw_config: dict[str, Any], fallback: str) -> str:
    if "class_map_json" in raw_config:
        return str(raw_config["class_map_json"])
    if "class_map" in raw_config:
        class_map = raw_config["class_map"]
        if not isinstance(class_map, dict):
            raise ModelAdapterError("source class_map must be a JSON object")
        return json.dumps(
            {str(key): str(value) for key, value in class_map.items()}, sort_keys=True
        )
    return fallback


def _resolved_model_config_for_source(source: str) -> ResolvedVisionModelConfig | None:
    settings = get_settings()
    if not settings.vision_model_worker_enabled:
        return None
    config = ResolvedVisionModelConfig(
        model_path=settings.vision_model_path,
        task=settings.vision_model_task,
        confidence=float(settings.vision_model_conf),
        iou=float(settings.vision_model_iou),
        image_size=int(settings.vision_model_imgsz),
        device=settings.vision_model_device,
        class_map_json=settings.vision_model_class_map_json,
        unmapped_class=settings.vision_model_unmapped_class,
    )
    source_configs = _parse_vision_model_source_config(settings.vision_model_source_config_json)
    raw_config = source_configs.get(source)
    if raw_config is not None:
        if not _truthy_json_value(raw_config.get("enabled"), default=True):
            return None
        config = ResolvedVisionModelConfig(
            model_path=str(raw_config.get("model_path", raw_config.get("path", config.model_path))),
            task=str(raw_config.get("task", config.task)),
            confidence=float(
                raw_config.get("confidence", raw_config.get("conf", config.confidence))
            ),
            iou=float(raw_config.get("iou", config.iou)),
            image_size=int(
                raw_config.get("image_size", raw_config.get("imgsz", config.image_size))
            ),
            device=str(raw_config.get("device", config.device)),
            class_map_json=_source_class_map_json(raw_config, config.class_map_json),
            unmapped_class=str(raw_config.get("unmapped_class", config.unmapped_class)),
        )
    if config.task not in {"segment", "detect"}:
        raise ModelAdapterError("vision model task must be 'segment' or 'detect'")
    if not config.model_path.strip():
        return None
    return config


@lru_cache(maxsize=8)
def _get_lift_roi_segmenter(
    *,
    model_path: str,
    task: str,
    confidence: float,
    iou: float,
    image_size: int,
    device: str,
    class_map_json: str,
    unmapped_class: str,
) -> UltralyticsSegmenterAdapter:
    return UltralyticsSegmenterAdapter(
        VisionModelConfig(
            model_path=model_path,
            task=task,
            confidence=confidence,
            iou=iou,
            image_size=image_size,
            device=device,
            class_map=_parse_vision_model_class_map(class_map_json),
            unmapped_class=unmapped_class,
        )
    )


def _ensure_known_source(source: str) -> None:
    if source not in get_settings().source_ids:
        raise HTTPException(status_code=400, detail=f"unknown source: {source}")


def _ensure_known_source_view(source: str, view: str | None = None) -> str:
    _ensure_known_source(source)
    view_id = normalize_view_id(view)
    try:
        get_settings().source_registry.resolve_view(source, view_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"unknown view for source {source}: {view_id}",
        ) from exc
    return view_id


def _store_overlay_result(
    result: OverlayRenderResult,
    *,
    events: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None = None,
) -> None:
    context = _runtime_context()
    metadata = result.metadata()
    with context.overlay_images_lock:
        # Keep overlay metadata, image bytes, and the compositor metadata event
        # layer as one internal snapshot for /overlay/metadata readers.
        context.overlay_cache.add(metadata, view=result.view)
        key = source_view_key(result.source, result.view)
        context.overlay_images[key] = result
        if events is not None:
            context.overlay_event_layers[key] = (
                result.frame_seq,
                [dict(event) for event in events],
            )
        else:
            context.overlay_event_layers.pop(key, None)
        if result.view == DEFAULT_VIEW_ID:
            context.overlay_images[result.source] = result
            if events is not None:
                context.overlay_event_layers[result.source] = (
                    result.frame_seq,
                    [dict(event) for event in events],
                )
            else:
                context.overlay_event_layers.pop(result.source, None)


def _latest_overlay_metadata_snapshot(
    source: str,
    *,
    view: str = DEFAULT_VIEW_ID,
    runtime_context: RuntimeContext | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]] | None]:
    context = runtime_context or _runtime_context()
    view_id = normalize_view_id(view)
    with context.overlay_images_lock:
        overlay = context.overlay_cache.latest(source, view=view_id)
        if overlay is None:
            raise HTTPException(
                status_code=404,
                detail=f"no overlay available for source/view: {source}/{view_id}",
            )
        if _latest_frame_is_stale(source, runtime_context=context):
            overlay = {**overlay, "stale": True, "visual_state": "stale"}
        cached = context.overlay_event_layers.get(source_view_key(source, view_id))
        if cached is None and view_id == DEFAULT_VIEW_ID:
            cached = context.overlay_event_layers.get(source)
        if cached is None:
            return overlay, None
        cached_frame_seq, events = cached
        overlay_frame_seq = overlay.get("frame_seq")
        if not isinstance(overlay_frame_seq, int) or cached_frame_seq != overlay_frame_seq:
            return overlay, None
        return overlay, [dict(event) for event in events]


def _overlay_sync_status_for_snapshot(
    source: str,
    *,
    overlay: dict[str, Any],
    runtime_context: RuntimeContext | None = None,
) -> dict[str, Any]:
    context = runtime_context or _runtime_context()
    frame = context.frame_store.latest(source)
    frame_seq = frame.frame_seq if frame is not None else None
    overlay_frame_seq = overlay.get("frame_seq") if isinstance(overlay, dict) else None
    overlay_lag_frames = (
        max(0, frame_seq - overlay_frame_seq)
        if isinstance(frame_seq, int) and isinstance(overlay_frame_seq, int)
        else None
    )
    return {
        "latest_frame_seq": frame_seq,
        "latest_overlay_frame_seq": overlay_frame_seq,
        "overlay_lag_frames": overlay_lag_frames,
        "overlay_visual_state": overlay.get("visual_state") if isinstance(overlay, dict) else None,
    }


def _latest_overlay_image(
    source: str,
    *,
    view: str = DEFAULT_VIEW_ID,
    runtime_context: RuntimeContext | None = None,
) -> OverlayRenderResult | None:
    context = runtime_context or _runtime_context()
    view_id = normalize_view_id(view)
    with context.overlay_images_lock:
        overlay = context.overlay_images.get(source_view_key(source, view_id))
        if overlay is None and view_id == DEFAULT_VIEW_ID:
            overlay = context.overlay_images.get(source)
        cached = context.overlay_event_layers.get(source_view_key(source, view_id))
        if cached is None and view_id == DEFAULT_VIEW_ID:
            cached = context.overlay_event_layers.get(source)
    if overlay is None or overlay.stale or not _latest_frame_is_stale(
        source, runtime_context=context
    ):
        return overlay
    frame = context.frame_store.latest(source)
    if frame is None or frame.frame_seq != overlay.frame_seq:
        return overlay
    events = cached[1] if cached is not None and cached[0] == frame.frame_seq else []
    return render_overlay(frame, events=events, stale=True, view=view_id)


def _now_dt() -> datetime:
    return datetime.now(timezone.utc).astimezone()


def _now_iso() -> str:
    return _now_dt().isoformat()


def _frame_age_s(frame: StoredFrame, *, now: datetime | None = None) -> float:
    current = now or _now_dt()
    timestamp = datetime.fromisoformat(frame.timestamp)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return max(0.0, (current - timestamp).total_seconds())


def _latest_frame_is_stale(
    source: str,
    *,
    runtime_context: RuntimeContext | None = None,
) -> bool:
    context = runtime_context or _runtime_context()
    frame = context.frame_store.latest(source)
    return frame is not None and _frame_age_s(frame) > get_settings().source_stale_after_s


def _overlay_publish_payload_preview_for_source(source: str) -> dict[str, Any]:
    return overlay_publish_payload_preview_for_source(
        source,
        runtime_context=_runtime_context(),
        latest_overlay_image=_latest_overlay_image,
    )


def _pose_confidence(pose: MarkerPose) -> float:
    return round(max(0.0, min(1.0, 1.0 - pose.reprojection_error_px / 5.0)), 3)


def _pose_estimate_payload(pose: MarkerPose) -> dict[str, Any]:
    return {
        "method": "ARUCO_POSE",
        "x": pose.lateral_m,
        "y": pose.distance_m,
        "yaw": pose.yaw_rad,
        "confidence": _pose_confidence(pose),
    }


def _event_metadata(
    *,
    model: str | None,
    image_width: int,
    image_height: int,
    latency_ms: float | None,
    frame_seq: int | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "n_frame_count": 1,
        "policy_version": get_settings().policy_version,
        "model": model,
        "image_width": image_width,
        "image_height": image_height,
        "latency_ms": latency_ms,
    }
    if frame_seq is not None:
        metadata["frame_seq"] = int(frame_seq)
    return metadata


def build_marker_event(
    *,
    source: str,
    detection: MarkerDetection,
    image_width: int,
    image_height: int,
    latency_ms: float | None = None,
    pose: MarkerPose | None = None,
    frame_seq: int | None = None,
) -> dict[str, Any]:
    """Build a schema-valid VisionEvent from a deterministic marker detection."""
    settings = get_settings()
    event: dict[str, Any] = {
        "schema_version": settings.vision_event_schema_version,
        "event_id": str(uuid4()),
        "timestamp": _now_iso(),
        "source": source,
        "robot_id": _robot_id_for_source(source),
        "frame_id": _frame_id_for_source(source),
        "event_kind": "CONFIRMED",
        "class_name": detection.class_name,
        "confidence": detection.confidence,
        "bbox_xyxy": detection.bbox_xyxy,
        "marker_id": detection.marker_id,
        "zone": None,
        "roi_id": None,
        "track_id": None,
        "pose_estimate": _pose_estimate_payload(pose) if pose is not None else None,
        "depth_median_m": None,
        "wms_hint": "TAG_DETECTED",
        "metadata": _event_metadata(
            model=detection.detector,
            image_width=image_width,
            image_height=image_height,
            latency_ms=latency_ms,
            frame_seq=frame_seq,
        ),
    }
    validate_vision_event(event)
    return event


def _normalize_public_model_class(raw_class_name: str) -> str:
    settings = get_settings()
    try:
        class_map = _parse_vision_model_class_map(settings.vision_model_class_map_json)
    except ModelAdapterError:
        class_map = {}
    mapped = class_map.get(raw_class_name, raw_class_name)
    allowed = {"person", "obstacle", "box", "dropped_item", "pallet", "unknown"}
    if mapped in allowed:
        return mapped
    fallback = settings.vision_model_unmapped_class
    return fallback if fallback in allowed else "unknown"


def _model_wms_hint(class_name: str) -> str | None:
    return {
        "person": "PERSON_CANDIDATE",
        "obstacle": "OBSTACLE_CANDIDATE",
        "box": "ITEM_CANDIDATE",
        "pallet": "ITEM_CANDIDATE",
        "dropped_item": "DROPPED_ITEM_CANDIDATE",
    }.get(class_name)


def _bbox_payload(result: DetectorResult) -> list[float]:
    bbox = getattr(result, "bbox_xyxy")
    return [float(value) for value in bbox]


def build_model_event(
    *,
    source: str,
    result: DetectorResult,
    image_width: int,
    image_height: int,
    latency_ms: float | None = None,
    frame_seq: int | None = None,
) -> dict[str, Any]:
    """Build a candidate VisionEvent from optional model output for ROS overlay streaming."""
    settings = get_settings()
    class_name = _normalize_public_model_class(str(getattr(result, "class_name", "unknown")))
    event: dict[str, Any] = {
        "schema_version": settings.vision_event_schema_version,
        "event_id": str(uuid4()),
        "timestamp": _now_iso(),
        "source": source,
        "robot_id": _robot_id_for_source(source),
        "frame_id": _frame_id_for_source(source),
        "event_kind": "CANDIDATE",
        "class_name": class_name,
        "confidence": float(getattr(result, "confidence", 0.0)),
        "bbox_xyxy": _bbox_payload(result),
        "marker_id": None,
        "zone": None,
        "roi_id": None,
        "track_id": getattr(result, "track_id", None),
        "pose_estimate": None,
        "depth_median_m": None,
        "wms_hint": _model_wms_hint(class_name),
        "metadata": _event_metadata(
            model=getattr(result, "detector", None),
            image_width=image_width,
            image_height=image_height,
            latency_ms=latency_ms,
            frame_seq=frame_seq,
        ),
    }
    validate_vision_event(event)
    return event


def _parse_dist_coeffs(value: str | None) -> tuple[float, ...]:
    if value is None or value.strip() == "":
        return ()
    try:
        return tuple((float(part.strip()) for part in value.split(",") if part.strip()))
    except ValueError as exc:
        raise HTTPException(
            status_code=400, detail="camera_dist_coeffs must be comma-separated numbers"
        ) from exc


def _manual_pose_fields_present(
    *,
    marker_size_m: float | None,
    camera_fx: float | None,
    camera_fy: float | None,
    camera_cx: float | None,
    camera_cy: float | None,
    camera_dist_coeffs: str | None,
) -> bool:
    return any(
        (
            value is not None
            for value in [
                marker_size_m,
                camera_fx,
                camera_fy,
                camera_cx,
                camera_cy,
                camera_dist_coeffs,
            ]
        )
    )


def _optional_pose_request(
    *,
    pose_profile: str | None,
    marker_size_m: float | None,
    camera_fx: float | None,
    camera_fy: float | None,
    camera_cx: float | None,
    camera_cy: float | None,
    camera_dist_coeffs: str | None,
) -> PoseRequest | None:
    settings = get_settings()
    manual_present = _manual_pose_fields_present(
        marker_size_m=marker_size_m,
        camera_fx=camera_fx,
        camera_fy=camera_fy,
        camera_cx=camera_cx,
        camera_cy=camera_cy,
        camera_dist_coeffs=camera_dist_coeffs,
    )
    if pose_profile is not None and pose_profile.strip():
        if manual_present:
            raise HTTPException(
                status_code=400,
                detail="pose_profile cannot be combined with manual camera calibration fields",
            )
        try:
            return get_pose_profile(pose_profile, path=settings.aruco_pose_profiles_path)
        except PoseProfileError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
    fields = [marker_size_m, camera_fx, camera_fy, camera_cx, camera_cy]
    if all((value is None for value in fields)) and (not camera_dist_coeffs):
        return None
    if any((value is None for value in fields)):
        raise HTTPException(
            status_code=400,
            detail="ArUco pose requires marker_size_m, camera_fx, camera_fy, camera_cx, and camera_cy together",
        )
    assert marker_size_m is not None
    assert camera_fx is not None
    assert camera_fy is not None
    assert camera_cx is not None
    assert camera_cy is not None
    if marker_size_m <= 0:
        raise HTTPException(status_code=400, detail="marker_size_m must be positive")
    if camera_fx <= 0 or camera_fy <= 0:
        raise HTTPException(status_code=400, detail="camera_fx and camera_fy must be positive")
    return (
        marker_size_m,
        CameraIntrinsics(
            fx=camera_fx,
            fy=camera_fy,
            cx=camera_cx,
            cy=camera_cy,
            dist_coeffs=_parse_dist_coeffs(camera_dist_coeffs),
        ),
    )


def _estimate_detection_pose(
    *, source: str, detection: MarkerDetection, pose_request: PoseRequest | None
) -> MarkerPose | None:
    if pose_request is None or not detection.corners_xy:
        return None
    if isinstance(pose_request, ArucoPoseProfile):
        if not pose_request.applies_to(source=source, marker_id=detection.marker_id):
            return None
        marker_size_m = pose_request.marker_size_m
        intrinsics = pose_request.intrinsics
    else:
        marker_size_m, intrinsics = pose_request
    try:
        return estimate_marker_pose(
            detection.corners_xy, marker_size_m=marker_size_m, intrinsics=intrinsics
        )
    except ValueError:
        return None


def _roi_crop_views_for_source(source: str) -> tuple[str, ...]:
    try:
        source_definition = get_settings().source_registry.get(source)
    except KeyError:
        return ()
    return tuple(
        view.view_id
        for view in source_definition.views
        if view.view_id != DEFAULT_VIEW_ID and view.kind in ROI_CROP_VIEW_KINDS
    )


def _crop_frame_from_selection(
    *,
    source_frame: StoredFrame,
    crop_image,
    selection: SmartRoiSelection,
) -> StoredFrame:
    ok, buffer = cv2.imencode(".jpg", crop_image)
    if not ok:
        raise ValueError("failed to encode smart ROI crop as JPEG")
    crop_height, crop_width = crop_image.shape[:2]
    return StoredFrame(
        source=source_frame.source,
        frame_seq=source_frame.frame_seq,
        timestamp=source_frame.timestamp,
        image_width=int(crop_width),
        image_height=int(crop_height),
        encoded=buffer.tobytes(),
        content_type="image/jpeg",
        decoded_bgr=crop_image,
    )


def _prepare_roi_view_overlays(
    *,
    source: str,
    frame: StoredFrame,
    decoded_image,
    full_frame_events: list[dict[str, Any]],
    full_image_width: int,
    full_image_height: int,
    stale: bool,
) -> tuple[list[dict[str, Any]], list[OverlayRenderResult]]:
    """Generate crop-first view overlays and full-frame mapped ROI detections."""

    settings = get_settings()
    try:
        source_model_config = _resolved_model_config_for_source(source)
    except ModelAdapterError:
        source_model_config = None
    model_input_size = (
        source_model_config.image_size
        if source_model_config is not None
        else int(settings.vision_model_imgsz)
    )
    model_input_size_px = (int(model_input_size), int(model_input_size))
    mapped_events: list[dict[str, Any]] = []
    roi_overlays: list[OverlayRenderResult] = []
    for view_id in _roi_crop_views_for_source(source):
        try:
            selection = select_smart_roi(
                decoded_image,
                view_id=view_id,
                model_input_size_px=model_input_size_px,
            )
            crop_image = crop_smart_roi(decoded_image, selection)
            crop_height, crop_width = crop_image.shape[:2]
            crop_results, crop_latency_ms = _detect_model_results(
                source=source, decoded_image=crop_image
            )
            crop_overlay_events = _events_from_model_results(
                source=source,
                detector_results=crop_results,
                image_width=crop_width,
                image_height=crop_height,
                latency_ms=crop_latency_ms,
                frame_seq=frame.frame_seq,
                roi_selection=selection,
                map_roi_to_full_frame=False,
            )
            mapped_events.extend(
                _events_from_model_results(
                    source=source,
                    detector_results=crop_results,
                    image_width=full_image_width,
                    image_height=full_image_height,
                    latency_ms=crop_latency_ms,
                    frame_seq=frame.frame_seq,
                    roi_selection=selection,
                    map_roi_to_full_frame=True,
                )
            )
            transformed_full_events = [
                roi_event
                for event in full_frame_events
                if (roi_event := event_for_roi_overlay(event, selection)) is not None
            ]
            crop_frame = _crop_frame_from_selection(
                source_frame=frame,
                crop_image=crop_image,
                selection=selection,
            )
            roi_overlays.append(
                render_overlay(
                    crop_frame,
                    events=[*transformed_full_events, *crop_overlay_events],
                    stale=stale,
                    view=view_id,
                )
            )
        except (ValueError, TypeError):
            continue
    return mapped_events, roi_overlays


def _detect_and_overlay_frame_snapshot(
    *, frame: StoredFrame, pose_request: PoseRequest | None = None, stale: bool = False
) -> dict[str, Any]:
    """Run marker detection on an already-stored latest-frame snapshot."""
    if frame.decoded_bgr is None:
        decoded_image = decode_image(frame.encoded)
    else:
        decoded_image = frame.decoded_bgr
    image_height, image_width = decoded_image.shape[:2]
    started = perf_counter()
    detections = detect_markers(decoded_image)
    latency_ms = round((perf_counter() - started) * 1000.0, 3)
    events = [
        build_marker_event(
            source=frame.source,
            detection=detection,
            image_width=image_width,
            image_height=image_height,
            latency_ms=latency_ms,
            pose=_estimate_detection_pose(
                source=frame.source, detection=detection, pose_request=pose_request
            ),
            frame_seq=frame.frame_seq,
        )
        for detection in detections
    ]
    events.extend(
        _detect_model_events(
            source=frame.source,
            decoded_image=decoded_image,
            image_width=image_width,
            image_height=image_height,
            frame_seq=frame.frame_seq,
        )
    )
    roi_events, roi_overlays = _prepare_roi_view_overlays(
        source=frame.source,
        frame=frame,
        decoded_image=decoded_image,
        full_frame_events=list(events),
        full_image_width=image_width,
        full_image_height=image_height,
        stale=stale,
    )
    events.extend(roi_events)
    for event in events:
        _runtime_context().store.add(event)
        _runtime_context().source_health.record_event(event)
    overlay_events = [
        *events,
        *_map_roi_overlay_events(
            source=frame.source,
            detections=detections,
            image_width=image_width,
            image_height=image_height,
            frame_seq=frame.frame_seq,
        ),
        *_zone_roi_overlay_events(
            source=frame.source,
            image_width=image_width,
            image_height=image_height,
            frame_seq=frame.frame_seq,
        ),
    ]
    overlay = render_overlay(frame, events=overlay_events, stale=stale)
    _store_overlay_result(overlay, events=overlay_events)
    for roi_overlay in roi_overlays:
        _store_overlay_result(roi_overlay)
    _runtime_context().metrics.record_detect_image(event_count=len(events))
    return {"frame": frame, "events": events, "overlay_events": overlay_events, "overlay": overlay}


def _store_latest_frame_from_bytes(
    *, source: str, payload: bytes, content_type: str
) -> StoredFrame:
    """Decode and store one latest frame for HTTP debug ingest or future ROS callbacks.

    This adapter intentionally performs no detection, overlay rendering, ROS2
    spinning, or publishing. It is the common Lane B/C seam that a future
    background ROS subscriber callback can call after receiving an image
    message, while FastAPI handlers continue to read cached state only.
    """
    _ensure_known_source(source)
    decoded_image = decode_image(payload)
    frame = _runtime_context().frame_store.put_decoded(
        source=source, image_bgr=decoded_image, encoded=payload, content_type=content_type
    )
    _runtime_context().source_health.record_frame(source, at=_now_dt())
    return frame


def _frame_ingest_context(
    *, transport: str, topic: str | None, processed_inline: bool = False
) -> dict[str, Any]:
    return {
        "transport": transport,
        "topic": topic,
        "stored_in_latest_frame_cache": True,
        "processed_inline": processed_inline,
        "source_health_updated": True,
        "ros_callback_compatible": True,
    }


def _detect_and_overlay_decoded_frame(
    *,
    source: str,
    decoded_image,
    encoded: bytes | None = None,
    content_type: str = "image/jpeg",
    pose_request: PoseRequest | None = None,
    stale: bool = False,
) -> dict[str, Any]:
    """Store latest frame, run marker detection, update evidence overlay state."""
    _ensure_known_source(source)
    frame = _runtime_context().frame_store.put_decoded(
        source=source, image_bgr=decoded_image, encoded=encoded, content_type=content_type
    )
    _runtime_context().source_health.record_frame(source, at=_now_dt())
    return _detect_and_overlay_frame_snapshot(frame=frame, pose_request=pose_request, stale=stale)


def _model_worker_enabled(settings) -> bool:
    return bool(settings.vision_model_worker_enabled and settings.vision_model_path.strip())


def _detect_model_results(
    *, source: str, decoded_image
) -> tuple[tuple[DetectorResult, ...], float | None]:
    try:
        config = _resolved_model_config_for_source(source)
    except ModelAdapterError:
        return (), None
    if config is None:
        return (), None
    try:
        provider = _lift_roi_segmenter()(
            model_path=config.model_path,
            task=config.task,
            confidence=config.confidence,
            iou=config.iou,
            image_size=config.image_size,
            device=config.device,
            class_map_json=config.class_map_json,
            unmapped_class=config.unmapped_class,
        )
        started = perf_counter()
        detector_results = tuple(provider.detect(decoded_image))
        latency_ms = round((perf_counter() - started) * 1000.0, 3)
    except ModelAdapterError:
        return (), None
    return detector_results, latency_ms


def _events_from_model_results(
    *,
    source: str,
    detector_results: tuple[DetectorResult, ...],
    image_width: int,
    image_height: int,
    latency_ms: float | None,
    frame_seq: int | None = None,
    roi_selection: SmartRoiSelection | None = None,
    map_roi_to_full_frame: bool = False,
) -> list[dict[str, Any]]:
    settings = get_settings()
    max_events = max(0, int(settings.vision_model_max_events))
    model_events: list[dict[str, Any]] = []
    for result in detector_results[:max_events]:
        try:
            event_result = (
                translate_detector_result_from_roi_to_full(result, roi_selection)
                if roi_selection is not None and map_roi_to_full_frame
                else result
            )
            event = build_model_event(
                source=source,
                result=event_result,
                image_width=image_width,
                image_height=image_height,
                latency_ms=latency_ms,
                frame_seq=frame_seq,
            )
            if roi_selection is not None:
                event["roi_id"] = roi_selection.view_id
                validate_vision_event(event)
            model_events.append(event)
        except (ContractValidationError, ValueError, TypeError):
            continue
    return model_events


def _detect_model_events(
    *, source: str, decoded_image, image_width: int, image_height: int, frame_seq: int | None = None
) -> list[dict[str, Any]]:
    detector_results, latency_ms = _detect_model_results(source=source, decoded_image=decoded_image)
    return _events_from_model_results(
        source=source,
        detector_results=detector_results,
        image_width=image_width,
        image_height=image_height,
        latency_ms=latency_ms,
        frame_seq=frame_seq,
    )


def vision_streams(
    source: str | None = Query(default=None, json_schema_extra=SOURCE_ID_OPENAPI_EXTRA),
) -> dict[str, Any]:
    """Describe Vision Gateway stream surfaces.

    Main-facing production browser video uses burned-overlay WebRTC as the
    primary plane with the source-selected HTTP/MJPEG Vision Stream Gateway on
    :8090 as fallback. ROS/rosbridge is internal allowlisted
    operator/prototype infrastructure only.
    """
    if source is not None:
        _ensure_known_source(source)
    return build_vision_streams_payload(
        source=source,
        runtime_context=_runtime_context(),
        latest_overlay_image=_latest_overlay_image,
        frame_age_s=_frame_age_s,
        now_iso=_now_iso,
    )


def _webrtc_sidecar_runtime_health(sidecar: dict[str, Any]) -> str:
    """Return live sidecar health used for offer selection."""
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
    """Return whether the requested MediaMTX path is actually online.

    The root WebRTC HTTP listener can be healthy while a specific camera path is
    missing/offline. Main should only prefer WebRTC for paths that MediaMTX
    reports as ready/available/online/sourceReady; otherwise MJPEG remains the
    safe fallback.  MediaMTX versions do not all expose the same readiness
    field, so this intentionally mirrors the runtime startup check and accepts
    any explicit truthy path-readiness marker rather than requiring every
    possible marker at once.
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


@dataclass(frozen=True)
class _WhepProxyResult:
    ok: bool
    reason: str
    status_code: int | None = None
    sdp: str | None = None
    session_url: str | None = None
    error: str | None = None


def _whep_response_header(response: Any, name: str) -> str | None:
    headers = getattr(response, "headers", None)
    if headers is not None:
        value = headers.get(name)
        if not value:
            value = headers.get(name.lower())
        if value:
            return str(value)
    getheader = getattr(response, "getheader", None)
    if callable(getheader):
        value = getheader(name)
        if value:
            return str(value)
    return None


def _proxy_webrtc_offer_to_whep(
    *,
    sidecar: dict[str, Any],
    sdp: str,
    timeout_s: float,
) -> _WhepProxyResult:
    """Proxy a browser SDP offer to a MediaMTX WHEP endpoint.

    MediaMTX's own reader performs `POST /path/whep` with
    `Content-Type: application/sdp`, expects a 201 response containing the SDP
    answer body, and exposes the WHEP session URL in the `Location` header.
    """

    whep_url = str(sidecar.get("whep_url") or "").strip()
    if not whep_url:
        return _WhepProxyResult(ok=False, reason="whep_url_missing")
    if not sdp.strip():
        return _WhepProxyResult(ok=False, reason="whep_offer_sdp_missing")
    request = UrlRequest(
        whep_url,
        data=sdp.encode("utf-8"),
        headers={
            "Accept": "application/sdp",
            "Content-Type": "application/sdp",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            status_code = int(getattr(response, "status", 200))
            answer_sdp = response.read().decode("utf-8", errors="replace")
            content_type = (_whep_response_header(response, "Content-Type") or "").lower()
            if status_code != 201:
                return _WhepProxyResult(
                    ok=False,
                    reason=f"whep_proxy_unexpected_status_{status_code}",
                    status_code=status_code,
                    error=answer_sdp[:500] or None,
                )
            if content_type and "application/sdp" not in content_type:
                return _WhepProxyResult(
                    ok=False,
                    reason="whep_proxy_unexpected_content_type",
                    status_code=status_code,
                    error=content_type[:200],
                )
            if not answer_sdp.strip():
                return _WhepProxyResult(
                    ok=False,
                    reason="whep_proxy_empty_answer",
                    status_code=status_code,
                )
            if not answer_sdp.lstrip().startswith("v=0"):
                return _WhepProxyResult(
                    ok=False,
                    reason="whep_proxy_invalid_answer",
                    status_code=status_code,
                    error=answer_sdp[:500],
                )
            return _WhepProxyResult(
                ok=True,
                reason="whep_answer_created",
                status_code=status_code,
                sdp=answer_sdp,
                session_url=_whep_response_header(response, "Location"),
            )
    except HTTPError as exc:
        error_body = ""
        try:
            error_body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            error_body = ""
        return _WhepProxyResult(
            ok=False,
            reason=f"whep_proxy_http_{exc.code}",
            status_code=exc.code,
            error=error_body[:500] or str(exc),
        )
    except (OSError, TimeoutError, URLError) as exc:
        return _WhepProxyResult(
            ok=False,
            reason="whep_proxy_unavailable",
            error=str(exc),
        )


def vision_webrtc_offer(
    source: str,
    payload: WebRtcOfferRequest | None = None,
    view: str = Query(default=DEFAULT_VIEW_ID),
    force_fallback: bool = Query(default=False),
) -> dict[str, Any]:
    """Return a media-only WebRTC candidate or MJPEG fallback descriptor.

    This is intentionally not a robot-control bridge. A future sidecar may own
    actual SDP/WHEP negotiation, while this endpoint keeps the Main-facing
    source/view contract and records transport health/fallback metrics.
    """
    view_id = _ensure_known_source_view(source, view)
    request_payload = payload or WebRtcOfferRequest()
    forced = bool(force_fallback or request_payload.force_fallback)
    sidecar = webrtc_sidecar_descriptor(source, view_id)
    runtime_health = _webrtc_sidecar_runtime_health(sidecar)
    sidecar["runtime_health"] = runtime_health
    path_runtime_health = _webrtc_sidecar_path_runtime_health(sidecar)
    sidecar["path_runtime_health"] = path_runtime_health
    compositor_runtime_health = _webrtc_compositor_runtime_health(sidecar)
    sidecar["compositor_runtime_health"] = compositor_runtime_health
    settings = get_settings()
    runtime_ok = runtime_health in {"healthy", "assume_healthy"}
    path_ok = path_runtime_health == "online"
    compositor_ok = compositor_runtime_health in {"alive", "not_required"}
    if not settings.vision_webrtc_enabled:
        status = "fallback_required"
        reason = "webrtc_disabled"
        selected_transport = "mjpeg"
    elif forced:
        status = "fallback_required"
        reason = "forced_fallback"
        selected_transport = "mjpeg"
    elif sidecar["status"] == "configured" and runtime_ok and path_ok and compositor_ok:
        status = "sidecar_configured"
        if compositor_runtime_health == "alive":
            reason = "sidecar_path_online_compositor_alive"
        elif path_runtime_health == "online":
            reason = "sidecar_path_online"
        else:
            reason = (
                "sidecar_runtime_healthy"
                if runtime_health == "healthy"
                else "sidecar_assume_healthy"
            )
        selected_transport = "webrtc"
    elif sidecar["status"] == "configured" and not runtime_ok:
        status = "fallback_required"
        reason = f"sidecar_health_{runtime_health}"
        selected_transport = "mjpeg"
    elif sidecar["status"] == "configured":
        status = "fallback_required"
        if path_ok and not compositor_ok:
            reason = f"sidecar_compositor_{compositor_runtime_health}"
        else:
            reason = f"sidecar_path_{path_runtime_health}"
        selected_transport = "mjpeg"
    else:
        status = "fallback_required"
        reason = "sidecar_not_configured"
        selected_transport = "mjpeg"

    whep_result: _WhepProxyResult | None = None
    if selected_transport == "webrtc" and request_payload.sdp:
        whep_result = _proxy_webrtc_offer_to_whep(
            sidecar=sidecar,
            sdp=request_payload.sdp,
            timeout_s=settings.vision_webrtc_sidecar_health_timeout_s,
        )
        if whep_result.ok:
            sidecar["proxy_mode"] = "whep_proxy"
            if whep_result.session_url:
                sidecar["whep_session_url"] = whep_result.session_url
        else:
            status = "fallback_required"
            reason = whep_result.reason
            selected_transport = "mjpeg"
            sidecar["proxy_mode"] = "whep_proxy_failed"
            sidecar["whep_proxy_status_code"] = whep_result.status_code

    context = _runtime_context()
    context.metrics.record_webrtc_offer(source=source, status=status, reason=reason)
    context.metrics.record_webrtc_selected_transport(
        source=source,
        transport=selected_transport,
    )
    if selected_transport == "mjpeg":
        context.metrics.record_webrtc_fallback(source=source, reason=reason)

    fallback_path = overlay_stream_path(source, view_id)
    response = {
        "source": source,
        "view": view_id,
        "transport": "webrtc",
        "status": status,
        "reason": reason,
        "selected_transport": selected_transport,
        "media_only": True,
        "signaling_scope": "ephemeral_media_session_only",
        "offer": {
            "type": request_payload.type,
            "sdp_received": bool(request_payload.sdp),
        },
        "sidecar": sidecar,
        "fallback": {
            "kind": "mjpeg",
            "path": fallback_path,
            "url": vision_gateway_url(fallback_path),
        },
        "stream_discovery_path": f"/api/v1/vision/streams?source={source}",
        "motion_command_allowed": False,
        "control_topics_published": [],
        "side_effects": {
            "db_writes": False,
            "evidence_truth_mutated": False,
            "ros_control_published": False,
            "ros_topics_started_by_http_request": False,
        },
    }
    if whep_result is not None:
        response["whep_proxy"] = {
            "ok": whep_result.ok,
            "reason": whep_result.reason,
            "status_code": whep_result.status_code,
        }
        if whep_result.ok:
            response.update(
                {
                    "type": "answer",
                    "sdp": whep_result.sdp,
                }
            )
            if whep_result.session_url:
                response["whep_proxy"]["session_url"] = whep_result.session_url
    structured_log(
        context.logger,
        "vision_webrtc_offer",
        source=source,
        view=view_id,
        status=status,
        reason=reason,
        selected_transport=selected_transport,
    )
    return response


def vision_webrtc_demo(
    source: str = Query(default="global_cam_01", json_schema_extra=SOURCE_ID_OPENAPI_EXTRA),
    view: str = Query(default=DEFAULT_VIEW_ID),
    force_fallback: bool = Query(default=False),
) -> HTMLResponse:
    """Standalone browser smoke page: prefer burned-overlay WebRTC, fall back to MJPEG."""
    view_id = _ensure_known_source_view(source, view)
    offer_path = webrtc_offer_path(source, view_id)
    fallback_path = overlay_stream_path(source, view_id)
    metadata_path = overlay_metadata_path(source, view_id)
    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>SmartFactory Vision burned-overlay WebRTC</title>
  <style>
    body {{ font-family: system-ui, sans-serif; margin: 24px; }}
    code, pre {{ background: #f5f5f5; padding: 2px 4px; }}
    img, iframe, video {{ max-width: 100%; border: 1px solid #ddd; }}
    iframe {{ width: min(100%, 1280px); height: 720px; }}
    .media-wrap {{ position: relative; width: min(100%, 1280px); }}
    #webrtcVideo {{ width: 100%; height: auto; display: block; }}
    #overlayCanvas {{
      position: absolute;
      inset: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
      border: 1px solid transparent;
    }}
  </style>
</head>
<body>
  <h1>Vision transport smoke test</h1>
  <p>source=<code id="source"></code>, view=<code id="view"></code></p>
  <p>selected transport: <strong id="selected">checking</strong></p>
  <p>Public WebRTC streams already contain burned-in AI overlay pixels. Canvas metadata is diagnostic-only and is not required for Main streaming.</p>
  <iframe id="sidecarFrame" title="WebRTC sidecar browser player" allow="autoplay; fullscreen" hidden></iframe>
  <p id="sidecarLinkRow" hidden>Sidecar browser URL: <a id="sidecarLink" target="_blank" rel="noreferrer"></a></p>
  <div class="media-wrap" id="webrtcWrap" hidden>
    <video id="webrtcVideo" autoplay playsinline muted controls></video>
    <canvas id="overlayCanvas"></canvas>
  </div>
  <img id="mjpegFallback" alt="MJPEG fallback overlay" hidden>
  <pre id="status"></pre>
  <script>
    const source = {json.dumps(source)};
    const view = {json.dumps(view_id)};
    const forceFallback = {json.dumps(force_fallback)};
    const offerPath = {json.dumps(offer_path)};
    const fallbackPath = {json.dumps(fallback_path)};
    const metadataPath = {json.dumps(metadata_path)};
    const debugCanvasMetadata = false;
    document.getElementById('source').textContent = source;
    document.getElementById('view').textContent = view;
    const selected = document.getElementById('selected');
    const status = document.getElementById('status');
    const img = document.getElementById('mjpegFallback');
    const webrtcWrap = document.getElementById('webrtcWrap');
    const video = document.getElementById('webrtcVideo');
    const overlayCanvas = document.getElementById('overlayCanvas');
    const overlayCtx = overlayCanvas.getContext('2d');
    const sidecarFrame = document.getElementById('sidecarFrame');
    const sidecarLinkRow = document.getElementById('sidecarLinkRow');
    const sidecarLink = document.getElementById('sidecarLink');
    let overlayTimer = null;
    let overlayRefreshFps = {json.dumps(float(get_settings().vision_webrtc_overlay_refresh_fps))};
    let metadataFailures = 0;

    function useMjpeg(reason) {{
      selected.textContent = 'mjpeg';
      img.src = fallbackPath;
      img.hidden = false;
      webrtcWrap.hidden = true;
      sidecarFrame.hidden = true;
      sidecarLinkRow.hidden = true;
      if (overlayTimer) {{
        clearInterval(overlayTimer);
        overlayTimer = null;
      }}
      status.textContent = 'MJPEG fallback: ' + reason + '\\n' + fallbackPath;
    }}

    function resizeCanvas(imageWidth, imageHeight) {{
      const width = video.videoWidth || imageWidth || 1920;
      const height = video.videoHeight || imageHeight || 1080;
      if (overlayCanvas.width !== width) overlayCanvas.width = width;
      if (overlayCanvas.height !== height) overlayCanvas.height = height;
    }}

    function drawOverlay(payload) {{
      const image = payload.overlay && payload.overlay.image ? payload.overlay.image : {{}};
      resizeCanvas(image.width, image.height);
      overlayCtx.clearRect(0, 0, overlayCanvas.width, overlayCanvas.height);
      const events = Array.isArray(payload.events) ? payload.events : [];
      overlayCtx.lineWidth = Math.max(2, overlayCanvas.width / 640);
      overlayCtx.font = `${{Math.max(14, overlayCanvas.width / 80)}}px system-ui, sans-serif`;
      overlayCtx.textBaseline = 'top';
      for (const event of events) {{
        const box = event.bbox_xyxy || [];
        if (box.length !== 4) continue;
        const [x1, y1, x2, y2] = box.map(Number);
        const label = `${{event.class_name || 'object'}} ${{event.confidence == null ? '' : Number(event.confidence).toFixed(2)}}`;
        overlayCtx.strokeStyle = event.class_name === 'person' ? '#ff3b30' : '#00e676';
        overlayCtx.fillStyle = overlayCtx.strokeStyle;
        overlayCtx.strokeRect(x1, y1, Math.max(1, x2 - x1), Math.max(1, y2 - y1));
        const labelY = Math.max(0, y1 - 24);
        const textWidth = overlayCtx.measureText(label).width + 10;
        overlayCtx.globalAlpha = 0.78;
        overlayCtx.fillRect(x1, labelY, textWidth, 22);
        overlayCtx.globalAlpha = 1;
        overlayCtx.fillStyle = '#111';
        overlayCtx.fillText(label, x1 + 5, labelY + 3);
      }}
    }}

    async function refreshOverlay() {{
      try {{
        const response = await fetch(metadataPath, {{ cache: 'no-store' }});
        if (!response.ok) {{
          metadataFailures += 1;
          status.textContent =
            `WebRTC burned-overlay video is playing; diagnostic metadata is not ready\\n` +
            `metadata: ${{metadataPath}}\\n` +
            `metadata_http_status: ${{response.status}}, consecutive_failures: ${{metadataFailures}}`;
          return;
        }}
        const payload = await response.json();
        metadataFailures = 0;
        drawOverlay(payload);
        const plane = payload.metadata_plane || {{}};
        const nextFps = Number(plane.refresh_fps || overlayRefreshFps || 5);
        if (Number.isFinite(nextFps) && Math.abs(nextFps - overlayRefreshFps) > 0.1) {{
          overlayRefreshFps = nextFps;
          startOverlayLoop(overlayRefreshFps);
          return;
        }}
        const count = Array.isArray(payload.events) ? payload.events.length : 0;
        status.textContent =
          `WebRTC burned-overlay video; diagnostic canvas metadata available\\n` +
          `metadata: ${{metadataPath}}\\n` +
          `refresh_fps: ${{plane.refresh_fps || 'n/a'}}, events: ${{count}}\\n` +
          `sync: ${{JSON.stringify(payload.sync || {{}})}}`;
      }} catch (error) {{
        metadataFailures += 1;
        status.textContent =
          `WebRTC burned-overlay video is playing; diagnostic metadata polling failed\\n` +
          `metadata: ${{metadataPath}}\\n` +
          `error: ${{error.message}}, consecutive_failures: ${{metadataFailures}}`;
      }}
    }}

    function startOverlayLoop(refreshFps) {{
      if (overlayTimer) clearInterval(overlayTimer);
      const fps = Math.max(1, Math.min(Number(refreshFps || 5), 10));
      overlayRefreshFps = fps;
      refreshOverlay();
      overlayTimer = setInterval(refreshOverlay, Math.round(1000 / fps));
    }}

    async function chooseTransport() {{
      if (!('RTCPeerConnection' in window)) {{
        useMjpeg('RTCPeerConnection unavailable');
        return;
      }}
      try {{
        const pc = new RTCPeerConnection();
        pc.ontrack = (event) => {{
          video.srcObject = event.streams[0];
        }};
        pc.addTransceiver('video', {{ direction: 'recvonly' }});
        const offer = await pc.createOffer();
        await pc.setLocalDescription(offer);
        const response = await fetch(offerPath, {{
          method: 'POST',
          headers: {{ 'Content-Type': 'application/json' }},
          body: JSON.stringify({{
            type: offer.type,
            sdp: offer.sdp,
            force_fallback: forceFallback
          }})
        }});
        const descriptor = await response.json();
        status.textContent = JSON.stringify(descriptor, null, 2);
        if (response.ok && descriptor.selected_transport === 'webrtc') {{
          if (descriptor.type === 'answer' && descriptor.sdp) {{
            await pc.setRemoteDescription({{ type: descriptor.type, sdp: descriptor.sdp }});
            selected.textContent = 'webrtc-burned-overlay';
            webrtcWrap.hidden = false;
            sidecarFrame.hidden = true;
            sidecarLinkRow.hidden = true;
            img.hidden = true;
            if (debugCanvasMetadata) {{
              startOverlayLoop(overlayRefreshFps);
            }} else {{
              overlayCanvas.hidden = true;
              status.textContent = 'WebRTC burned-overlay video playing\\n' +
                'diagnostic metadata: ' + metadataPath;
            }}
            return;
          }}
          const browserUrl = descriptor.sidecar && descriptor.sidecar.browser_url;
          if (browserUrl) {{
            selected.textContent = 'webrtc-sidecar-burned-overlay';
            sidecarFrame.src = browserUrl;
            sidecarFrame.hidden = false;
            sidecarLink.href = browserUrl;
            sidecarLink.textContent = browserUrl;
            sidecarLinkRow.hidden = false;
            webrtcWrap.hidden = true;
            img.hidden = true;
            return;
          }}
          useMjpeg('WebRTC selected but no sidecar.browser_url was provided');
          return;
        }}
        useMjpeg(descriptor.reason || 'offer rejected');
      }} catch (error) {{
        useMjpeg(error.message);
      }}
    }}

    chooseTransport();
  </script>
</body>
</html>
"""
    return HTMLResponse(content=html)


def vision_ros_topics(
    source: str | None = Query(default=None, json_schema_extra=SOURCE_ID_OPENAPI_EXTRA),
) -> dict[str, Any]:
    """Return the read-only ROS2 topic handoff matrix for Lane B/C planning.

    This endpoint does not start ROS2, does not publish overlays, and does not
    expose motion control. It exists so GUI/Main/ROS developers can align on the
    source-to-topic contract before Lane C ROS ingest/domain bridge work.
    """
    if source is not None:
        _ensure_known_source(source)
    return build_vision_ros_topics_payload(
        source=source,
        runtime_context=_runtime_context(),
        latest_overlay_image=_latest_overlay_image,
        frame_age_s=_frame_age_s,
        now_iso=_now_iso,
    )


def _worker_tick_sources(requested_source: str | None) -> list[str]:
    settings = get_settings()
    if requested_source is not None:
        _ensure_known_source(requested_source)
        return [requested_source]
    return list(settings.source_ids)


def _worker_tick_result_for_source(
    *, source: str, force: bool, stale: bool, max_frame_age_s: float
) -> dict[str, Any]:
    frame = _runtime_context().frame_store.latest(source)
    if frame is None:
        _runtime_context().metrics.record_worker_tick(source=source, status="no_frame")
        return {
            "source": source,
            "status": "no_frame",
            "frame_seq": None,
            "event_count": 0,
            "new_event_count": 0,
            "evidence_action": "none",
            "overlay": None,
            "reason": "no latest frame available",
        }
    frame_age_s = round(_frame_age_s(frame), 3)
    if not force and frame_age_s > max_frame_age_s:
        _runtime_context().metrics.record_worker_tick(source=source, status="stale_frame")
        return {
            "source": source,
            "status": "stale_frame",
            "frame_seq": frame.frame_seq,
            "frame_age_s": frame_age_s,
            "max_frame_age_s": max_frame_age_s,
            "event_count": 0,
            "new_event_count": 0,
            "evidence_action": "none",
            "overlay": None,
            "reason": "latest frame is older than max_frame_age_s",
        }
    latest_overlay_metadata = _runtime_context().overlay_cache.latest(source)
    overlay_frame_seq = (
        latest_overlay_metadata.get("frame_seq")
        if isinstance(latest_overlay_metadata, dict)
        else None
    )
    if not force and isinstance(overlay_frame_seq, int) and (overlay_frame_seq >= frame.frame_seq):
        _runtime_context().metrics.record_worker_tick(source=source, status="skipped")
        return {
            "source": source,
            "status": "skipped",
            "frame_seq": frame.frame_seq,
            "frame_age_s": frame_age_s,
            "max_frame_age_s": max_frame_age_s,
            "event_count": int(latest_overlay_metadata.get("event_count", 0)),
            "new_event_count": 0,
            "evidence_action": "reused",
            "overlay": latest_overlay_metadata,
            "reason": "latest overlay already matches latest frame",
        }
    processed = _detect_and_overlay_frame_snapshot(frame=frame, stale=stale)
    overlay: OverlayRenderResult = processed["overlay"]
    new_event_count = len(processed["events"])
    _runtime_context().metrics.record_worker_tick(source=source, status="processed")
    return {
        "source": source,
        "status": "processed",
        "frame_seq": frame.frame_seq,
        "frame_age_s": frame_age_s,
        "max_frame_age_s": max_frame_age_s,
        "event_count": new_event_count,
        "new_event_count": new_event_count,
        "evidence_action": "created",
        "overlay": overlay.metadata(),
        "reason": "forced" if force else "new frame processed",
    }


def _worker_result_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = {"no_frame": 0, "processed": 0, "skipped": 0, "stale_frame": 0}
    event_count_total = 0
    new_event_count_total = 0
    reused_event_count_total = 0
    for item in items:
        status = str(item.get("status") or "")
        if status in status_counts:
            status_counts[status] += 1
        event_count = int(item.get("event_count") or 0)
        new_event_count = int(item.get("new_event_count") or 0)
        event_count_total += event_count
        new_event_count_total += new_event_count
        if item.get("evidence_action") == "reused":
            reused_event_count_total += event_count
    return {
        "sources_total": len(items),
        "processed_count": status_counts["processed"],
        "skipped_count": status_counts["skipped"],
        "stale_frame_count": status_counts["stale_frame"],
        "event_count_total": event_count_total,
        "new_event_count_total": new_event_count_total,
        "reused_event_count_total": reused_event_count_total,
        "status_counts": status_counts,
    }


def vision_worker_status(
    source: str | None = Query(default=None, json_schema_extra=SOURCE_ID_OPENAPI_EXTRA),
    max_frame_age_s: float | None = Query(default=None, ge=0),
) -> dict[str, Any]:
    """Return what the next worker tick would do without processing frames."""
    if source is not None:
        _ensure_known_source(source)
    return build_vision_worker_status_payload(
        source=source,
        max_frame_age_s=max_frame_age_s,
        runtime_context=_runtime_context(),
        frame_age_s=_frame_age_s,
        now_iso=_now_iso,
    )


def vision_worker_tick(payload: VisionWorkerTickRequest) -> dict[str, Any]:
    """Run one controlled latest-frame processing tick for Lane B validation.

    This is a robot-free debug/control surface for the future evidence worker.
    It processes only explicit configured sources and never publishes ROS motion
    commands. Main-facing production browser video uses the source-selected
    HTTP/MJPEG Vision Stream Gateway on :8090; rosbridge is internal allowlisted
    operator/prototype infrastructure only.
    """
    sources = _worker_tick_sources(payload.source)
    settings = get_settings()
    max_frame_age_s = (
        payload.max_frame_age_s
        if payload.max_frame_age_s is not None
        else settings.source_stale_after_s
    )
    results = [
        _worker_tick_result_for_source(
            source=source, force=payload.force, stale=payload.stale, max_frame_age_s=max_frame_age_s
        )
        for source in sources
    ]
    return {
        "generated_at": _now_iso(),
        "requested_source": payload.source,
        "force": payload.force,
        "stale": payload.stale,
        "max_frame_age_s": max_frame_age_s,
        "summary": _worker_result_summary(results),
        "results": results,
    }


def vision_debug_sources(
    source: str | None = Query(default=None, json_schema_extra=SOURCE_ID_OPENAPI_EXTRA),
) -> dict[str, Any]:
    """Return one-shot source/frame/overlay readiness snapshots for Lane B debug use."""
    if source is not None:
        _ensure_known_source(source)
    return build_vision_debug_sources_payload(
        source=source,
        runtime_context=_runtime_context(),
        latest_overlay_image=_latest_overlay_image,
        frame_age_s=_frame_age_s,
        now_iso=_now_iso,
        now_dt=_now_dt,
    )


async def ingest_frame(
    source: str = Form(..., json_schema_extra=SOURCE_ID_OPENAPI_EXTRA),
    image: UploadFile = File(...),
) -> dict[str, Any]:
    """Store one raw frame in the latest-frame cache without detection.

    This is a Lane B robot-free seam for future ROS2/camera ingest. It lets
    callers push a frame, inspect it with `/vision/frame/latest`, and then run
    `/vision/worker/tick` to process it. It is not the production browser stream
    plane and it does not publish ROS motion commands.
    """
    return await build_frame_ingest_response(
        source=source,
        image=image,
        store_latest_frame_from_bytes=_store_latest_frame_from_bytes,
        frame_ingest_context=_frame_ingest_context,
    )


async def ingest_and_process_frame(
    source: str = Form(..., json_schema_extra=SOURCE_ID_OPENAPI_EXTRA),
    image: UploadFile = File(...),
    force: bool = Form(default=True),
    stale: bool = Form(default=False),
) -> dict[str, Any]:
    """Store one raw frame and immediately render AI/detection overlay.

    This ROS-free endpoint is optimized for the D1 gateway hot path: one HTTP
    request updates the latest-frame cache and overlay cache, avoiding the older
    frame POST -> worker tick race. It still publishes no ROS/control topics.
    """
    return await build_frame_process_response(
        source=source,
        image=image,
        force=force,
        stale=stale,
        runtime_context=_runtime_context(),
        store_latest_frame_from_bytes=_store_latest_frame_from_bytes,
        detect_and_overlay_frame_snapshot=_detect_and_overlay_frame_snapshot,
        frame_ingest_context=_frame_ingest_context,
    )


def latest_frame(
    source: str = Query(..., json_schema_extra=SOURCE_ID_OPENAPI_EXTRA),
) -> dict[str, Any]:
    """Return latest raw frame metadata for one source.

    This is a Lane B debug/fallback endpoint for visual QA. It exposes only the
    newest cached frame and does not queue historical frames.
    """
    _ensure_known_source(source)
    return build_latest_frame_response(
        source=source,
        runtime_context=_runtime_context(),
        now_iso=_now_iso,
    )


def latest_frame_image(
    source: str = Query(..., json_schema_extra=SOURCE_ID_OPENAPI_EXTRA),
) -> Response:
    """Return latest raw frame image for one source.

    This is a debug/fallback image endpoint for comparing raw frame evidence
    against rendered overlays. Main-facing production browser streaming uses the
    burned-overlay WebRTC primary plane with the source-selected HTTP/MJPEG
    Vision Stream Gateway on :8090 as fallback; rosbridge is internal
    allowlisted operator/prototype infrastructure only.
    """
    _ensure_known_source(source)
    return build_latest_frame_image_response(
        source=source,
        runtime_context=_runtime_context(),
    )


def latest_overlay(
    source: str = Query(..., json_schema_extra=SOURCE_ID_OPENAPI_EXTRA),
    view: str = Query(default=DEFAULT_VIEW_ID),
) -> dict[str, Any]:
    """Return latest visual evidence overlay metadata for one source."""
    view_id = _ensure_known_source_view(source, view)
    context = _runtime_context()
    overlay, _ = _latest_overlay_metadata_snapshot(
        source,
        view=view_id,
        runtime_context=context,
    )
    return {
        "generated_at": _now_iso(),
        "requested_source": source,
        "requested_view": view_id,
        "sync": _overlay_sync_status_for_snapshot(
            source,
            overlay=overlay,
            runtime_context=context,
        ),
        "overlay": overlay,
    }


def latest_overlay_metadata(
    source: str = Query(..., json_schema_extra=SOURCE_ID_OPENAPI_EXTRA),
    view: str = Query(default=DEFAULT_VIEW_ID),
    limit: int = Query(default=20, ge=1, le=50),
) -> dict[str, Any]:
    """Return diagnostic client-renderable AI overlay metadata.

    Public Main-facing WebRTC streams carry burned-in overlay pixels.  This
    endpoint remains available for debugging canvas math and event/frame sync;
    it does not return image bytes and has no control or DB side effects.
    """
    view_id = _ensure_known_source_view(source, view)
    context = _runtime_context()
    overlay, cached_overlay_events = _latest_overlay_metadata_snapshot(
        source,
        view=view_id,
        runtime_context=context,
    )
    response = {
        "generated_at": _now_iso(),
        "requested_source": source,
        "requested_view": view_id,
        "sync": _overlay_sync_status_for_snapshot(
            source,
            overlay=overlay,
            runtime_context=context,
        ),
        "overlay": overlay,
    }
    overlay_frame_seq = overlay.get("frame_seq")
    overlay_image = overlay.get("image", {})
    overlay_width = overlay_image.get("width") if isinstance(overlay_image, dict) else None
    overlay_height = overlay_image.get("height") if isinstance(overlay_image, dict) else None
    candidate_events = context.store.latest(source=source, limit=context.store.maxlen)
    if cached_overlay_events is not None:
        events = cached_overlay_events[:limit]
    else:
        # Compatibility fallback for overlays produced before the event-layer
        # cache existed.  This intentionally returns only persisted detection
        # events; debug-only ROI layers must not be reconstructed from lossy
        # event-store dictionaries because MapROI needs marker-corner geometry.
        events = [
            event
            for event in candidate_events
            if isinstance(event.get("metadata"), dict)
            and event["metadata"].get("frame_seq") == overlay_frame_seq
            and (
                view_id == DEFAULT_VIEW_ID
                or (
                    event.get("roi_id") == view_id
                    and event["metadata"].get("image_width") == overlay_width
                    and event["metadata"].get("image_height") == overlay_height
                )
            )
        ][:limit]
    return {
        **response,
        "metadata_plane": {
            "kind": "vision_event_canvas_layer_diagnostic",
            "render_target": "diagnostic_canvas_only_public_stream_is_burned_overlay",
            "refresh_fps": get_settings().vision_webrtc_overlay_refresh_fps,
            "client_rendering": "diagnostic_only_not_required_for_main_streaming",
            "recommended_for_main_streaming": False,
            "motion_command_allowed": False,
            "db_writes": False,
            "evidence_truth_mutation": False,
        },
        "events": events,
    }


def latest_overlay_image(
    source: str = Query(..., json_schema_extra=SOURCE_ID_OPENAPI_EXTRA),
    view: str = Query(default=DEFAULT_VIEW_ID),
) -> Response:
    """Return latest overlay image for one source as JPEG."""
    view_id = _ensure_known_source_view(source, view)
    return build_latest_overlay_image_response(
        source=source,
        view=view_id,
        latest_overlay_image=_latest_overlay_image,
    )


async def _mjpeg_latest_overlay_generator(
    source: str,
    *,
    view: str = DEFAULT_VIEW_ID,
    max_fps: int,
    runtime_context: RuntimeContext | None = None,
):
    return_generator = mjpeg_latest_overlay_generator(
        source,
        view=view,
        max_fps=max_fps,
        runtime_context=runtime_context or _runtime_context(),
        latest_overlay_image=_latest_overlay_image,
    )
    async for chunk in return_generator:
        yield chunk


def debug_overlay_mjpeg_stream(
    source: str,
    view: str = Query(default=DEFAULT_VIEW_ID),
    max_fps: int = Query(default=10, ge=1, le=30),
) -> StreamingResponse:
    """Debug/fallback MJPEG stream of latest overlays.

    This stream feeds the MJPEG fallback/diagnostic gateway. Main-facing public
    WebRTC carries burned-in overlay pixels when the compositor path is healthy;
    ROS/rosbridge remains internal allowlisted operator/prototype infrastructure.
    """
    view_id = _ensure_known_source_view(source, view)
    context = _runtime_context()
    return build_debug_overlay_mjpeg_stream_response(
        source=source,
        view=view_id,
        max_fps=max_fps,
        runtime_context=context,
        latest_overlay_image=_latest_overlay_image,
    )


def metrics_snapshot(
    source: str | None = Query(default=None, json_schema_extra=SOURCE_ID_OPENAPI_EXTRA),
) -> dict[str, Any]:
    if source is not None:
        _ensure_known_source(source)
    return build_metrics_snapshot_payload(
        source=source,
        runtime_context=_runtime_context(),
        now_iso=_now_iso,
    )


def vision_monitor_states() -> dict[str, Any]:
    states = [state.as_dict() for state in _runtime_context().monitor_states.list()]
    return {
        "schema_version": "vision-monitor-state-list.v1",
        "monitors": states,
    }


def vision_monitor_state(
    monitor_id: str,
    robot_id: str | None = Query(default=None),
    source: str | None = Query(default=None, json_schema_extra=SOURCE_ID_OPENAPI_EXTRA),
) -> dict[str, Any]:
    try:
        state = _runtime_context().monitor_states.get(
            monitor_id,
            robot_id=robot_id,
            source=source,
            source_registry=get_settings().source_registry,
        )
    except VisionMonitorStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "schema_version": "vision-monitor-state.v1",
        "monitor": state.as_dict(),
    }


def update_vision_monitor_state(
    monitor_id: str,
    payload: VisionMonitorStateRequest,
) -> dict[str, Any]:
    try:
        state = _runtime_context().monitor_states.update(
            monitor_id,
            payload.model_dump(),
            source_registry=get_settings().source_registry,
            updated_at=_now_iso(),
        )
    except VisionMonitorStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "schema_version": "vision-monitor-state.v1",
        "monitor": state.as_dict(),
    }


def _source_for_robot_id(robot_id: str) -> str:
    source_by_robot = {
        "tb3_1": "tb3_1_picam",
        "tb3_2": "tb3_2_picam",
    }
    try:
        return source_by_robot[robot_id]
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=f"unknown robot_id: {robot_id}") from exc


def _person_confidence(raw_event: dict[str, Any]) -> float | None:
    for key in ("confidence", "score", "conf"):
        value = raw_event.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return max(0.0, min(1.0, float(value)))
    return None


def _is_person_event(raw_event: dict[str, Any]) -> bool:
    return str(raw_event.get("class_name") or raw_event.get("label") or "").lower() == "person"


def _person_hazard_monitor_event(
    *,
    source: str,
    robot_id: str,
    task_id: int | str | None,
    raw_event: dict[str, Any],
) -> dict[str, Any]:
    source_event_id = raw_event.get("event_id")
    confidence = _person_confidence(raw_event)
    observed_at = str(raw_event.get("timestamp") or raw_event.get("observed_at") or _now_iso())
    payload = {
        "schema_version": "vision-monitor-event.v1",
        "event_id": str(uuid4()),
        "event_type": "HUMAN_DETECTED",
        "source": source,
        "robot_id": robot_id,
        "task_id": task_id,
        "command_id": None,
        "result": "ADVISORY",
        "severity": "CRITICAL",
        "confidence": confidence,
        "reason_code": "HUMAN_DETECTED",
        "trusted": False,
        "observed_at": observed_at,
        "image_url": None,
        "policy_version": VISION_MONITOR_POLICY_VERSION,
        "profile_id": PERSON_DRIVE_PROFILE_ID,
        "threshold_set_id": PERSON_DRIVE_THRESHOLD_SET_ID,
        "data_json": {
            "result": "ADVISORY",
            "reason_code": "HUMAN_DETECTED",
            "policy_version": VISION_MONITOR_POLICY_VERSION,
            "profile_id": PERSON_DRIVE_PROFILE_ID,
            "threshold_set_id": PERSON_DRIVE_THRESHOLD_SET_ID,
            "assignment_status": "OWNED",
            "related_robot_ids": [],
            "task_id_ref": task_id,
            "source_event_id": source_event_id,
        },
    }
    validate_vision_monitor_event(payload)
    return payload


def person_hazard_latest(
    robot_id: str | None = Query(default=None),
    source: str | None = Query(default=None, json_schema_extra=SOURCE_ID_OPENAPI_EXTRA),
    limit: int = Query(default=20, ge=1, le=200),
) -> dict[str, Any]:
    if robot_id is not None:
        expected_source = _source_for_robot_id(robot_id)
        if source is not None and source != expected_source:
            raise HTTPException(
                status_code=400,
                detail=f"robot_id {robot_id} requires source {expected_source}",
            )
        source = expected_source
    if source is None:
        source = (
            _runtime_context()
            .monitor_states.get(
                "person_drive",
                robot_id=robot_id,
                source_registry=get_settings().source_registry,
            )
            .source
        )
    if source is None:
        return {
            "schema_version": "vision-person-hazard-latest.v1",
            "monitor_id": "person_drive",
            "source": None,
            "robot_id": robot_id,
            "result": "NO_ACTIVE_MONITOR",
            "reason_code": "NO_ACTIVE_MONITOR",
            "event": None,
        }
    _ensure_known_source(source)
    resolved_robot_id = robot_id or _robot_id_for_source(source)
    state = _runtime_context().monitor_states.get(
        "person_drive",
        robot_id=resolved_robot_id,
        source=source,
        source_registry=get_settings().source_registry,
    )
    active = (
        state.enabled
        and state.operation_state == "DRIVE"
        and state.source == source
        and resolved_robot_id is not None
        and state.robot_id == resolved_robot_id
    )
    if not active:
        return {
            "schema_version": "vision-person-hazard-latest.v1",
            "monitor_id": "person_drive",
            "source": source,
            "robot_id": resolved_robot_id,
            "result": "NO_ACTIVE_MONITOR",
            "reason_code": "NO_ACTIVE_MONITOR",
            "event": None,
        }

    for raw_event in _runtime_context().store.latest(source=source, limit=limit):
        if not _is_person_event(raw_event):
            continue
        event = _person_hazard_monitor_event(
            source=source,
            robot_id=resolved_robot_id,
            task_id=state.task_id,
            raw_event=raw_event,
        )
        return {
            "schema_version": "vision-person-hazard-latest.v1",
            "monitor_id": "person_drive",
            "source": source,
            "robot_id": resolved_robot_id,
            "result": event["result"],
            "reason_code": event["reason_code"],
            "event": event,
        }

    return {
        "schema_version": "vision-person-hazard-latest.v1",
        "monitor_id": "person_drive",
        "source": source,
        "robot_id": resolved_robot_id,
        "result": "NO_RELEVANT_DETECTION",
        "reason_code": "NO_RELEVANT_DETECTION",
        "event": None,
    }


DEFAULT_ARUCO_ITEM_MARKER_IDS = (
    "ARUCO_4X4_50_20",
    "ARUCO_4X4_50_22",
    "ARUCO_4X4_50_23",
    "ARUCO_4X4_50_24",
    "ARUCO_4X4_50_27",
    "ARUCO_4X4_50_29",
)
REGISTERED_ARUCO_ITEM_MARKER_IDS = frozenset(DEFAULT_ARUCO_ITEM_MARKER_IDS)


def _normalize_lift_operation(operation: str) -> str:
    normalized = operation.strip().upper().replace("-", "_")
    aliases = {
        "PICK_UP": "PICKUP",
        "PICKUP": "PICKUP",
        "DROP_OFF": "DROPOFF",
        "DROPOFF": "DROPOFF",
        "PRE_DROP_OFF": "PRE_DROP_OFF",
        "PRE_DROPOFF": "PRE_DROP_OFF",
    }
    try:
        return aliases[normalized]
    except KeyError as exc:
        raise HTTPException(
            status_code=400, detail=f"unknown lift-load operation: {operation}"
        ) from exc


def _normalize_expected_marker_id(value: str | int) -> str:
    raw = str(value).strip().upper()
    if raw.startswith("ARUCO_4X4_50_"):
        suffix = raw.rsplit("_", 1)[-1]
    else:
        suffix = raw
    try:
        marker_int = int(suffix)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=f"invalid expected marker id: {value}") from exc
    if marker_int < 20 or marker_int > 49:
        raise HTTPException(
            status_code=400,
            detail="expected item marker id must be in 20..49; 0..19 are reserved for map/zone/spare markers",
        )
    return f"ARUCO_4X4_50_{marker_int}"


def _expected_marker_ids(payload: LiftLoadEvaluateRequest) -> tuple[str, ...]:
    marker_values: list[str | int] = []
    if payload.expected_marker_id is not None:
        marker_values.append(payload.expected_marker_id)
    if payload.expected_marker_ids:
        marker_values.extend(payload.expected_marker_ids)
    if not marker_values:
        return DEFAULT_ARUCO_ITEM_MARKER_IDS
    return tuple(sorted({_normalize_expected_marker_id(value) for value in marker_values}))


def _lift_monitor_event_type(*, operation: str, result: str) -> str:
    if result == "NO_DECISION":
        return "NO_DECISION"
    if result == "UNCERTAIN":
        return "LIFT_LOAD_UNCERTAIN"
    if result != "PASS":
        return "LIFT_LOAD_EVIDENCE"
    if operation == "PICKUP":
        return "ITEM_PICKED"
    if operation == "DROPOFF":
        return "ITEM_PLACED"
    if operation == "PRE_DROP_OFF":
        return "ITEM_PLACEMENT_READY"
    return "LIFT_LOAD_EVIDENCE"


def _build_lift_load_monitor_event(
    *,
    source: str,
    robot_id: str | None,
    task_id: int | str | None,
    command_id: int | str | None,
    operation: str,
    result: str,
    reason_code: str,
    confidence: float | None,
    observed_at: str,
    expected_item_id: str | None,
    expected_marker_ids: tuple[str, ...],
    expected_item_count: int,
    detected_marker_ids: list[str],
    vision_zone_id: str | None,
    location_id: str | None,
    zone_resolution_source: str | None,
    accepted_frames: int,
    total_frames: int,
    observed_count: int | None,
) -> dict[str, Any]:
    event_type = _lift_monitor_event_type(operation=operation, result=result)
    severity = "INFO" if result == "PASS" else ("LOW" if result == "NO_DECISION" else "MEDIUM")
    payload = {
        "schema_version": "vision-monitor-event.v1",
        "event_id": str(uuid4()),
        "event_type": event_type,
        "source": source,
        "robot_id": robot_id,
        "task_id": task_id,
        "command_id": command_id,
        "result": result,
        "severity": severity,
        "confidence": confidence,
        "reason_code": reason_code,
        "trusted": False,
        "observed_at": observed_at,
        "image_url": None,
        "policy_version": VISION_MONITOR_POLICY_VERSION,
        "profile_id": LIFT_EVIDENCE_PROFILE_ID,
        "threshold_set_id": LIFT_EVIDENCE_THRESHOLD_SET_ID,
        "data_json": {
            "result": result,
            "reason_code": reason_code,
            "policy_version": VISION_MONITOR_POLICY_VERSION,
            "profile_id": LIFT_EVIDENCE_PROFILE_ID,
            "threshold_set_id": LIFT_EVIDENCE_THRESHOLD_SET_ID,
            "assignment_status": "OWNED" if robot_id else "UNASSIGNED",
            "related_robot_ids": [],
            "task_id_ref": task_id,
            "expected_item_id": expected_item_id,
            "expected_marker_ids": list(expected_marker_ids),
            "detected_marker_ids": sorted(set(detected_marker_ids)),
            "detected_marker_id": detected_marker_ids[0]
            if len(set(detected_marker_ids)) == 1
            else None,
            "marker_dictionary": "DICT_4X4_50",
            "vision_zone_id": vision_zone_id,
            "location_id": location_id,
            "zone_resolution_source": zone_resolution_source,
            "operation": operation,
            "expected_count": expected_item_count,
            "expected_item_count": expected_item_count,
            "observed_count": observed_count,
            "accepted_frames": accepted_frames,
            "total_frames": total_frames,
            "command_satisfying": event_type in {"ITEM_PICKED", "ITEM_PLACED", "ITEM_PLACEMENT_READY"},
        },
    }
    validate_vision_monitor_event(payload)
    return payload


def _lift_load_response(
    *,
    payload: LiftLoadEvaluateRequest,
    operation: str,
    vision_zone_id: str | None,
    result: str,
    reason_code: str,
    event: dict[str, Any],
) -> dict[str, Any]:
    return {
        "schema_version": "vision-lift-load-evaluate.v1",
        "monitor_id": "lift_evidence",
        "source": payload.source,
        "robot_id": payload.robot_id,
        "task_id": payload.task_id,
        "command_id": payload.command_id,
        "operation": operation,
        "vision_zone_id": vision_zone_id,
        "result": result,
        "reason_code": reason_code,
        "event": event,
    }


def _zone_config_for_lift_evidence() -> ZoneRoiConfig | None:
    path = Path(get_settings().vision_zone_roi_config_path)
    if not path.is_absolute():
        path = REPO_ROOT / path
    try:
        return load_zone_roi_config_cached(str(path), True)
    except (OSError, ValueError) as exc:
        _runtime_context().logger.warning("invalid lift evidence ZoneROI config: %s", exc)
        return None


def _resolve_lift_evidence_zone(
    config: ZoneRoiConfig,
    *,
    vision_zone_id: str | None,
    location_id: str | None,
) -> tuple[ZoneRoi | None, str | None, str | None]:
    """Resolve the explicit zone id or its configured Main location alias."""

    if vision_zone_id:
        return find_zone_by_id(config, vision_zone_id), vision_zone_id, "vision_zone_id"
    if not location_id:
        return None, None, None
    aliases = config.location_aliases or {}
    mapped_zone_id = aliases.get(location_id)
    if not mapped_zone_id:
        return None, None, "unmapped_location_id"
    return find_zone_by_id(config, mapped_zone_id), mapped_zone_id, "location_aliases"


def _is_item_marker_id(marker_id: str, item_marker_ids: set[str]) -> bool:
    """Return whether a marker belongs to the active item catalog."""

    return marker_id in item_marker_ids


def _frame_marker_ids_in_zone(
    *,
    frame: StoredFrame,
    zone: ZoneRoi,
    expected_marker_ids: set[str],
) -> tuple[int, int, list[str], list[str]]:
    if frame.decoded_bgr is None:
        return 0, 0, [], []
    expected_hits: list[str] = []
    any_item_hits: list[str] = []
    item_marker_ids = set(REGISTERED_ARUCO_ITEM_MARKER_IDS) | expected_marker_ids
    for detection in detect_markers(frame.decoded_bgr):
        bbox = detection.bbox_xyxy
        x = (bbox[0] + bbox[2]) / 2.0
        y = (bbox[1] + bbox[3]) / 2.0
        if not zone_contains_pixel(
            zone,
            x=x,
            y=y,
            image_width=frame.image_width,
            image_height=frame.image_height,
        ):
            continue
        if _is_item_marker_id(detection.marker_id, item_marker_ids):
            any_item_hits.append(detection.marker_id)
        if detection.marker_id in expected_marker_ids:
            expected_hits.append(detection.marker_id)
    return len(expected_hits), len(any_item_hits), expected_hits, any_item_hits


async def _latest_frame_burst(
    *,
    source: str,
    burst_frames: int,
    sample_interval_ms: int,
    max_frame_age_s: float,
) -> tuple[list[StoredFrame], StoredFrame | None]:
    frames: list[StoredFrame] = []
    seen_frame_seq: set[int] = set()
    latest_seen: StoredFrame | None = None
    attempts = max(burst_frames, burst_frames * 3)
    for attempt in range(attempts):
        frame = _runtime_context().frame_store.latest(source)
        if frame is not None:
            latest_seen = frame
            if frame.frame_seq not in seen_frame_seq and _frame_age_s(frame) <= max_frame_age_s:
                frames.append(frame)
                seen_frame_seq.add(frame.frame_seq)
                if len(frames) >= burst_frames:
                    break
        if sample_interval_ms > 0 and attempt < attempts - 1:
            await async_sleep(sample_interval_ms / 1000.0)
    return frames, latest_seen


async def lift_load_evaluate(payload: LiftLoadEvaluateRequest) -> dict[str, Any]:
    operation = _normalize_lift_operation(payload.operation)
    if payload.source != "global_cam_01":
        raise HTTPException(
            status_code=400, detail="lift-load evidence requires source global_cam_01"
        )
    if payload.robot_id not in {"tb3_1", "tb3_2"}:
        raise HTTPException(
            status_code=400, detail="lift-load evidence requires robot_id tb3_1 or tb3_2"
        )
    expected_marker_ids = _expected_marker_ids(payload)
    expected_marker_set = set(expected_marker_ids)
    vision_zone_id = payload.vision_zone_id
    zone_resolution_source: str | None = None
    observed_at = _now_iso()

    def no_decision(
        reason_code: str, *, confidence: float | None = None, observed_count: int | None = None
    ) -> dict[str, Any]:
        event = _build_lift_load_monitor_event(
            source=payload.source,
            robot_id=payload.robot_id,
            task_id=payload.task_id,
            command_id=payload.command_id,
            operation=operation,
            result="NO_DECISION",
            reason_code=reason_code,
            confidence=confidence,
            observed_at=observed_at,
            expected_item_id=payload.expected_item_id,
            expected_marker_ids=expected_marker_ids,
            expected_item_count=payload.expected_item_count,
            detected_marker_ids=[],
            vision_zone_id=vision_zone_id,
            location_id=payload.location_id,
            zone_resolution_source=zone_resolution_source,
            accepted_frames=0,
            total_frames=0,
            observed_count=observed_count,
        )
        return _lift_load_response(
            payload=payload,
            operation=operation,
            vision_zone_id=vision_zone_id,
            result="NO_DECISION",
            reason_code=reason_code,
            event=event,
        )

    if not payload.vision_zone_id and not payload.location_id:
        return no_decision("POLICY_NOT_APPLICABLE")
    zone_config = _zone_config_for_lift_evidence()
    if zone_config is None or zone_config.source != payload.source:
        return no_decision("POLICY_NOT_APPLICABLE")
    zone, resolved_zone_id, zone_resolution_source = _resolve_lift_evidence_zone(
        zone_config,
        vision_zone_id=payload.vision_zone_id,
        location_id=payload.location_id,
    )
    vision_zone_id = resolved_zone_id
    if zone is None:
        return no_decision("POLICY_NOT_APPLICABLE")
    if not zone.natural_item_location:
        return no_decision("POLICY_NOT_APPLICABLE")

    frames, latest_seen = await _latest_frame_burst(
        source=payload.source,
        burst_frames=payload.burst_frames,
        sample_interval_ms=payload.sample_interval_ms,
        max_frame_age_s=payload.max_frame_age_s,
    )
    if not frames:
        reason = "SOURCE_STALE" if latest_seen is not None else "NO_RELEVANT_DETECTION"
        return no_decision(reason)

    per_frame_expected_counts: list[int] = []
    per_frame_item_counts: list[int] = []
    expected_hits_all: list[str] = []
    item_hits_all: list[str] = []
    for frame in frames:
        (
            expected_count_in_frame,
            item_count_in_frame,
            expected_hits,
            item_hits,
        ) = await run_in_threadpool(
            _frame_marker_ids_in_zone,
            frame=frame,
            zone=zone,
            expected_marker_ids=expected_marker_set,
        )
        per_frame_expected_counts.append(expected_count_in_frame)
        per_frame_item_counts.append(item_count_in_frame)
        expected_hits_all.extend(expected_hits)
        item_hits_all.extend(item_hits)

    expected_count = int(payload.expected_item_count)
    min_pass_frames = payload.min_pass_frames
    judgement = evaluate_lift_load_marker_burst(
        per_frame_expected_counts=per_frame_expected_counts,
        per_frame_item_counts=per_frame_item_counts,
        expected_count=expected_count,
        operation=operation,
        min_pass_frames=min_pass_frames,
        requested_frames=payload.burst_frames,
    )

    event = _build_lift_load_monitor_event(
        source=payload.source,
        robot_id=payload.robot_id,
        task_id=payload.task_id,
        command_id=payload.command_id,
        operation=operation,
        result=judgement["result"],
        reason_code=judgement["reason_code"],
        confidence=judgement["confidence"],
        observed_at=observed_at,
        expected_item_id=payload.expected_item_id,
        expected_marker_ids=expected_marker_ids,
        expected_item_count=expected_count,
        detected_marker_ids=item_hits_all or expected_hits_all,
        vision_zone_id=vision_zone_id,
        location_id=payload.location_id,
        zone_resolution_source=zone_resolution_source,
        accepted_frames=judgement["accepted_frames"],
        total_frames=judgement["total_frames"],
        observed_count=judgement["observed_count"],
    )
    return _lift_load_response(
        payload=payload,
        operation=operation,
        vision_zone_id=vision_zone_id,
        result=judgement["result"],
        reason_code=judgement["reason_code"],
        event=event,
    )


async def ingest_synthetic_frame(payload: SyntheticFrameRequest) -> dict[str, Any]:
    """Generate and ingest a synthetic ArUco frame for robot-free Lane B validation.

    This debug endpoint exercises the same latest-frame, detection, and overlay
    path used by uploaded images, without requiring a physical camera or ROS2.
    """
    _ensure_known_source(payload.source)
    try:
        decoded_image = generate_synthetic_aruco_frame(
            marker_id=payload.marker_id, marker_size=payload.marker_size, padding=payload.padding
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    processed = _detect_and_overlay_decoded_frame(
        source=payload.source,
        decoded_image=decoded_image,
        content_type="image/jpeg",
        stale=payload.stale,
    )
    events = processed["events"]
    overlay: OverlayRenderResult = processed["overlay"]
    settings = get_settings()
    emit_disabled = bool(payload.emit and (not settings.wms_emit_enabled))
    emit_results: list[dict[str, Any]] = []
    if payload.emit and settings.wms_emit_enabled and events:
        emit_results = await _emit_vision_events()(events, settings=settings)
    emitted = bool(
        payload.emit
        and settings.wms_emit_enabled
        and events
        and all((result["ok"] for result in emit_results))
    )
    return {
        "source": payload.source,
        "emitted": emitted,
        "emit_disabled": emit_disabled,
        "emit_results": emit_results,
        "events": events,
        "overlay": overlay.metadata(),
    }


async def detect_image(
    source: str = Form(..., json_schema_extra=SOURCE_ID_OPENAPI_EXTRA),
    image: UploadFile = File(...),
    emit: bool = Form(default=False),
    pose_profile: str | None = Form(default=None),
    marker_size_m: float | None = Form(default=None),
    camera_fx: float | None = Form(default=None),
    camera_fy: float | None = Form(default=None),
    camera_cx: float | None = Form(default=None),
    camera_cy: float | None = Form(default=None),
    camera_dist_coeffs: str | None = Form(default=None),
) -> dict[str, Any]:
    """Debug/offline detector endpoint.

    The endpoint decodes uploaded images, runs deterministic marker detectors,
    and returns contract-valid VisionEvents for detections.
    """
    return await build_detect_image_response(
        source=source,
        image=image,
        emit=emit,
        pose_profile=pose_profile,
        marker_size_m=marker_size_m,
        camera_fx=camera_fx,
        camera_fy=camera_fy,
        camera_cx=camera_cx,
        camera_cy=camera_cy,
        camera_dist_coeffs=camera_dist_coeffs,
        decode_image=decode_image,
        optional_pose_request=_optional_pose_request,
        detect_and_overlay_decoded_frame=_detect_and_overlay_decoded_frame,
        emit_vision_events=_emit_vision_events,
    )


def _with_route_dependencies(
    handler,
    *,
    context_getter: ContextGetter,
    emit_vision_events_getter: Callable[[], Any],
    lift_roi_segmenter_getter: Callable[[], Any],
):
    @wraps(handler)
    async def wrapper(*args, **kwargs):
        context_token = _context_getter_var.set(context_getter)
        emit_token = _emit_vision_events_getter_var.set(emit_vision_events_getter)
        segmenter_token = _lift_roi_segmenter_getter_var.set(lift_roi_segmenter_getter)
        try:
            result = handler(*args, **kwargs)
            if isawaitable(result):
                return await result
            return result
        finally:
            _lift_roi_segmenter_getter_var.reset(segmenter_token)
            _emit_vision_events_getter_var.reset(emit_token)
            _context_getter_var.reset(context_token)

    return wrapper


def register_vision_routes(
    app,
    *,
    context_getter: ContextGetter,
    emit_vision_events_getter: Callable[[], Any] | None = None,
    lift_roi_segmenter_getter: Callable[[], Any] | None = None,
) -> None:
    """Register remaining non-health AI Server route clusters."""
    emit_getter = emit_vision_events_getter or (lambda: default_emit_vision_events)
    segmenter_getter = lift_roi_segmenter_getter or (lambda: _get_lift_roi_segmenter)

    def route(handler):
        return _with_route_dependencies(
            handler,
            context_getter=context_getter,
            emit_vision_events_getter=emit_getter,
            lift_roi_segmenter_getter=segmenter_getter,
        )

    app.get(
        "/api/v1/vision/streams",
        responses={
            200: _json_response_openapi(
                "Main-facing HTTP/MJPEG Vision Stream Gateway discovery",
                _vision_streams_response_schema(),
            ),
            400: ERROR_RESPONSE_OPENAPI,
        },
    )(route(vision_streams))
    app.post(
        "/api/v1/vision/streams/{source}/webrtc/offer",
        dependencies=[Depends(require_main_hmac)],
        responses={
            200: _json_response_openapi(
                "Media-only WebRTC candidate offer/fallback descriptor",
                {"type": "object", "additionalProperties": True},
            ),
            400: ERROR_RESPONSE_OPENAPI,
            422: ERROR_RESPONSE_OPENAPI,
        },
    )(route(vision_webrtc_offer))
    app.get("/api/v1/vision/webrtc/demo", responses={400: ERROR_RESPONSE_OPENAPI})(
        route(vision_webrtc_demo)
    )
    app.get(
        "/api/v1/vision/ros/topics",
        responses={
            200: _json_response_openapi(
                "Lane B ROS2/domain-bridge handoff topic matrix", _ros_handoff_response_schema()
            )
        },
    )(route(vision_ros_topics))
    app.get(
        "/api/v1/vision/worker/status",
        responses={
            200: _json_response_openapi(
                "Lane B read-only worker readiness snapshot", _worker_status_response_schema()
            ),
            400: ERROR_RESPONSE_OPENAPI,
            422: ERROR_RESPONSE_OPENAPI,
        },
    )(route(vision_worker_status))
    app.post(
        "/api/v1/vision/worker/tick",
        dependencies=[Depends(require_main_hmac)],
        responses={
            401: ERROR_RESPONSE_OPENAPI,
            400: ERROR_RESPONSE_OPENAPI,
            422: ERROR_RESPONSE_OPENAPI,
            500: ERROR_RESPONSE_OPENAPI,
            503: ERROR_RESPONSE_OPENAPI,
        },
    )(route(vision_worker_tick))
    app.get(
        "/api/v1/vision/monitors",
        responses={
            200: _json_response_openapi(
                "Vision monitor state list", _vision_monitor_states_response_schema()
            ),
            400: ERROR_RESPONSE_OPENAPI,
        },
    )(route(vision_monitor_states))
    app.get(
        "/api/v1/vision/monitors/{monitor_id}/state",
        responses={
            200: _json_response_openapi(
                "Vision monitor state", _vision_monitor_state_response_schema()
            ),
            400: ERROR_RESPONSE_OPENAPI,
        },
    )(route(vision_monitor_state))
    app.put(
        "/api/v1/vision/monitors/{monitor_id}/state",
        dependencies=[Depends(require_main_hmac)],
        responses={
            200: _json_response_openapi(
                "Vision monitor state", _vision_monitor_state_response_schema()
            ),
            400: ERROR_RESPONSE_OPENAPI,
            401: ERROR_RESPONSE_OPENAPI,
            422: ERROR_RESPONSE_OPENAPI,
            503: ERROR_RESPONSE_OPENAPI,
        },
    )(route(update_vision_monitor_state))
    app.get(
        "/api/v1/vision/hazards/person/latest",
        responses={
            200: _json_response_openapi(
                "Latest advisory person hazard monitor event",
                _person_hazard_latest_response_schema(),
            ),
            400: ERROR_RESPONSE_OPENAPI,
        },
    )(route(person_hazard_latest))
    app.post(
        "/api/v1/vision/evidence/lift-load/evaluate",
        dependencies=[Depends(require_main_hmac)],
        responses={
            200: _json_response_openapi(
                "One-shot fixed ZoneROI ArUco lift-load evidence evaluation",
                _lift_load_evaluate_response_schema(),
            ),
            400: ERROR_RESPONSE_OPENAPI,
            401: ERROR_RESPONSE_OPENAPI,
            422: ERROR_RESPONSE_OPENAPI,
            503: ERROR_RESPONSE_OPENAPI,
        },
    )(route(lift_load_evaluate))
    app.get(
        "/api/v1/vision/debug/sources",
        responses={
            200: _json_response_openapi(
                "Lane B source/frame/overlay debug snapshot", _debug_sources_response_schema()
            ),
            400: ERROR_RESPONSE_OPENAPI,
        },
    )(route(vision_debug_sources))
    app.post(
        "/api/v1/vision/frame",
        dependencies=[Depends(require_vision_gateway_hmac)],
        responses={
            200: _json_response_openapi(
                "Latest-frame ingest debug response", _frame_ingest_response_schema()
            ),
            400: ERROR_RESPONSE_OPENAPI,
            401: ERROR_RESPONSE_OPENAPI,
            422: ERROR_RESPONSE_OPENAPI,
            503: ERROR_RESPONSE_OPENAPI,
        },
    )(route(ingest_frame))
    app.post(
        "/api/v1/vision/frame/process",
        dependencies=[Depends(require_vision_gateway_hmac)],
        responses={
            200: _json_response_openapi(
                "Latest-frame ingest plus immediate overlay processing response",
                _frame_process_response_schema(),
            ),
            400: ERROR_RESPONSE_OPENAPI,
            401: ERROR_RESPONSE_OPENAPI,
            422: ERROR_RESPONSE_OPENAPI,
            503: ERROR_RESPONSE_OPENAPI,
        },
    )(route(ingest_and_process_frame))
    app.get(
        "/api/v1/vision/frame/latest",
        responses={
            200: _json_response_openapi(
                "Latest raw frame debug metadata", _latest_frame_response_schema()
            ),
            400: ERROR_RESPONSE_OPENAPI,
            404: ERROR_RESPONSE_OPENAPI,
        },
    )(route(latest_frame))
    app.get(
        "/api/v1/vision/frame/latest/image",
        responses={400: ERROR_RESPONSE_OPENAPI, 404: ERROR_RESPONSE_OPENAPI},
    )(route(latest_frame_image))
    app.get(
        "/api/v1/vision/overlay/latest",
        responses={400: ERROR_RESPONSE_OPENAPI, 404: ERROR_RESPONSE_OPENAPI},
    )(route(latest_overlay))
    app.get(
        "/api/v1/vision/overlay/metadata",
        responses={
            200: _json_response_openapi(
                "Diagnostic client-renderable AI overlay metadata; public streams are burned overlay",
                _overlay_canvas_metadata_response_schema(),
            ),
            400: ERROR_RESPONSE_OPENAPI,
            404: ERROR_RESPONSE_OPENAPI,
        },
    )(route(latest_overlay_metadata))
    app.get(
        "/api/v1/vision/overlay/latest/image",
        responses={400: ERROR_RESPONSE_OPENAPI, 404: ERROR_RESPONSE_OPENAPI},
    )(route(latest_overlay_image))
    app.get(
        "/api/v1/vision/stream/{source}.mjpeg",
        responses={400: ERROR_RESPONSE_OPENAPI, 404: ERROR_RESPONSE_OPENAPI},
    )(route(debug_overlay_mjpeg_stream))
    app.get(
        "/api/v1/metrics", responses={200: METRICS_RESPONSE_OPENAPI, 400: ERROR_RESPONSE_OPENAPI}
    )(route(metrics_snapshot))
    app.post(
        "/api/v1/vision/synthetic/frame",
        dependencies=[Depends(require_main_hmac)],
        responses={
            200: _json_response_openapi(
                "Synthetic frame detection response with overlay metadata",
                _synthetic_frame_response_schema(),
            ),
            400: ERROR_RESPONSE_OPENAPI,
            401: ERROR_RESPONSE_OPENAPI,
            422: ERROR_RESPONSE_OPENAPI,
            500: ERROR_RESPONSE_OPENAPI,
            503: ERROR_RESPONSE_OPENAPI,
        },
    )(route(ingest_synthetic_frame))
    app.post(
        "/api/v1/detect/image",
        dependencies=[Depends(require_main_hmac)],
        responses={
            200: _json_response_openapi(
                "Image detection response with VisionEvent v1 events",
                _detect_image_response_schema(),
            ),
            400: ERROR_RESPONSE_OPENAPI,
            401: ERROR_RESPONSE_OPENAPI,
            422: ERROR_RESPONSE_OPENAPI,
            500: ERROR_RESPONSE_OPENAPI,
            503: ERROR_RESPONSE_OPENAPI,
        },
    )(route(detect_image))


__all__ = ["_mjpeg_latest_overlay_generator", "register_vision_routes"]
