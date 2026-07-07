import pytest
from fastapi.testclient import TestClient
from generated_fixtures import (
    aruco_png_bytes,
    blank_png_bytes,
    multi_aruco_png_bytes,
)

from app.contracts import validate_vision_event
from app.main import app

client = TestClient(app)


@pytest.mark.parametrize(
    ("source", "expected_robot_id", "marker_id"),
    [
        ("global_cam_01", None, 1),
        ("tb3_1_picam", "tb3_1", 2),
        ("tb3_2_picam", "tb3_2", 3),
    ],
)
def test_generated_aruco_fixtures_emit_contract_valid_events(source, expected_robot_id, marker_id):
    response = client.post(
        "/api/v1/detect/image",
        data={"source": source},
        files={"image": ("generated-aruco.png", aruco_png_bytes(marker_id), "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["source"] == source
    assert body["emitted"] is False
    assert len(body["events"]) == 1

    event = body["events"][0]
    validate_vision_event(event)
    assert event["source"] == source
    assert event["robot_id"] == expected_robot_id
    assert event["class_name"] == "aruco_marker"
    assert event["event_kind"] == "CONFIRMED"
    assert event["marker_id"] == f"ARUCO_4X4_50_{marker_id}"
    assert event["wms_hint"] == "TAG_DETECTED"
    assert event["depth_median_m"] is None
    assert event["metadata"]["model"] == "opencv-aruco-4x4-50"
    assert event["metadata"]["image_width"] == 160
    assert event["metadata"]["image_height"] == 160
    x1, y1, x2, y2 = event["bbox_xyxy"]
    assert 0 <= x1 < x2 <= event["metadata"]["image_width"]
    assert 0 <= y1 < y2 <= event["metadata"]["image_height"]


def test_generated_blank_fixture_emits_no_events():
    response = client.post(
        "/api/v1/detect/image",
        data={"source": "global_cam_01"},
        files={"image": ("blank.png", blank_png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["events"] == []


def test_generated_fixture_decode_rejects_non_image_bytes():
    response = client.post(
        "/api/v1/detect/image",
        data={"source": "global_cam_01"},
        files={"image": ("not-image.bin", b"not an image", "application/octet-stream")},
    )

    assert response.status_code == 400
    assert "decodable image" in response.json()["error"]["message"]


def test_generated_multi_marker_fixture_returns_all_markers_in_stable_order():
    response = client.post(
        "/api/v1/detect/image",
        data={"source": "global_cam_01"},
        files={"image": ("generated-multi-aruco.png", multi_aruco_png_bytes(), "image/png")},
    )

    assert response.status_code == 200
    events = response.json()["events"]
    assert [event["marker_id"] for event in events] == [
        "ARUCO_4X4_50_4",
        "ARUCO_4X4_50_5",
    ]
    for event in events:
        validate_vision_event(event)
        x1, y1, x2, y2 = event["bbox_xyxy"]
        assert 0 <= x1 < x2 <= event["metadata"]["image_width"]
        assert 0 <= y1 < y2 <= event["metadata"]["image_height"]


def test_generated_fixture_event_is_available_in_latest_feed():
    client.post(
        "/api/v1/detect/image",
        data={"source": "tb3_2_picam"},
        files={"image": ("generated-aruco.png", aruco_png_bytes(9), "image/png")},
    )

    response = client.get("/api/v1/detections/latest", params={"source": "tb3_2_picam", "limit": 1})

    assert response.status_code == 200
    events = response.json()["events"]
    assert len(events) == 1
    validate_vision_event(events[0])
    assert events[0]["marker_id"] == "ARUCO_4X4_50_9"
