import cv2
import numpy as np

from app import overlay as overlay_module
from app.frame_store import LatestFrameStore
from app.overlay import render_overlay


def test_latest_frame_store_drops_old_frames_per_source():
    store = LatestFrameStore()
    image = np.zeros((20, 30, 3), dtype=np.uint8)

    first = store.put_decoded(source="tb3_1_picam", image_bgr=image)
    second = store.put_decoded(source="tb3_1_picam", image_bgr=image)

    assert first.frame_seq == 1
    assert second.frame_seq == 2
    assert store.latest("tb3_1_picam") == second
    assert store.stats()["sources_with_frames"] == 1


def test_overlay_renderer_draws_marker_bbox_and_metadata():
    store = LatestFrameStore()
    image = np.zeros((120, 160, 3), dtype=np.uint8)
    frame = store.put_decoded(source="tb3_1_picam", image_bgr=image)
    event = {
        "timestamp": "2026-06-15T09:00:00+09:00",
        "class_name": "aruco_marker",
        "marker_id": "ARUCO_4X4_50_7",
        "confidence": 1.0,
        "bbox_xyxy": [20, 20, 80, 80],
        "metadata": {"latency_ms": 3.5},
    }

    overlay = render_overlay(frame, events=[event])

    decoded = cv2.imdecode(np.frombuffer(overlay.jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    assert overlay.metadata()["source"] == "tb3_1_picam"
    assert overlay.metadata()["view"] == "full"
    assert overlay.metadata()["frame_seq"] == 1
    assert overlay.metadata()["event_count"] == 1
    assert overlay.metadata()["evidence_timestamp"] == event["timestamp"]
    assert overlay.metadata()["latency_ms"] == 3.5
    assert overlay.metadata()["visual_state"] == "fresh"


def test_overlay_renderer_shortens_aruco_marker_visual_labels(monkeypatch):
    store = LatestFrameStore()
    image = np.zeros((120, 160, 3), dtype=np.uint8)
    frame = store.put_decoded(source="tb3_1_picam", image_bgr=image)
    event = {
        "timestamp": "2026-06-15T09:00:00+09:00",
        "class_name": "aruco_marker",
        "marker_id": "ARUCO_4X4_50_12",
        "confidence": 1.0,
        "bbox_xyxy": [20, 20, 80, 80],
        "metadata": {"latency_ms": 3.5},
    }
    captured_labels = []

    def capture_label(image, text, x, y, color):
        captured_labels.append(text)

    monkeypatch.setattr(overlay_module, "_draw_label", capture_label)

    render_overlay(frame, events=[event])

    assert captured_labels[0] == "A12 1.00"
    assert "ARUCO_4X4_50_12" not in captured_labels[0]


def test_stale_overlay_has_unmistakable_visual_warning_band():
    store = LatestFrameStore()
    image = np.zeros((120, 160, 3), dtype=np.uint8)
    frame = store.put_decoded(source="tb3_1_picam", image_bgr=image)
    event = {
        "timestamp": "2026-06-15T09:00:00+09:00",
        "class_name": "aruco_marker",
        "marker_id": "ARUCO_4X4_50_7",
        "confidence": 1.0,
        "bbox_xyxy": [20, 30, 80, 90],
        "metadata": {"latency_ms": 3.5},
    }

    fresh = render_overlay(frame, events=[event], stale=False)
    stale = render_overlay(frame, events=[event], stale=True)

    fresh_decoded = cv2.imdecode(np.frombuffer(fresh.jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    stale_decoded = cv2.imdecode(np.frombuffer(stale.jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert fresh_decoded is not None
    assert stale_decoded is not None
    assert stale.metadata()["stale"] is True
    assert stale.metadata()["visual_state"] == "stale"

    # BGR amber stale header: high red+green, low blue.  Sample away from text.
    stale_header_pixel = stale_decoded[3, 150]
    fresh_header_pixel = fresh_decoded[3, 150]
    assert int(stale_header_pixel[2]) > 180
    assert int(stale_header_pixel[1]) > 100
    assert int(stale_header_pixel[0]) < 80
    assert np.linalg.norm(stale_header_pixel.astype(float) - fresh_header_pixel.astype(float)) > 100


def test_overlay_banner_labels_live_stream_as_realtime(monkeypatch):
    store = LatestFrameStore()
    image = np.zeros((120, 320, 3), dtype=np.uint8)
    frame = store.put_decoded(source="tb3_1_picam", image_bgr=image)
    captured_labels = []

    def capture_label(image, text, x, y, color):
        captured_labels.append(text)

    monkeypatch.setattr(overlay_module, "_draw_label", capture_label)
    monkeypatch.setattr(overlay_module, "_local_clock_label", lambda: "12:34:56")

    render_overlay(frame, events=[])

    assert captured_labels[-1] == "tb3_1_picam time=12:34:56 events=0"
    assert "frame=" not in captured_labels[-1]


def test_overlay_renderer_draws_map_roi_polygon_with_distinct_color():
    store = LatestFrameStore()
    image = np.zeros((120, 160, 3), dtype=np.uint8)
    frame = store.put_decoded(source="global_cam_01", image_bgr=image)
    event = {
        "timestamp": "2026-07-02T09:00:00+09:00",
        "class_name": "map_roi",
        "confidence": 1.0,
        "metadata": {
            "debug_overlay": True,
            "overlay_kind": "map_roi",
            "overlay_polygon_xy": [[20, 20], [100, 20], [100, 80], [20, 80]],
            "overlay_color_bgr": [255, 255, 0],
            "overlay_label": "MAP ROI FRESH",
        },
    }

    overlay = render_overlay(frame, events=[event])

    decoded = cv2.imdecode(np.frombuffer(overlay.jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    assert overlay.metadata()["event_count"] == 1
    # BGR cyan line near the top polygon edge; allow JPEG compression.
    sample = decoded[20, 60]
    assert int(sample[0]) > 120
    assert int(sample[1]) > 120
    assert int(sample[2]) < 100


def test_overlay_renderer_suppresses_unknown_visual_boxes():
    store = LatestFrameStore()
    image = np.zeros((120, 160, 3), dtype=np.uint8)
    frame = store.put_decoded(source="global_cam_01", image_bgr=image)
    unknown_event = {
        "timestamp": "2026-07-02T09:00:00+09:00",
        "class_name": "unknown",
        "confidence": 0.72,
        "bbox_xyxy": [20, 20, 100, 80],
        "metadata": {"latency_ms": 3.5},
    }

    overlay = render_overlay(frame, events=[unknown_event])

    decoded = cv2.imdecode(np.frombuffer(overlay.jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    assert overlay.metadata()["event_count"] == 1
    # Unknown detections should remain in metadata counts but not draw a green
    # rectangle in the operator view.  Sample away from the clock banner.
    assert np.linalg.norm(decoded[20, 60].astype(float)) < 30


def test_overlay_renderer_uses_explicit_polygon_label_anchor(monkeypatch):
    store = LatestFrameStore()
    image = np.zeros((120, 160, 3), dtype=np.uint8)
    frame = store.put_decoded(source="global_cam_01", image_bgr=image)
    captured_labels = []

    def capture_label(image, text, x, y, color):
        captured_labels.append((text, x, y, color))

    monkeypatch.setattr(overlay_module, "_draw_label", capture_label)
    monkeypatch.setattr(overlay_module, "_local_clock_label", lambda: "12:34:56")
    event = {
        "timestamp": "2026-07-02T09:00:00+09:00",
        "class_name": "zone_roi",
        "confidence": 1.0,
        "metadata": {
            "overlay_polygon_xy": [[20, 20], [100, 20], [100, 80], [20, 80]],
            "overlay_color_bgr": [255, 0, 255],
            "overlay_label": "ZONE storage 1",
            "overlay_label_xy": [28, 44],
        },
    }

    render_overlay(frame, events=[event])

    assert captured_labels[0][:3] == ("ZONE storage 1", 28, 44)
