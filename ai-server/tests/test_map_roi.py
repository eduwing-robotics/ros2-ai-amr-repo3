from __future__ import annotations

import pytest
from api_test_helpers import aruco_png_bytes, client, get_settings, main_module

from app.detectors import MarkerDetection
from app.map_roi import (
    FRESH,
    LOCKED,
    STALE_USABLE,
    MapRoiConfig,
    MapRoiTracker,
    normalize_freeze_mode,
    parse_marker_ids,
    parse_normalized_polygon,
    snapshot_to_overlay_event,
)


@pytest.fixture(autouse=True)
def _clear_settings_cache_around_test():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _marker(marker_id: int, x: float, y: float) -> MarkerDetection:
    corners = (
        (x, y),
        (x + 10.0, y),
        (x + 10.0, y + 10.0),
        (x, y + 10.0),
    )
    return MarkerDetection(
        class_name="aruco_marker",
        marker_id=f"ARUCO_4X4_50_{marker_id}",
        bbox_xyxy=[x, y, x + 10.0, y + 10.0],
        corners_xy=corners,
    )


def test_parse_marker_ids_accepts_short_and_full_aruco_names() -> None:
    assert parse_marker_ids("11,ARUCO_4X4_50_12,11") == (
        "ARUCO_4X4_50_11",
        "ARUCO_4X4_50_12",
    )


def test_parse_normalized_polygon_accepts_semicolon_format() -> None:
    assert parse_normalized_polygon("0.1,0.2;0.8,0.2;0.7,0.9") == (
        (0.1, 0.2),
        (0.8, 0.2),
        (0.7, 0.9),
    )


def test_normalize_freeze_mode_accepts_any_and_all_only() -> None:
    assert normalize_freeze_mode("ANY") == "any"
    assert normalize_freeze_mode(" all ") == "all"
    with pytest.raises(ValueError):
        normalize_freeze_mode("either")


def test_map_roi_tracker_latches_first_marker_observation_and_translates_polygon() -> None:
    config = MapRoiConfig(
        enabled=True,
        source="global_cam_01",
        marker_ids=("ARUCO_4X4_50_11",),
        min_markers=1,
        stale_usable_s=30.0,
        polygon_normalized=((0.1, 0.1), (0.5, 0.1), (0.5, 0.5), (0.1, 0.5)),
    )
    tracker = MapRoiTracker()

    first = tracker.update(
        source="global_cam_01",
        detections=[_marker(11, 20.0, 30.0)],
        image_width=101,
        image_height=101,
        config=config,
        now_monotonic=10.0,
    )
    assert first is not None
    assert first.status == FRESH
    assert first.polygon_xy == ((10.0, 10.0), (50.0, 10.0), (50.0, 50.0), (10.0, 50.0))

    moved = tracker.update(
        source="global_cam_01",
        detections=[_marker(11, 25.0, 37.0)],
        image_width=101,
        image_height=101,
        config=config,
        now_monotonic=11.0,
    )
    assert moved is not None
    assert moved.status == FRESH
    assert moved.polygon_xy == ((15.0, 17.0), (55.0, 17.0), (55.0, 57.0), (15.0, 57.0))


def test_map_roi_tracker_freezes_once_preferred_marker_is_seen() -> None:
    config = MapRoiConfig(
        enabled=True,
        source="global_cam_01",
        marker_ids=("ARUCO_4X4_50_11", "ARUCO_4X4_50_12"),
        min_markers=1,
        stale_usable_s=30.0,
        polygon_normalized=((0.1, 0.1), (0.5, 0.1), (0.5, 0.5), (0.1, 0.5)),
        freeze_marker_ids=("ARUCO_4X4_50_12",),
    )
    tracker = MapRoiTracker()

    initial = tracker.update(
        source="global_cam_01",
        detections=[_marker(11, 20.0, 30.0)],
        image_width=101,
        image_height=101,
        config=config,
        now_monotonic=10.0,
    )
    assert initial is not None
    assert initial.status == FRESH

    locked = tracker.update(
        source="global_cam_01",
        detections=[_marker(12, 80.0, 90.0)],
        image_width=101,
        image_height=101,
        config=config,
        now_monotonic=11.0,
    )
    assert locked is not None
    assert locked.status == LOCKED
    assert locked.reason == "marker_freeze_latch"
    locked_polygon = locked.polygon_xy

    later = tracker.update(
        source="global_cam_01",
        detections=[_marker(11, 50.0, 60.0)],
        image_width=101,
        image_height=101,
        config=config,
        now_monotonic=20.0,
    )
    assert later is not None
    assert later.status == LOCKED
    assert later.reason == "marker_freeze_locked"
    assert later.polygon_xy == locked_polygon
    assert later.age_s == 9.0


