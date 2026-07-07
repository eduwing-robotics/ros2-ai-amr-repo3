from __future__ import annotations

import numpy as np

from app.api import vision as vision_module
from app.api.vision_overlay_endpoints import (
    build_latest_overlay_image_response,
    build_latest_overlay_response,
)
from app.api.vision_read_model_ros import frame_overlay_sync_status
from app.overlay import OverlayRenderResult
from app.runtime_state import create_runtime_context


def _overlay_result(*, view: str, frame_seq: int, jpeg: bytes) -> OverlayRenderResult:
    return OverlayRenderResult(
        source="global_depth_01",
        view=view,
        frame_seq=frame_seq,
        frame_timestamp="2026-06-22T00:00:00+00:00",
        evidence_timestamp=None,
        overlay_timestamp="2026-06-22T00:00:01+00:00",
        latency_ms=None,
        event_count=0,
        stale=False,
        image_width=2,
        image_height=2,
        jpeg=jpeg,
    )


def test_latest_overlay_metadata_cache_is_partitioned_by_source_view():
    context = create_runtime_context()
    context.overlay_cache.add({"source": "global_depth_01", "view": "full", "frame_seq": 10})
    context.overlay_cache.add({"source": "global_depth_01", "view": "pallet_zoom", "frame_seq": 20})

    full = build_latest_overlay_response(
        source="global_depth_01",
        runtime_context=context,
        frame_overlay_sync_status=lambda source, *, runtime_context, view: {
            "source": source,
            "view": view,
            "runtime_context_bound": runtime_context is context,
        },
        now_iso=lambda: "2026-06-22T00:00:02+00:00",
    )
    zoom = build_latest_overlay_response(
        source="global_depth_01",
        view="pallet_zoom",
        runtime_context=context,
        frame_overlay_sync_status=lambda source, *, runtime_context, view: {
            "source": source,
            "view": view,
            "runtime_context_bound": runtime_context is context,
        },
        now_iso=lambda: "2026-06-22T00:00:02+00:00",
    )

    assert full["requested_view"] == "full"
    assert full["sync"]["view"] == "full"
    assert full["overlay"]["frame_seq"] == 10
    assert zoom["requested_view"] == "pallet_zoom"
    assert zoom["sync"]["view"] == "pallet_zoom"
    assert zoom["overlay"]["frame_seq"] == 20
    assert context.overlay_cache.latest("global_depth_01")["frame_seq"] == 10
    assert context.overlay_cache.latest("global_depth_01", view="pallet_zoom")["frame_seq"] == 20


def test_latest_overlay_image_cache_keeps_full_and_pallet_zoom_separate():
    context = create_runtime_context()
    full = _overlay_result(view="full", frame_seq=10, jpeg=b"full-jpeg")
    zoom = _overlay_result(view="pallet_zoom", frame_seq=20, jpeg=b"zoom-jpeg")
    token = vision_module._context_getter_var.set(lambda: context)
    try:
        vision_module._store_overlay_result(full)
        vision_module._store_overlay_result(zoom)
    finally:
        vision_module._context_getter_var.reset(token)

    default_full = vision_module._latest_overlay_image(
        "global_depth_01",
        runtime_context=context,
    )
    explicit_full = vision_module._latest_overlay_image(
        "global_depth_01",
        view="full",
        runtime_context=context,
    )
    explicit_zoom = vision_module._latest_overlay_image(
        "global_depth_01",
        view="pallet_zoom",
        runtime_context=context,
    )
    zoom_response = build_latest_overlay_image_response(
        source="global_depth_01",
        view="pallet_zoom",
        latest_overlay_image=lambda source, *, view: vision_module._latest_overlay_image(
            source,
            view=view,
            runtime_context=context,
        ),
    )

    assert default_full is full
    assert explicit_full is full
    assert explicit_zoom is zoom
    assert zoom_response.body == b"zoom-jpeg"


def test_overlay_sync_status_uses_requested_view_bucket():
    context = create_runtime_context()
    image = np.zeros((8, 8, 3), dtype=np.uint8)
    for _ in range(25):
        context.frame_store.put_decoded(source="global_depth_01", image_bgr=image)
    context.overlay_cache.add(
        {
            "source": "global_depth_01",
            "view": "full",
            "frame_seq": 10,
            "visual_state": "fresh",
        }
    )
    context.overlay_cache.add(
        {
            "source": "global_depth_01",
            "view": "pallet_zoom",
            "frame_seq": 20,
            "visual_state": "stale",
        }
    )

    full_sync = frame_overlay_sync_status(
        "global_depth_01",
        runtime_context=context,
    )
    zoom = build_latest_overlay_response(
        source="global_depth_01",
        view="pallet_zoom",
        runtime_context=context,
        frame_overlay_sync_status=frame_overlay_sync_status,
        now_iso=lambda: "2026-06-22T00:00:02+00:00",
    )

    assert full_sync["latest_overlay_frame_seq"] == 10
    assert full_sync["overlay_lag_frames"] == 15
    assert zoom["sync"]["latest_overlay_frame_seq"] == 20
    assert zoom["sync"]["overlay_lag_frames"] == 5
    assert zoom["sync"]["overlay_visual_state"] == "stale"
