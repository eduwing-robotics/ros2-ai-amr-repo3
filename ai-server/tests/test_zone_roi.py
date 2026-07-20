from __future__ import annotations

import json
from pathlib import Path

import pytest
from api_test_helpers import aruco_png_bytes, client, get_settings, main_module

from app.config import REPO_ROOT
from app.zone_roi import (
    ZoneRoi,
    find_zone_by_id,
    load_zone_roi_config,
    load_zone_roi_config_cached,
    zone_contains_pixel,
    zone_roi_overlay_events,
)


@pytest.fixture(autouse=True)
def _clear_settings_and_zone_cache():
    get_settings.cache_clear()
    load_zone_roi_config_cached.cache_clear()
    yield
    get_settings.cache_clear()
    load_zone_roi_config_cached.cache_clear()


def _zone_config(tmp_path):
    path = tmp_path / "zones.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": "smartfactory-zone-roi-draft.v1",
                "source": "global_cam_01",
                "coordinate_space": "normalized_full_frame_xy",
                "zones": [
                    {
                        "zone_id": "inbound_static_item_zone",
                        "label": "inbound",
                        "role": "allowed_static_item_zone",
                        "natural_item_location": True,
                        "reference_markers": [0, 1],
                        "polygon_normalized": [[0.1, 0.1], [0.4, 0.1], [0.4, 0.4], [0.1, 0.4]],
                    },
                    {
                        "zone_id": "charging_reference_zone",
                        "label": "charging",
                        "role": "robot_charging_reference_zone",
                        "natural_item_location": False,
                        "reference_markers": [3, 4],
                        "polygon_normalized": [[0.5, 0.1], [0.8, 0.1], [0.8, 0.4], [0.5, 0.4]],
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def test_zone_roi_config_builds_visual_overlay_events(tmp_path) -> None:
    config = load_zone_roi_config(_zone_config(tmp_path))

    events = zone_roi_overlay_events(
        config,
        source="global_cam_01",
        image_width=200,
        image_height=100,
        frame_seq=42,
        timestamp="2026-07-03T00:00:00+09:00",
    )

    assert [event["class_name"] for event in events] == ["zone_roi", "zone_roi"]
    assert events[0]["metadata"]["overlay_kind"] == "zone_roi"
    assert events[0]["metadata"]["overlay_polygon_xy"] == [
        [20.0, 10.0],
        [80.0, 10.0],
        [80.0, 40.0],
        [20.0, 40.0],
    ]
    assert events[0]["metadata"]["overlay_color_bgr"] == [255, 0, 255]
    assert events[0]["metadata"]["overlay_label"] == "inbound"
    assert events[0]["metadata"]["overlay_label_xy"] == [28.0, 34.0]
    assert events[0]["metadata"]["overlay_fill_polygon_xy"] == [
        [20.0, 10.0],
        [80.0, 10.0],
        [80.0, 40.0],
        [20.0, 40.0],
    ]
    assert events[0]["metadata"]["overlay_fill_alpha"] == pytest.approx(0.12)
    assert events[1]["metadata"]["overlay_color_bgr"] == [0, 165, 255]
    assert events[1]["metadata"]["overlay_label"] == "REF charging"
    assert "overlay_fill_polygon_xy" not in events[1]["metadata"]



def test_zone_roi_config_accepts_explicit_overlay_label_anchor(tmp_path) -> None:
    path = _zone_config(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["zones"][0]["overlay_label_anchor_normalized"] = [0.25, 0.3]
    path.write_text(json.dumps(data), encoding="utf-8")

    config = load_zone_roi_config(path)
    events = zone_roi_overlay_events(
        config,
        source="global_cam_01",
        image_width=200,
        image_height=100,
    )

    assert events[0]["metadata"]["overlay_label_xy"] == [50.0, 30.0]


def test_zone_roi_config_rejects_invalid_overlay_label_anchor(tmp_path) -> None:
    path = _zone_config(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["zones"][0]["overlay_label_anchor_normalized"] = [1.2, 0.3]
    path.write_text(json.dumps(data), encoding="utf-8")

    with pytest.raises(ValueError, match="overlay_label_anchor_normalized"):
        load_zone_roi_config(path)

def test_zone_roi_draft_uses_canonical_location_labels_and_aliases() -> None:
    config = load_zone_roi_config(
        REPO_ROOT / "config" / "vision" / "zone_rois" / "global_cam_01_lab_draft.json"
    )

    expected_labels = {
        "INBOUND_01": "inbound 1",
        "INBOUND_02": "inbound 2",
        "OUTBOUND_01": "outbound 1",
        "OUTBOUND_02": "outbound 2",
        "STORAGE_S1": "S1",
        "STORAGE_S2": "S2",
        "STORAGE_S3": "S3",
        "STORAGE_S4": "S4",
    }
    labels = {zone.zone_id: zone.label for zone in config.zones if zone.natural_item_location}

    assert labels == expected_labels
    assert config.location_aliases == {zone_id: zone_id for zone_id in expected_labels}


def test_zone_roi_draft_separates_visible_location_bounds_from_evidence_masks() -> None:
    path = REPO_ROOT / "config" / "vision" / "zone_rois" / "global_cam_01_lab_draft.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    config = load_zone_roi_config(path)
    zones = {zone.zone_id: zone for zone in config.zones}
    map_roi = ZoneRoi(
        zone_id="map_roi",
        label="map roi",
        role="diagnostic",
        natural_item_location=False,
        polygon_normalized=tuple(
            (float(x), float(y)) for x, y in data["map_roi"]["polygon_normalized"]
        ),
    )

    expected_markers = {
        "INBOUND_01": (0,),
        "INBOUND_02": (1,),
        "OUTBOUND_01": (5,),
        "OUTBOUND_02": (6,),
        "STORAGE_S1": (7,),
        "STORAGE_S2": (8,),
        "STORAGE_S3": (10,),
        "STORAGE_S4": (9,),
    }
    assert {zone_id: zones[zone_id].reference_markers for zone_id in expected_markers} == expected_markers

    for zone in zones.values():
        for x, y in zone.polygon_normalized:
            assert zone_contains_pixel(
                map_roi, x=x * 1920, y=y * 1080, image_width=1920, image_height=1080
            )

    assert zones["OUTBOUND_02"].polygon_normalized[2][1] == pytest.approx(
        zones["OUTBOUND_01"].polygon_normalized[1][1]
    )
    assert zones["INBOUND_02"].polygon_normalized[2][1] == pytest.approx(
        zones["INBOUND_01"].polygon_normalized[1][1]
    )
    assert zones["STORAGE_S4"].polygon_normalized[1][0] == pytest.approx(
        zones["STORAGE_S3"].polygon_normalized[0][0]
    )
    assert zones["STORAGE_S2"].polygon_normalized[1][0] == pytest.approx(
        zones["STORAGE_S1"].polygon_normalized[0][0]
    )

    # Inbound/outbound evidence is the straight aisle-side carried-item strip,
    # not the full perspective-shaped location outline.
    assert zone_contains_pixel(
        zones["OUTBOUND_02"], x=0.39 * 1920, y=0.10 * 1080, image_width=1920, image_height=1080
    )
    assert not zone_contains_pixel(
        zones["OUTBOUND_02"], x=0.28 * 1920, y=0.10 * 1080, image_width=1920, image_height=1080
    )
    assert zone_contains_pixel(
        zones["INBOUND_01"], x=0.40 * 1920, y=0.84 * 1080, image_width=1920, image_height=1080
    )
    assert not zone_contains_pixel(
        zones["INBOUND_01"], x=0.32 * 1920, y=0.84 * 1080, image_width=1920, image_height=1080
    )

    # Storage outlines remain full-height for the operator. Evidence uses the
    # carried-item-side 75% away from the rack, independent of lift floor.
    assert zone_contains_pixel(
        zones["STORAGE_S4"], x=0.52 * 1920, y=0.34 * 1080, image_width=1920, image_height=1080
    )
    assert not zone_contains_pixel(
        zones["STORAGE_S4"], x=0.52 * 1920, y=0.46 * 1080, image_width=1920, image_height=1080
    )
    assert zone_contains_pixel(
        zones["STORAGE_S2"], x=0.52 * 1920, y=0.82 * 1080, image_width=1920, image_height=1080
    )
    assert not zone_contains_pixel(
        zones["STORAGE_S2"], x=0.52 * 1920, y=0.67 * 1080, image_width=1920, image_height=1080
    )

    overlay = zone_roi_overlay_events(
        config,
        source="global_cam_01",
        image_width=1920,
        image_height=1080,
    )
    s4_overlay = next(event for event in overlay if event["metadata"]["zone_roi"]["zone_id"] == "STORAGE_S4")
    assert s4_overlay["metadata"]["overlay_label"] == "S4"
    assert s4_overlay["metadata"]["overlay_fill_polygon_xy"] == [
        [0.485 * 1920, 0.290677 * 1080],
        [0.5625 * 1920, 0.290677 * 1080],
        [0.5625 * 1920, 0.451927 * 1080],
        [0.485 * 1920, 0.451927 * 1080],
    ]
    assert "evidence_polygon_normalized" not in s4_overlay["metadata"]["zone_roi"]


def test_zone_roi_rejects_location_aliases_pointing_to_unknown_zones(tmp_path) -> None:
    path = tmp_path / "bad-zones.json"
    path.write_text(
        json.dumps(
            {
                "source": "global_cam_01",
                "coordinate_space": "normalized_full_frame_xy",
                "location_aliases": {"inbound": "missing_zone"},
                "zones": [
                    {
                        "zone_id": "inbound_static_item_zone",
                        "label": "inbound",
                        "role": "allowed_static_item_zone",
                        "natural_item_location": True,
                        "polygon_normalized": [[0.1, 0.1], [0.4, 0.1], [0.4, 0.4], [0.1, 0.4]],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="references unknown zone_id"):
        load_zone_roi_config(path)


def test_zone_contains_pixel_treats_polygon_edges_as_inside(tmp_path) -> None:
    config = load_zone_roi_config(_zone_config(tmp_path))
    zone = find_zone_by_id(config, "inbound_static_item_zone")
    assert zone is not None

    assert zone_contains_pixel(zone, x=20, y=20, image_width=200, image_height=200) is True
    assert zone_contains_pixel(zone, x=50, y=50, image_width=200, image_height=200) is True
    assert zone_contains_pixel(zone, x=90, y=90, image_width=200, image_height=200) is False


def test_zone_roi_overlay_does_not_pollute_main_facing_detection_store(
    monkeypatch, tmp_path
) -> None:
    context = main_module._runtime_context()
    context.store.reset()
    context.source_health.reset()
    context.frame_store.reset()
    context.overlay_cache.reset()
    with context.overlay_images_lock:
        context.overlay_images.clear()

    zone_path = _zone_config(tmp_path)
    monkeypatch.setenv("VISION_ZONE_ROI_ENABLED", "true")
    monkeypatch.setenv("VISION_ZONE_ROI_CONFIG_PATH", str(zone_path))
    monkeypatch.setenv("VISION_ZONE_ROI_SOURCE", "global_cam_01")
    get_settings.cache_clear()
    load_zone_roi_config_cached.cache_clear()

    response = client.post(
        "/api/v1/vision/frame/process",
        data={"source": "global_cam_01", "force": "true"},
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["event_count"] == 1
    assert body["overlay_event_count"] == 3
    assert [event["class_name"] for event in body["events"]] == ["aruco_marker"]
    assert [event["class_name"] for event in body["overlay_events"]] == [
        "aruco_marker",
        "zone_roi",
        "zone_roi",
    ]
    assert len(context.store.latest(source="global_cam_01", limit=10)) == 1


def test_zone_roi_metadata_plane_includes_overlay_without_polluting_store(
    monkeypatch, tmp_path
) -> None:
    context = main_module._runtime_context()
    context.store.reset()
    context.source_health.reset()
    context.frame_store.reset()
    context.overlay_cache.reset()
    with context.overlay_images_lock:
        context.overlay_images.clear()

    zone_path = _zone_config(tmp_path)
    monkeypatch.setenv("VISION_ZONE_ROI_ENABLED", "true")
    monkeypatch.setenv("VISION_ZONE_ROI_CONFIG_PATH", str(zone_path))
    monkeypatch.setenv("VISION_ZONE_ROI_SOURCE", "global_cam_01")
    get_settings.cache_clear()
    load_zone_roi_config_cached.cache_clear()

    response = client.post(
        "/api/v1/vision/frame/process",
        data={"source": "global_cam_01", "force": "true"},
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )
    assert response.status_code == 200
    assert [event["class_name"] for event in response.json()["events"]] == ["aruco_marker"]

    metadata = client.get(
        "/api/v1/vision/overlay/metadata",
        params={"source": "global_cam_01", "view": "full", "limit": 10},
    )

    assert metadata.status_code == 200
    assert [event["class_name"] for event in metadata.json()["events"]] == [
        "aruco_marker",
        "zone_roi",
        "zone_roi",
    ]
    assert len(context.store.latest(source="global_cam_01", limit=10)) == 1


def test_zone_roi_relative_config_path_resolves_from_repo_root_when_ai_server_cwd_changes(
    monkeypatch,
) -> None:
    context = main_module._runtime_context()
    context.store.reset()
    context.source_health.reset()
    context.frame_store.reset()
    context.overlay_cache.reset()
    with context.overlay_images_lock:
        context.overlay_images.clear()
        context.overlay_event_layers.clear()

    monkeypatch.chdir(Path("."))
    monkeypatch.setenv("VISION_ZONE_ROI_ENABLED", "true")
    monkeypatch.setenv(
        "VISION_ZONE_ROI_CONFIG_PATH", "config/vision/zone_rois/global_cam_01_lab_draft.json"
    )
    monkeypatch.setenv("VISION_ZONE_ROI_SOURCE", "global_cam_01")
    get_settings.cache_clear()
    load_zone_roi_config_cached.cache_clear()

    response = client.post(
        "/api/v1/vision/frame/process",
        data={"source": "global_cam_01", "force": "true"},
        files={"image": ("aruco.png", aruco_png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    class_names = [event["class_name"] for event in response.json()["overlay_events"]]
    assert class_names.count("zone_roi") == 9
    assert len(context.store.latest(source="global_cam_01", limit=10)) == 1