def test_map_roi_tracker_freeze_all_uses_visible_markers_not_only_roi_markers() -> None:
    config = MapRoiConfig(
        enabled=True,
        source="global_cam_01",
        marker_ids=("ARUCO_4X4_50_11", "ARUCO_4X4_50_12"),
        min_markers=1,
        stale_usable_s=30.0,
        polygon_normalized=((0.1, 0.1), (0.5, 0.1), (0.5, 0.5), (0.1, 0.5)),
        freeze_marker_ids=("ARUCO_4X4_50_6", "ARUCO_4X4_50_12"),
        freeze_mode="all",
    )
    tracker = MapRoiTracker()

    first = tracker.update(
        source="global_cam_01",
        detections=[_marker(11, 20.0, 30.0), _marker(6, 40.0, 50.0)],
        image_width=101,
        image_height=101,
        config=config,
        now_monotonic=10.0,
    )
    assert first is not None
    assert first.status == FRESH

    no_lock = tracker.update(
        source="global_cam_01",
        detections=[_marker(12, 80.0, 90.0)],
        image_width=101,
        image_height=101,
        config=config,
        now_monotonic=11.0,
    )
    assert no_lock is not None
    assert no_lock.status == FRESH

    locked = tracker.update(
        source="global_cam_01",
        detections=[_marker(6, 42.0, 52.0), _marker(12, 81.0, 91.0)],
        image_width=101,
        image_height=101,
        config=config,
        now_monotonic=12.0,
    )
    assert locked is not None
    assert locked.status == LOCKED
    assert locked.reason == "marker_freeze_latch"
    assert locked.markers_used == ("ARUCO_4X4_50_12",)


def test_map_roi_tracker_keeps_latched_polygon_stale_then_expires() -> None:
    config = MapRoiConfig(
        enabled=True,
        source="global_cam_01",
        marker_ids=("ARUCO_4X4_50_11",),
        min_markers=1,
        stale_usable_s=2.0,
        polygon_normalized=((0.1, 0.1), (0.5, 0.1), (0.5, 0.5), (0.1, 0.5)),
    )
    tracker = MapRoiTracker()
    assert tracker.update(
        source="global_cam_01",
        detections=[_marker(11, 20.0, 30.0)],
        image_width=101,
        image_height=101,
        config=config,
        now_monotonic=10.0,
    )

    stale = tracker.update(
        source="global_cam_01",
        detections=[],
        image_width=101,
        image_height=101,
        config=config,
        now_monotonic=11.5,
    )
    assert stale is not None
    assert stale.status == STALE_USABLE
    assert stale.age_s == 1.5

    expired = tracker.update(
        source="global_cam_01",
        detections=[],
        image_width=101,
        image_height=101,
        config=config,
        now_monotonic=13.0,
    )
    assert expired is not None
    assert expired.status == "EXPIRED"
    assert snapshot_to_overlay_event(expired) is None


def test_stale_map_roi_overlay_keeps_cyan_color_to_avoid_live_flicker() -> None:
    config = MapRoiConfig(
        enabled=True,
        source="global_cam_01",
        marker_ids=("ARUCO_4X4_50_11",),
        min_markers=1,
        stale_usable_s=30.0,
        polygon_normalized=((0.1, 0.1), (0.5, 0.1), (0.5, 0.5), (0.1, 0.5)),
    )
    tracker = MapRoiTracker()
    assert tracker.update(
        source="global_cam_01",
        detections=[_marker(11, 20.0, 30.0)],
        image_width=101,
        image_height=101,
        config=config,
        now_monotonic=10.0,
    )
    stale = tracker.update(
        source="global_cam_01",
        detections=[],
        image_width=101,
        image_height=101,
        config=config,
        now_monotonic=12.0,
    )
    assert stale is not None
    assert stale.status == STALE_USABLE

    event = snapshot_to_overlay_event(stale)

    assert event is not None
    assert event["metadata"]["overlay_color_bgr"] == [255, 255, 0]
    assert "STALE_USABLE" in event["metadata"]["overlay_label"]


