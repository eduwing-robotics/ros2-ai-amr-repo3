from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import HTTPException, UploadFile

from ..config import get_settings


async def build_detect_image_response(
    *,
    source: str,
    image: UploadFile,
    emit: bool,
    pose_profile: str | None,
    marker_size_m: float | None,
    camera_fx: float | None,
    camera_fy: float | None,
    camera_cx: float | None,
    camera_cy: float | None,
    camera_dist_coeffs: str | None,
    decode_image: Callable[[bytes], Any],
    optional_pose_request: Callable[..., Any],
    detect_and_overlay_decoded_frame: Callable[..., dict[str, Any]],
    emit_vision_events: Callable[[], Any],
) -> dict[str, Any]:
    settings = get_settings()
    if source not in settings.source_ids:
        raise HTTPException(status_code=400, detail=f"unknown source: {source}")

    payload = await image.read()
    try:
        decoded_image = decode_image(payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    pose_request = optional_pose_request(
        pose_profile=pose_profile,
        marker_size_m=marker_size_m,
        camera_fx=camera_fx,
        camera_fy=camera_fy,
        camera_cx=camera_cx,
        camera_cy=camera_cy,
        camera_dist_coeffs=camera_dist_coeffs,
    )
    processed = detect_and_overlay_decoded_frame(
        source=source,
        decoded_image=decoded_image,
        encoded=payload,
        content_type=image.content_type or "application/octet-stream",
        pose_request=pose_request,
    )
    events = processed["events"]
    emit_disabled = bool(emit and not settings.wms_emit_enabled)
    emit_results: list[dict[str, Any]] = []
    if emit and settings.wms_emit_enabled and events:
        emit_results = await emit_vision_events()(events, settings=settings)
    emitted = bool(
        emit
        and settings.wms_emit_enabled
        and events
        and all(result["ok"] for result in emit_results)
    )
    return {
        "source": source,
        "emitted": emitted,
        "emit_disabled": emit_disabled,
        "emit_results": emit_results,
        "events": events,
    }
