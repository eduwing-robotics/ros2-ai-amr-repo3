from __future__ import annotations

from collections.abc import Callable
from typing import Any

from ..config import get_settings
from ..runtime_state import RuntimeContext
from .vision_read_model_ros import FrameAgeGetter


def worker_status_for_source(
    *,
    source: str,
    max_frame_age_s: float,
    runtime_context: RuntimeContext,
    frame_age_s: FrameAgeGetter,
) -> dict[str, Any]:
    frame = runtime_context.frame_store.latest(source)
    latest_overlay_metadata = runtime_context.overlay_cache.latest(source)
    overlay_frame_seq = (
        latest_overlay_metadata.get("frame_seq")
        if isinstance(latest_overlay_metadata, dict)
        else None
    )
    if frame is None:
        return {
            "source": source,
            "has_frame": False,
            "has_overlay": latest_overlay_metadata is not None,
            "latest_frame_seq": None,
            "latest_overlay_frame_seq": overlay_frame_seq,
            "frame_age_s": None,
            "max_frame_age_s": max_frame_age_s,
            "overlay_lag_frames": None,
            "pending": False,
            "next_tick_status": "no_frame",
            "would_create_new_evidence": False,
            "evidence_action_if_ticked": "none",
            "expected_new_event_count": 0,
            "reused_event_count_if_ticked": 0,
            "reason": "no latest frame available",
        }

    resolved_frame_age_s = round(frame_age_s(frame), 3)
    overlay_lag_frames = (
        max(0, frame.frame_seq - overlay_frame_seq) if isinstance(overlay_frame_seq, int) else None
    )
    if resolved_frame_age_s > max_frame_age_s:
        next_status = "stale_frame"
        pending = False
        would_create_new_evidence = False
        evidence_action_if_ticked = "none"
        expected_new_event_count = 0
        reused_event_count_if_ticked = 0
        reason = "latest frame is older than max_frame_age_s"
    elif isinstance(overlay_frame_seq, int) and overlay_frame_seq >= frame.frame_seq:
        next_status = "skipped"
        pending = False
        would_create_new_evidence = False
        evidence_action_if_ticked = "reused"
        expected_new_event_count = 0
        reused_event_count_if_ticked = int(latest_overlay_metadata.get("event_count", 0))
        reason = "latest overlay already matches latest frame"
    else:
        next_status = "processed"
        pending = True
        would_create_new_evidence = True
        evidence_action_if_ticked = "created"
        expected_new_event_count = None
        reused_event_count_if_ticked = 0
        reason = "new frame pending processing"
    return {
        "source": source,
        "has_frame": True,
        "has_overlay": latest_overlay_metadata is not None,
        "latest_frame_seq": frame.frame_seq,
        "latest_overlay_frame_seq": overlay_frame_seq,
        "frame_age_s": resolved_frame_age_s,
        "max_frame_age_s": max_frame_age_s,
        "overlay_lag_frames": overlay_lag_frames,
        "pending": pending,
        "next_tick_status": next_status,
        "would_create_new_evidence": would_create_new_evidence,
        "evidence_action_if_ticked": evidence_action_if_ticked,
        "expected_new_event_count": expected_new_event_count,
        "reused_event_count_if_ticked": reused_event_count_if_ticked,
        "reason": reason,
    }


def worker_status_summary(items: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts = {"no_frame": 0, "processed": 0, "skipped": 0, "stale_frame": 0}
    pending_count = 0
    stale_count = 0
    would_create_new_evidence_count = 0
    expected_new_event_count_total = 0
    reused_event_count_if_ticked_total = 0
    for item in items:
        status = str(item.get("next_tick_status") or "")
        if status in status_counts:
            status_counts[status] += 1
        if item.get("pending") is True:
            pending_count += 1
        if item.get("would_create_new_evidence") is True:
            would_create_new_evidence_count += 1
        if isinstance(item.get("expected_new_event_count"), int):
            expected_new_event_count_total += int(item["expected_new_event_count"])
        reused_event_count_if_ticked_total += int(item.get("reused_event_count_if_ticked") or 0)
        if status == "stale_frame":
            stale_count += 1
    return {
        "sources_total": len(items),
        "pending_count": pending_count,
        "stale_frame_count": stale_count,
        "would_create_new_evidence_count": would_create_new_evidence_count,
        "expected_new_event_count_total": expected_new_event_count_total,
        "reused_event_count_if_ticked_total": reused_event_count_if_ticked_total,
        "status_counts": status_counts,
    }


def build_vision_worker_status_payload(
    *,
    source: str | None,
    max_frame_age_s: float | None,
    runtime_context: RuntimeContext,
    frame_age_s: FrameAgeGetter,
    now_iso: Callable[[], str],
) -> dict[str, Any]:
    settings = get_settings()
    sources = [source] if source is not None else list(settings.source_ids)
    resolved_max_frame_age_s = (
        max_frame_age_s if max_frame_age_s is not None else settings.source_stale_after_s
    )
    status_items = [
        worker_status_for_source(
            source=item,
            max_frame_age_s=resolved_max_frame_age_s,
            runtime_context=runtime_context,
            frame_age_s=frame_age_s,
        )
        for item in sources
    ]
    return {
        "generated_at": now_iso(),
        "requested_source": source,
        "max_frame_age_s": resolved_max_frame_age_s,
        "debug_only": True,
        "summary": worker_status_summary(status_items),
        "sources": status_items,
    }
