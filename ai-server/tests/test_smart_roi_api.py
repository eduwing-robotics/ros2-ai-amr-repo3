from __future__ import annotations

import json

from api_test_helpers import DetectionBox, client, cv2, get_settings, main_module, np


def _jpg_bytes(image: np.ndarray) -> bytes:
    ok, buffer = cv2.imencode(".jpg", image)
    assert ok
    return buffer.tobytes()


def test_global_cam_process_generates_lift_roi_overlay_view():
    main_module.store.reset()
    main_module.source_health.reset()
    main_module.metrics.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()

    image = np.full((720, 1280, 3), 210, dtype=np.uint8)
    image[280:420, 500:780] = 45

    response = client.post(
        "/api/v1/vision/frame/process",
        data={"source": "global_cam_01", "force": "true"},
        files={"image": ("gopro.jpg", _jpg_bytes(image), "image/jpeg")},
    )

    assert response.status_code == 200
    latest = client.get(
        "/api/v1/vision/overlay/latest",
        params={"source": "global_cam_01", "view": "lift_roi"},
    )
    assert latest.status_code == 200
    overlay = latest.json()["overlay"]
    assert overlay["view"] == "lift_roi"
    assert overlay["frame_seq"] == response.json()["frame_seq"]
    assert overlay["image"]["width"] < 1280
    assert overlay["image"]["height"] < 720

    image_response = client.get(
        "/api/v1/vision/overlay/latest/image",
        params={"source": "global_cam_01", "view": "lift_roi"},
    )
    assert image_response.status_code == 200
    assert image_response.content.startswith(b"\xff\xd8")


def test_global_cam_smart_roi_crop_uses_source_specific_segment_config(monkeypatch):
    main_module.store.reset()
    main_module.source_health.reset()
    main_module.metrics.reset()
    main_module.frame_store.reset()
    main_module.overlay_cache.reset()
    with main_module._overlay_images_lock:
        main_module._overlay_images.clear()
    main_module._parse_vision_model_class_map.cache_clear()
    main_module._parse_vision_model_source_config.cache_clear()

    settings = get_settings()
    monkeypatch.setattr(settings, "vision_model_worker_enabled", True)
    monkeypatch.setattr(settings, "vision_model_path", "fallback-picam-det.pt")
    monkeypatch.setattr(settings, "vision_model_task", "detect")
    monkeypatch.setattr(settings, "vision_model_imgsz", 320)
    monkeypatch.setattr(settings, "vision_model_class_map_json", '{"person":"person"}')
    monkeypatch.setattr(
        settings,
        "vision_model_source_config_json",
        json.dumps(
            {
                "global_cam_01": {
                    "model_path": "global-pallet-seg.pt",
                    "task": "segment",
                    "imgsz": 640,
                    "class_map": {"pallet": "pallet"},
                }
            }
        ),
    )
    factory_calls = []
    detect_shapes = []

    class FakeGlobalSegmenter:
        detector_name = "fake-global-pallet-seg"

        def detect(self, image):
            detect_shapes.append(image.shape[:2])
            return (
                DetectionBox(
                    class_name="pallet",
                    bbox_xyxy=(10.0, 10.0, 120.0, 80.0),
                    confidence=0.86,
                    detector=self.detector_name,
                ),
            )

    def fake_model_factory(**kwargs):
        factory_calls.append(kwargs)
        return FakeGlobalSegmenter()

    monkeypatch.setattr(main_module, "_get_lift_roi_segmenter", fake_model_factory)

    image = np.full((720, 1280, 3), 210, dtype=np.uint8)
    image[280:420, 500:780] = 45

    response = client.post(
        "/api/v1/vision/frame/process",
        data={"source": "global_cam_01", "force": "true"},
        files={"image": ("gopro.jpg", _jpg_bytes(image), "image/jpeg")},
    )

    assert response.status_code == 200
    assert len(factory_calls) >= 2
    assert any(height < 720 and width < 1280 for height, width in detect_shapes)
    assert all(call["model_path"] == "global-pallet-seg.pt" for call in factory_calls)
    assert all(call["task"] == "segment" for call in factory_calls)
    assert all(call["image_size"] == 640 for call in factory_calls)
