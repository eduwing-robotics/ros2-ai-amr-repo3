"""Direct tests for split Vision endpoint helper modules."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.api.vision_frame_endpoints import build_frame_process_response
from app.api.vision_overlay_endpoints import (
    build_latest_overlay_image_response,
    build_latest_overlay_response,
)
from app.overlay import OverlayRenderResult
from app.runtime_state import create_runtime_context


@dataclass(frozen=True)
class FakeFrame:
    source: str
    frame_seq: int

    def metadata(self, *, include_content: bool = False) -> dict:
        payload = {"source": self.source, "frame_seq": self.frame_seq}
        if include_content:
            payload["size_bytes"] = 4
        return payload


class FakeUpload:
    content_type = "image/png"

    async def read(self) -> bytes:
        return b"fake"


def _ingest_context(**kwargs) -> dict:
    return {"ros_callback_compatible": True, **kwargs}


def test_frame_process_helper_reuses_matching_overlay_without_detection():
    context = create_runtime_context()
    context.overlay_cache.add(
        {"source": "tb3_1_picam", "frame_seq": 7, "event_count": 2, "status": "cached"}
    )

    def store_latest_frame_from_bytes(**kwargs):
        assert kwargs["payload"] == b"fake"
        assert kwargs["content_type"] == "image/png"
        return FakeFrame(source=kwargs["source"], frame_seq=7)

    def fail_detection(**_):
        raise AssertionError("matching overlay should be reused when force is false")

    response = asyncio.run(
        build_frame_process_response(
            source="tb3_1_picam",
            image=FakeUpload(),
            force=False,
            stale=False,
            runtime_context=context,
            store_latest_frame_from_bytes=store_latest_frame_from_bytes,
            detect_and_overlay_frame_snapshot=fail_detection,
            frame_ingest_context=_ingest_context,
        )
    )

    assert response["processed"] is False
    assert response["status"] == "skipped"
    assert response["frame_seq"] == 7
    assert response["event_count"] == 2
    assert response["new_event_count"] == 0
    assert response["evidence_action"] == "reused"
    assert response["overlay"]["status"] == "cached"
    assert response["ingest_context"]["processed_inline"] is True


def test_frame_process_helper_processes_when_overlay_is_missing():
    context = create_runtime_context()
    frame = FakeFrame(source="tb3_2_picam", frame_seq=3)

    overlay = OverlayRenderResult(
        source=frame.source,
        frame_seq=frame.frame_seq,
        frame_timestamp="2026-06-22T00:00:00+00:00",
        evidence_timestamp=None,
        overlay_timestamp="2026-06-22T00:00:01+00:00",
        latency_ms=None,
        event_count=1,
        stale=True,
        image_width=1,
        image_height=1,
        jpeg=b"jpeg",
    )

    response = asyncio.run(
        build_frame_process_response(
            source=frame.source,
            image=FakeUpload(),
            force=False,
            stale=True,
            runtime_context=context,
            store_latest_frame_from_bytes=lambda **_: frame,
            detect_and_overlay_frame_snapshot=lambda **kwargs: {
                "overlay": overlay,
                "events": [{"event_id": "evt-1"}],
            },
            frame_ingest_context=_ingest_context,
        )
    )

    assert response["processed"] is True
    assert response["status"] == "processed"
    assert response["frame_seq"] == 3
    assert response["event_count"] == 1
    assert response["new_event_count"] == 1
    assert response["evidence_action"] == "created"
    assert response["overlay"]["visual_state"] == "stale"
    assert response["reason"] == "new frame processed"


def test_overlay_helpers_return_metadata_and_image_without_route_wrapper():
    context = create_runtime_context()
    context.overlay_cache.add({"source": "tb3_1_picam", "frame_seq": 1, "event_count": 0})
    overlay = OverlayRenderResult(
        source="tb3_1_picam",
        frame_seq=1,
        frame_timestamp="2026-06-22T00:00:00+00:00",
        evidence_timestamp=None,
        overlay_timestamp="2026-06-22T00:00:01+00:00",
        latency_ms=None,
        event_count=0,
        stale=False,
        image_width=1,
        image_height=1,
        jpeg=b"jpeg-bytes",
    )

    metadata = build_latest_overlay_response(
        source="tb3_1_picam",
        runtime_context=context,
        frame_overlay_sync_status=lambda source, *, runtime_context, view: {
            "source": source,
            "view": view,
            "runtime_context_bound": runtime_context is context,
        },
        now_iso=lambda: "2026-06-22T00:00:02+00:00",
    )
    image = build_latest_overlay_image_response(
        source="tb3_1_picam",
        latest_overlay_image=lambda source: overlay,
    )

    assert metadata == {
        "generated_at": "2026-06-22T00:00:02+00:00",
        "requested_source": "tb3_1_picam",
        "requested_view": "full",
        "sync": {
            "source": "tb3_1_picam",
            "view": "full",
            "runtime_context_bound": True,
        },
        "overlay": {
            "source": "tb3_1_picam",
            "view": "full",
            "frame_seq": 1,
            "event_count": 0,
        },
    }
    assert image.status_code == 200
    assert image.media_type == "image/jpeg"
    assert image.body == b"jpeg-bytes"
