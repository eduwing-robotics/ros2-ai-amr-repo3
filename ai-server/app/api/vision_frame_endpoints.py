from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, UploadFile
from fastapi.responses import Response

from ..frame_store import StoredFrame
from ..runtime_state import RuntimeContext

FrameIngestContextBuilder = Callable[..., dict[str, Any]]
StoreFrameFromBytes = Callable[..., StoredFrame]
DetectAndOverlayFrame = Callable[..., dict[str, Any]]


async def build_frame_ingest_response(
    *,
    source: str,
    image: UploadFile,
    store_latest_frame_from_bytes: StoreFrameFromBytes,
    frame_ingest_context: FrameIngestContextBuilder,
) -> dict[str, Any]:
    payload = await image.read()
    content_type = image.content_type or "application/octet-stream"
    try:
        frame = store_latest_frame_from_bytes(
            source=source,
            payload=payload,
            content_type=content_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "source": source,
        "processed": False,
        "frame": frame.metadata(include_content=True),
        "overlay": None,
        "ingest_context": frame_ingest_context(transport="http_debug", topic=None),
        "worker_tick_path": "/api/v1/vision/worker/tick",
    }


async def build_frame_process_response(
    *,
    source: str,
    image: UploadFile,
    force: bool,
    stale: bool,
    runtime_context: RuntimeContext,
    store_latest_frame_from_bytes: StoreFrameFromBytes,
    detect_and_overlay_frame_snapshot: DetectAndOverlayFrame,
    frame_ingest_context: FrameIngestContextBuilder,
) -> dict[str, Any]:
    payload = await image.read()
    content_type = image.content_type or "application/octet-stream"
    try:
        frame = store_latest_frame_from_bytes(
            source=source,
            payload=payload,
            content_type=content_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    latest_overlay_metadata = runtime_context.overlay_cache.latest(source)
    overlay_frame_seq = (
        latest_overlay_metadata.get("frame_seq")
        if isinstance(latest_overlay_metadata, dict)
        else None
    )
    if not force and isinstance(overlay_frame_seq, int) and overlay_frame_seq >= frame.frame_seq:
        return {
            "source": source,
            "processed": False,
            "status": "skipped",
            "frame_seq": frame.frame_seq,
            "event_count": int(latest_overlay_metadata.get("event_count", 0)),
            "new_event_count": 0,
            "evidence_action": "reused",
            "frame": frame.metadata(include_content=True),
            "overlay": latest_overlay_metadata,
            "reason": "latest overlay already matches latest frame",
            "ingest_context": frame_ingest_context(
                transport="http_debug",
                topic=None,
                processed_inline=True,
            ),
        }

    processed = detect_and_overlay_frame_snapshot(frame=frame, stale=stale)
    overlay = processed["overlay"]
    events = processed["events"]
    overlay_events = processed.get("overlay_events", events)
    return {
        "source": source,
        "processed": True,
        "status": "processed",
        "frame_seq": frame.frame_seq,
        "event_count": len(events),
        "new_event_count": len(events),
        "overlay_event_count": len(overlay_events),
        "evidence_action": "created",
        "frame": frame.metadata(include_content=True),
        "overlay": overlay.metadata(),
        "events": events,
        "overlay_events": overlay_events,
        "reason": "forced" if force else "new frame processed",
        "ingest_context": frame_ingest_context(
            transport="http_debug",
            topic=None,
            processed_inline=True,
        ),
    }


def build_latest_frame_response(
    *,
    source: str,
    runtime_context: RuntimeContext,
    now_iso: Callable[[], str],
) -> dict[str, Any]:
    frame = runtime_context.frame_store.latest(source)
    if frame is None:
        raise HTTPException(
            status_code=404,
            detail=f"no latest frame available for source: {source}",
        )
    return {"generated_at": now_iso(), "frame": frame.metadata(include_content=True)}


def build_latest_frame_image_response(
    *,
    source: str,
    runtime_context: RuntimeContext,
) -> Response:
    frame = runtime_context.frame_store.latest(source)
    if frame is None:
        raise HTTPException(
            status_code=404,
            detail=f"no latest frame image available for source: {source}",
        )
    return Response(content=frame.encoded, media_type=frame.content_type)
