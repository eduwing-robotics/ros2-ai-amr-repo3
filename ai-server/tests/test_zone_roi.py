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
    assert events[0]["metadata"]["overlay_label"] == "ZONE inbound"
    assert events[0]["metadata"]["overlay_label_xy"] == [28.0, 34.0]
    assert events[1]["metadata"]["overlay_color_bgr"] == [0, 165, 255]
    assert events[1]["metadata"]["overlay_label"] == "REF charging"



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

def test_zone_roi_draft_config_uses_compact_storage_labels() -> None:
    config = load_zone_roi_config(
        REPO_ROOT / "config" / "vision" / "zone_rois" / "global_cam_01_lab_draft.json"
    )

    labels = [zone.label for zone in config.zones if zone.zone_id.startswith("storage_")]

    assert labels == ["storage 1", "storage 2"]


def test_zone_roi_draft_config_exposes_operator_location_aliases() -> None:
    config = load_zone_roi_config(
        REPO_ROOT / "config" / "vision" / "zone_rois" / "global_cam_01_lab_draft.json"
    )

    assert config.location_aliases == {
        "inbound": "inbound_static_item_zone",
        "outbound": "outbound_static_item_zone",
        "storage_1": "storage_upper_static_item_zone",
        "storage_2": "storage_lower_static_item_zone",
    }


def test_zone_roi_draft_uses_wall_floor_calibration_inside_map_roi() -> None:
    path = REPO_ROOT / "config" / "vision" / "zone_rois" / "global_cam_01_lab_draft.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    zones = {zone["zone_id"]: zone for zone in data["zones"]}

    expected_y_bounds = {
        "outbound_static_item_zone": (0.095, 0.409259),
        "charging_reference_zone": (0.409259, 0.740741),
        "inbound_static_item_zone": (0.740741, 0.918519),
        "storage_upper_static_item_zone": (0.418519, 0.633519),
        "storage_lower_static_item_zone": (0.668519, 0.918519),
    }
    expected_label_y = {
        "outbound_static_item_zone": 0.145,
        "charging_reference_zone": 0.464259,
        "inbound_static_item_zone": 0.810741,
        "storage_upper_static_item_zone": 0.473519,
        "storage_lower_static_item_zone": 0.738519,
    }
    expected_x_values = {
        "outbound_static_item_zone": [0.19, 0.43, 0.43, 0.225],
        "charging_reference_zone": [0.225, 0.43, 0.43, 0.245],
        "inbound_static_item_zone": [0.255, 0.43, 0.43, 0.26],
        "storage_upper_static_item_zone": [0.485, 0.705, 0.705, 0.485],
        "storage_lower_static_item_zone": [0.485, 0.705, 0.705, 0.485],
    }
    map_roi = ZoneRoi(
        zone_id="map_roi",
        label="map roi",
        role="diagnostic",
        natural_item_location=False,
        polygon_normalized=tuple(
            (float(x), float(y)) for x, y in data["map_roi"]["polygon_normalized"]
        ),
    )

    for zone_id, (minimum_y, maximum_y) in expected_y_bounds.items():
        polygon = zones[zone_id]["polygon_normalized"]
        assert [point[0] for point in polygon] == expected_x_values[zone_id]
        assert [point[1] for point in polygon] == pytest.approx(
            [minimum_y, minimum_y, maximum_y, maximum_y]
        )
        assert zones[zone_id]["overlay_label_anchor_normalized"][1] == pytest.approx(
            expected_label_y[zone_id]
        )
        for x, y in polygon:
            assert zone_contains_pixel(
                map_roi, x=x * 1920, y=y * 1080, image_width=1920, image_height=1080
            )

    assert expected_y_bounds["storage_upper_static_item_zone"][1] - expected_y_bounds[
        "storage_upper_static_item_zone"
    ][0] == pytest.approx(0.215)
    assert expected_y_bounds["storage_lower_static_item_zone"][1] - expected_y_bounds[
        "storage_lower_static_item_zone"
    ][0] == pytest.approx(0.25)


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
    assert class_names.count("zone_roi") == 5
    assert len(context.store.latest(source="global_cam_01", limit=10)) == 1
