from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from app.model_adapters import UltralyticsSegmenterAdapter, VisionModelConfig
from app.vision_interfaces import DetectionBox, InstanceMask


class FakeYOLO:
    def __init__(self, model_path: str, *, task: str) -> None:
        self.model_path = model_path
        self.task = task

    def predict(self, image, **kwargs):
        assert image.shape == (20, 20, 3)
        assert kwargs["conf"] == 0.4
        mask = np.zeros((10, 10), dtype=np.uint8)
        mask[2:8, 2:8] = 1
        return [
            SimpleNamespace(
                boxes=SimpleNamespace(
                    xyxy=np.asarray([[4.0, 4.0, 16.0, 16.0]]),
                    conf=np.asarray([0.91]),
                    cls=np.asarray([0.0]),
                    id=None,
                ),
                masks=SimpleNamespace(data=np.asarray([mask])),
                names={0: "box"},
                orig_shape=(20, 20),
            )
        ]


class FakeDetectOnlyYOLO(FakeYOLO):
    def predict(self, image, **kwargs):
        return [
            SimpleNamespace(
                boxes=SimpleNamespace(
                    xyxy=np.asarray([[1.0, 2.0, 10.0, 12.0]]),
                    conf=np.asarray([0.7]),
                    cls=np.asarray([1.0]),
                    id=np.asarray([42.0]),
                ),
                masks=None,
                names={1: "pallet"},
                orig_shape=(20, 20),
            )
        ]


def test_ultralytics_segmenter_adapter_prefers_instance_masks(monkeypatch):
    monkeypatch.setitem(__import__("sys").modules, "ultralytics", SimpleNamespace(YOLO=FakeYOLO))

    adapter = UltralyticsSegmenterAdapter(
        VisionModelConfig(
            model_path="custom-seg.pt",
            task="segment",
            confidence=0.4,
            iou=0.5,
            image_size=320,
            device="cpu",
        )
    )

    result = tuple(adapter.detect(np.zeros((20, 20, 3), dtype=np.uint8)))

    assert len(result) == 1
    assert isinstance(result[0], InstanceMask)
    assert result[0].class_name == "box"
    assert result[0].confidence == 0.91
    assert result[0].mask.shape == (20, 20)
    assert result[0].mask.sum() > 0


def test_ultralytics_adapter_falls_back_to_bbox_when_masks_are_absent(monkeypatch):
    monkeypatch.setitem(
        __import__("sys").modules,
        "ultralytics",
        SimpleNamespace(YOLO=FakeDetectOnlyYOLO),
    )

    adapter = UltralyticsSegmenterAdapter(
        VisionModelConfig(model_path="custom-det.pt", task="detect")
    )

    result = tuple(adapter.detect(np.zeros((20, 20, 3), dtype=np.uint8)))

    assert len(result) == 1
    assert isinstance(result[0], DetectionBox)
    assert result[0].class_name == "pallet"
    assert result[0].track_id == 42


class FakeBottleYOLO(FakeYOLO):
    def predict(self, image, **kwargs):
        return [
            SimpleNamespace(
                boxes=SimpleNamespace(
                    xyxy=np.asarray([[1.0, 2.0, 10.0, 12.0], [3.0, 4.0, 14.0, 18.0]]),
                    conf=np.asarray([0.8, 0.6]),
                    cls=np.asarray([0.0, 1.0]),
                    id=None,
                ),
                masks=None,
                names={0: "bottle", 1: "chair"},
                orig_shape=(20, 20),
            )
        ]


def test_ultralytics_adapter_normalizes_pretrained_coco_classes(monkeypatch):
    monkeypatch.setitem(
        __import__("sys").modules,
        "ultralytics",
        SimpleNamespace(YOLO=FakeBottleYOLO),
    )

    adapter = UltralyticsSegmenterAdapter(
        VisionModelConfig(
            model_path="yolov8n.pt",
            task="detect",
            class_map={"bottle": "box", "person": "person"},
            unmapped_class="unknown",
        )
    )

    result = tuple(adapter.detect(np.zeros((20, 20, 3), dtype=np.uint8)))

    assert [item.class_name for item in result] == ["box", "unknown"]