def test_snapshot_to_overlay_event_is_debug_only_polygon_metadata() -> None:
    config = MapRoiConfig(
        enabled=True,
        source="global_cam_01",
        marker_ids=("ARUCO_4X4_50_11",),
        min_markers=1,
        polygon_normalized=((0.1, 0.1), (0.5, 0.1), (0.5, 0.5)),
    )
    tracker = MapRoiTracker()
    snapshot = tracker.update(
        source="global_cam_01",
        detections=[_marker(11, 20.0, 30.0)],
        image_width=101,
        image_height=101,
        config=config,
        now_monotonic=10.0,
    )
    assert snapshot is not None

    event = snapshot_to_overlay_event(
        snapshot, label="LAB MAP", frame_seq=7, timestamp="2026-07-02T00:00:00+09:00"
    )

    assert event is not None
    assert event["class_name"] == "map_roi"
    assert "bbox_xyxy" not in event
    assert event["metadata"]["debug_overlay"] is True
    assert event["metadata"]["overlay_kind"] == "map_roi"
    assert event["metadata"]["frame_seq"] == 7


def test_map_roi_overlay_does_not_pollute_main_facing_detection_store(monkeypatch) -> None:
    context = main_module._runtime_context()
    context.store.reset()
    context.source_health.reset()
    context.frame_store.reset()
    context.overlay_cache.reset()
    with context.overlay_images_lock:
        context.overlay_images.clear()
    with context.map_roi_trackers_lock:
        context.map_roi_trackers.clear()

    monkeypatch.setenv("VISION_MAP_ROI_ENABLED", "true")
    monkeypatch.setenv("VISION_MAP_ROI_SOURCE", "global_cam_01")
    monkeypatch.setenv("VISION_MAP_ROI_MARKER_IDS", "7")
    monkeypatch.setenv("VISION_MAP_ROI_POLYGON_NORMALIZED", "0.1,0.1;0.8,0.1;0.8,0.8;0.1,0.8")
    response = client.post(
        "/api/v1/vision/synthetic/frame",
        json={"source": "global_cam_01", "marker_id": 7},
    )

    assert response.status_code == 200
    overlay = context.overlay_cache.latest("global_cam_01")
    assert overlay is not None
    assert overlay["event_count"] == 2
    events = context.store.latest(source="global_cam_01", limit=10)
    assert len(events) == 1
    assert events[0]["class_name"] == "aruco_marker"
    metadata = client.get(
        "/api/v1/vision/overlay/metadata",
        params={"source": "global_cam_01", "limit": 10},
    )
    assert metadata.status_code == 200
    assert [event["class_name"] for event in metadata.json()["events"]] == [
        "aruco_marker",
        "map_roi",
    ]

    get_settings.cache_clear()


def test_frame_process_returns_overlay_events_for_webrtc_adapter_without_storing_them(
    monkeypatch,
) -> None:
    context = main_module._runtime_context()
    context.store.reset()
    context.source_health.reset()
    context.frame_store.reset()
    context.overlay_cache.reset()
    with context.overlay_images_lock:
        context.overlay_images.clear()
    with context.map_roi_trackers_lock:
        context.map_roi_trackers.clear()

    monkeypatch.setenv("VISION_MAP_ROI_ENABLED", "true")
    monkeypatch.setenv("VISION_MAP_ROI_SOURCE", "global_cam_01")
    monkeypatch.setenv("VISION_MAP_ROI_MARKER_IDS", "7")
    monkeypatch.setenv("VISION_MAP_ROI_POLYGON_NORMALIZED", "0.1,0.1;0.8,0.1;0.8,0.8;0.1,0.8")

    response = client.post(
        "/api/v1/vision/frame/process",
        data={"source": "global_cam_01", "force": "true"},
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["event_count"] == 1
    assert body["overlay_event_count"] == 2
    assert [event["class_name"] for event in body["events"]] == ["aruco_marker"]
    assert [event["class_name"] for event in body["overlay_events"]] == [
        "aruco_marker",
        "map_roi",
    ]
    assert len(context.store.latest(source="global_cam_01", limit=10)) == 1
