from __future__ import annotations

import json
from pathlib import Path

import numpy as np
from burned_overlay_compositor import (
    CompositorMetrics,
    MetricsWriter,
    RawVideoRtspPublisher,
    events_for_crop,
    letterbox_frame_and_events_bgr,
    letterbox_frame_bgr,
    render_burned_overlay_bgr,
)


def test_events_for_crop_translates_and_clips_bboxes() -> None:
    events = [
        {"class_name": "box", "confidence": 0.8, "bbox_xyxy": [10, 10, 50, 50]},
        {"class_name": "person", "confidence": 0.7, "bbox_xyxy": [90, 90, 120, 120]},
    ]

    cropped = events_for_crop(events, [20, 20, 100, 100])

    assert cropped == [
        {
            "class_name": "box",
            "confidence": 0.8,
            "bbox_xyxy": [0, 0, 30, 30],
            "metadata": {"crop_translated": True, "crop_bbox_xyxy": [20, 20, 100, 100]},
        },
        {
            "class_name": "person",
            "confidence": 0.7,
            "bbox_xyxy": [70, 70, 80, 80],
            "metadata": {"crop_translated": True, "crop_bbox_xyxy": [20, 20, 100, 100]},
        },
    ]


def test_render_burned_overlay_returns_bgr_pixels() -> None:
    frame = np.zeros((80, 120, 3), dtype=np.uint8)
    rendered = render_burned_overlay_bgr(
        frame,
        source="tb3_1_picam",
        view="full",
        frame_seq=1,
        events=[{"class_name": "person", "confidence": 0.9, "bbox_xyxy": [5, 5, 40, 40]}],
    )

    assert rendered.shape == frame.shape
    assert rendered.sum() > 0


def test_letterbox_frame_bgr_returns_fixed_even_canvas_without_distortion() -> None:
    frame = np.full((77, 151, 3), 255, dtype=np.uint8)

    letterboxed = letterbox_frame_bgr(frame, width=641, height=481)

    assert letterboxed.shape == (480, 640, 3)
    non_black = np.argwhere(letterboxed[:, :, 0] > 0)
    y_min, x_min = non_black.min(axis=0)
    y_max, x_max = non_black.max(axis=0)
    assert (x_max - x_min + 1) % 2 == 0
    assert (y_max - y_min + 1) % 2 == 0
    assert (x_max - x_min + 1) == 640
    assert (y_max - y_min + 1) < 480


def test_letterbox_frame_and_events_scales_1080p_to_720p_exactly() -> None:
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    events = [{"class_name": "box", "confidence": 0.9, "bbox_xyxy": [960, 540, 1440, 810]}]

    output, mapped = letterbox_frame_and_events_bgr(frame, events, width=1280, height=720)

    assert output.shape == (720, 1280, 3)
    assert mapped[0]["bbox_xyxy"] == [640, 360, 960, 540]
    assert mapped[0]["metadata"]["letterbox_translated"] is True
    assert mapped[0]["metadata"]["letterbox_output_size_px"] == {"width": 1280, "height": 720}


def test_letterbox_frame_and_events_scales_debug_overlay_polygon() -> None:
    frame = np.zeros((1080, 1920, 3), dtype=np.uint8)
    events = [
        {
            "class_name": "map_roi",
            "metadata": {
                "overlay_polygon_xy": [[0, 0], [1920, 0], [1920, 1080], [0, 1080]],
                "overlay_color_bgr": [255, 255, 0],
            },
        }
    ]

    output, mapped = letterbox_frame_and_events_bgr(frame, events, width=1280, height=720)

    assert output.shape == (720, 1280, 3)
    assert mapped == [
        {
            "class_name": "map_roi",
            "metadata": {
                "overlay_polygon_xy": [[0, 0], [1280, 0], [1280, 720], [0, 720]],
                "overlay_color_bgr": [255, 255, 0],
                "letterbox_translated": True,
                "letterbox_source_size_px": {"width": 1920, "height": 1080},
                "letterbox_output_size_px": {"width": 1280, "height": 720},
                "letterbox_scale": {"x": 1280 / 1920, "y": 720 / 1080},
                "letterbox_offset_px": {"x": 0, "y": 0},
            },
        }
    ]


def test_letterbox_frame_and_events_handles_non_16_9_offsets_and_clipping() -> None:
    frame = np.zeros((1000, 1000, 3), dtype=np.uint8)
    events = [
        {"class_name": "box", "confidence": 0.9, "bbox_xyxy": [250, 250, 750, 750]},
        {"class_name": "box", "confidence": 0.8, "bbox_xyxy": [-100, -100, 100, 100]},
        {"class_name": "box", "confidence": 0.7, "bbox_xyxy": [1200, 1200, 1300, 1300]},
    ]

    output, mapped = letterbox_frame_and_events_bgr(frame, events, width=1280, height=720)

    assert output.shape == (720, 1280, 3)
    assert mapped[0]["bbox_xyxy"] == [460, 180, 820, 540]
    assert mapped[0]["metadata"]["letterbox_offset_px"] == {"x": 280, "y": 0}
    assert mapped[1]["bbox_xyxy"] == [280, 0, 352, 72]
    assert len(mapped) == 2


def test_metrics_writer_uses_atomic_json_file(tmp_path: Path) -> None:
    metrics = CompositorMetrics(
        source="global_cam_01",
        view="full",
        path_id="global_cam_01_full",
        target_fps=30,
        ai_fps=5,
    )
    metrics.output_frames = 3
    target = tmp_path / "global_cam_01_full.json"

    MetricsWriter(target).write(metrics)

    payload = json.loads(target.read_text())
    assert payload["schema_version"] == "smartfactory-vision-compositor-metrics.v1"
    assert payload["source"] == "global_cam_01"
    assert payload["view"] == "full"
    assert payload["path_id"] == "global_cam_01_full"
    assert payload["updated_at_epoch_s"] > 0


def test_raw_video_rtsp_publisher_command_is_low_latency_h264() -> None:
    publisher = RawVideoRtspPublisher(
        rtsp_url="rtsp://127.0.0.1:18554/tb3_1_picam_full",
        width=640,
        height=480,
        fps=30,
        bitrate="1800k",
        bufsize="500k",
        gop=15,
    )

    command = publisher.command()

    assert command[: command.index("-i") + 2] == [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "warning",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "bgr24",
        "-s",
        "640x480",
        "-r",
        "30.0",
        "-i",
        "pipe:0",
    ]
    assert "-tune" in command
    assert "zerolatency" in command
    assert "keyint=15:min-keyint=15:scenecut=0" in command
    assert command[-1] == "rtsp://127.0.0.1:18554/tb3_1_picam_full"
