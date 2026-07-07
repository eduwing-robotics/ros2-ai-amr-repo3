from __future__ import annotations

import importlib.util
import sys
from argparse import Namespace
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "vision" / "run_latest_frame_compositor.py"


def load_module(name: str = "run_latest_frame_compositor_for_test"):
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class FakePublisher:
    def __init__(self, **kwargs):
        self.width = kwargs["width"]
        self.height = kwargs["height"]
        self.writes = 0

    def write(self, frame):
        self.writes += 1

    def close(self):
        pass


def args(
    tmp_path: Path, *, max_frames: int = 1, stale_overlay_after_ms: float = 1500.0
) -> Namespace:
    return Namespace(
        source="tb3_1_picam",
        view="full",
        ai_server_url="http://127.0.0.1:8100",
        frame_url="http://frame",
        events_url="http://events",
        events_limit=20,
        rtsp_url="rtsp://127.0.0.1:18554/tb3_1_picam_full",
        mediamtx_rtsp_port="18554",
        target_fps=1000.0,
        ai_fps=1000000.0,
        metrics_dir=str(tmp_path),
        timeout=0.01,
        stale_overlay_after_ms=stale_overlay_after_ms,
        bitrate="100k",
        bufsize="100k",
        gop=15,
        encoder="libx264",
        preset="ultrafast",
        ffmpeg_bin="ffmpeg",
        max_frames=max_frames,
    )


def overlay_payload(frame_seq: int, events: list[dict]) -> dict:
    return {
        "requested_source": "tb3_1_picam",
        "requested_view": "full",
        "overlay": {"frame_seq": frame_seq, "event_count": len(events)},
        "events": events,
    }


def event(frame_seq: int, *, bbox=(1, 2, 3, 4), class_name="person") -> dict:
    return {
        "class_name": class_name,
        "bbox_xyxy": list(bbox),
        "metadata": {"frame_seq": frame_seq},
    }


def test_latest_frame_compositor_rejects_malformed_events_without_crashing(monkeypatch, tmp_path):
    module = load_module("run_latest_frame_compositor_malformed_test")
    rendered = []

    monkeypatch.setattr(module, "RawVideoRtspPublisher", FakePublisher)
    monkeypatch.setattr(module, "read_json", lambda *a, **k: (200, {"events": [1]}, None))
    monkeypatch.setattr(module, "read_image", lambda *a, **k: np.zeros((12, 16, 3), dtype=np.uint8))

    def fake_render(frame, *, source, view, frame_seq, events, stale):
        rendered.append({"events": list(events), "stale": stale})
        return frame

    monkeypatch.setattr(module, "render_burned_overlay_bgr", fake_render)

    assert module.run(args(tmp_path)) == 0
    assert rendered == [{"events": [], "stale": True}]


def test_latest_frame_compositor_rejects_malformed_bboxes_without_fresh_update(
    monkeypatch, tmp_path
):
    module = load_module("run_latest_frame_compositor_malformed_bbox_test")
    rendered = []

    monkeypatch.setattr(module, "RawVideoRtspPublisher", FakePublisher)
    malformed_event = {
        "class_name": "person",
        "bbox_xyxy": [0, 0, float("inf"), 1],
        "metadata": {"frame_seq": 1},
    }
    monkeypatch.setattr(
        module,
        "read_json",
        lambda *a, **k: (200, overlay_payload(1, [malformed_event]), None),
    )
    monkeypatch.setattr(module, "read_image", lambda *a, **k: np.zeros((12, 16, 3), dtype=np.uint8))

    def fake_render(frame, *, source, view, frame_seq, events, stale):
        rendered.append({"events": list(events), "stale": stale})
        return frame

    monkeypatch.setattr(module, "render_burned_overlay_bgr", fake_render)

    assert module.run(args(tmp_path)) == 0
    assert rendered == [{"events": [], "stale": True}]


def test_overlay_bound_events_filters_to_latest_overlay_frame_seq():
    module = load_module("run_latest_frame_compositor_frame_bound_helper_test")
    current = event(42, bbox=(1, 2, 5, 6))
    old = event(41, bbox=(10, 10, 20, 20))

    assert module.overlay_bound_events(
        200,
        overlay_payload(42, [old, current]),
        None,
        source="tb3_1_picam",
        view="full",
    ) == [current]


def test_overlay_bound_events_rejects_unbound_detection_history_payload():
    module = load_module("run_latest_frame_compositor_unbound_helper_test")

    assert (
        module.overlay_bound_events(
            200,
            {"events": [event(42)]},
            None,
            source="tb3_1_picam",
            view="full",
        )
        is None
    )


def test_latest_frame_compositor_empty_current_overlay_clears_previous_events(
    monkeypatch, tmp_path
):
    module = load_module("run_latest_frame_compositor_empty_clears_test")
    rendered = []
    responses = iter(
        [
            (200, overlay_payload(10, [event(10)]), None),
            (200, overlay_payload(11, []), None),
        ]
    )
    ticks = iter([0.0, 0.01, 0.02, 0.03, 0.04, 0.05, 0.06, 0.07])

    monkeypatch.setattr(module, "RawVideoRtspPublisher", FakePublisher)
    monkeypatch.setattr(module, "read_json", lambda *a, **k: next(responses))
    monkeypatch.setattr(module, "read_image", lambda *a, **k: np.zeros((12, 16, 3), dtype=np.uint8))
    monkeypatch.setattr(module.time, "monotonic", lambda: next(ticks))

    def fake_render(frame, *, source, view, frame_seq, events, stale):
        rendered.append({"events": list(events), "stale": stale})
        return frame

    monkeypatch.setattr(module, "render_burned_overlay_bgr", fake_render)

    assert module.run(args(tmp_path, max_frames=2, stale_overlay_after_ms=1500.0)) == 0
    assert rendered[0] == {"events": [event(10)], "stale": False}
    assert rendered[1] == {"events": [], "stale": False}


def test_events_for_render_clears_boxes_after_stale_threshold():
    module = load_module("run_latest_frame_compositor_stale_helper_test")

    draw_events, stale = module.events_for_render(
        [event(10)],
        last_event_update_s=1.0,
        now_s=3.0,
        stale_overlay_after_ms=1500.0,
    )

    assert draw_events == []
    assert stale is True
