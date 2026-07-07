from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.source_health import InMemorySourceHealthTracker, source_status


def _t(seconds: float = 0.0) -> datetime:
    return datetime(2026, 6, 11, 12, 0, 0, tzinfo=timezone.utc) + timedelta(seconds=seconds)


def test_source_status_moves_from_offline_to_online_stale_and_offline():
    assert (
        source_status(
            enabled=True,
            last_frame_at=None,
            now=_t(0),
            stale_after_s=2.0,
            offline_after_s=30.0,
        )[0]
        == "offline"
    )
    assert (
        source_status(
            enabled=True,
            last_frame_at=_t(0),
            now=_t(1.0),
            stale_after_s=2.0,
            offline_after_s=30.0,
        )[0]
        == "online"
    )
    assert (
        source_status(
            enabled=True,
            last_frame_at=_t(0),
            now=_t(5.0),
            stale_after_s=2.0,
            offline_after_s=30.0,
        )[0]
        == "stale"
    )
    assert (
        source_status(
            enabled=True,
            last_frame_at=_t(0),
            now=_t(31.0),
            stale_after_s=2.0,
            offline_after_s=30.0,
        )[0]
        == "offline"
    )


def test_disabled_source_overrides_frame_freshness():
    status, age = source_status(
        enabled=False,
        last_frame_at=_t(0),
        now=_t(1.0),
        stale_after_s=2.0,
        offline_after_s=30.0,
    )

    assert status == "disabled"
    assert age is None


def test_tracker_records_frames_and_events_with_fake_time():
    tracker = InMemorySourceHealthTracker()

    tracker.record_frame("tb3_1_picam", at=_t(0))
    tracker.record_frame("tb3_1_picam", at=_t(1))
    tracker.record_event(
        {
            "source": "tb3_1_picam",
            "timestamp": _t(1.5).isoformat(),
            "event_id": "evt-1",
            "event_kind": "CONFIRMED",
            "marker_id": "ARUCO_4X4_50_7",
        }
    )

    snapshot = tracker.snapshot(
        "tb3_1_picam",
        now=_t(2),
        stale_after_s=2.0,
        offline_after_s=30.0,
    )

    assert snapshot.status == "online"
    assert snapshot.frame_count == 2
    assert snapshot.event_count == 1
    assert snapshot.last_frame_at == _t(1).isoformat()
    assert snapshot.last_event_at == _t(1.5).isoformat()
    assert snapshot.last_event_id == "evt-1"
    assert snapshot.last_event_kind == "CONFIRMED"
    assert snapshot.last_marker_id == "ARUCO_4X4_50_7"
    assert snapshot.last_frame_age_s == 1.0


def test_tracker_summary_counts_configured_sources():
    tracker = InMemorySourceHealthTracker()
    tracker.record_frame("tb3_1_picam", at=_t(0))
    tracker.record_frame("tb3_2_picam", at=_t(-10))
    tracker.set_enabled("global_cam_01", False)

    summary = tracker.summary(
        ["global_cam_01", "tb3_1_picam", "tb3_2_picam", "unseen_cam"],
        now=_t(1),
        stale_after_s=2.0,
        offline_after_s=30.0,
    )

    assert summary == {
        "configured": 4,
        "online": 1,
        "stale": 1,
        "disabled": 1,
        "offline": 1,
    }
