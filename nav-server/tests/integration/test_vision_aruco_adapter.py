from __future__ import annotations

from datetime import datetime, timezone

import pytest


def _event(
    *,
    source: str = "tb3_2_picam",
    marker_id: str = "ARUCO_4X4_50_4",
    timestamp: str = "2026-07-19T15:06:01.243101+09:00",
) -> dict:
    return {
        "event_id": "event-a4",
        "timestamp": timestamp,
        "source": source,
        "robot_id": "tb3_2",
        "frame_id": "tb3_2_pi_camera_optical_frame",
        "event_kind": "CONFIRMED",
        "class_name": "aruco_marker",
        "confidence": 1.0,
        "bbox_xyxy": [78.0, 25.0, 253.0, 199.0],
        "marker_id": marker_id,
        "pose_estimate": None,
        "metadata": {
            "image_width": 320,
            "image_height": 240,
            "frame_seq": 26130,
        },
    }


def test_vision_event_converts_to_nav_detector_payload_without_overlay_pixels():
    from nav_app.services.vision_aruco import detector_payload_from_vision

    payload = detector_payload_from_vision(
        {"events": [_event()]}, expected_source="tb3_2_picam"
    )

    assert payload is not None
    assert payload["transport"] == "vision_http"
    assert payload["source"] == "tb3_2_picam"
    assert len(payload["detections"]) == 1
    detection = payload["detections"][0]
    assert detection["marker_id"] == 4
    assert detection["center_px"] == pytest.approx([165.5, 112.0])
    assert detection["center_error_norm"] == pytest.approx(5.5 / 160.0)
    assert detection["marker_width_px"] == pytest.approx(175.0)
    assert detection["marker_height_px"] == pytest.approx(174.0)
    assert detection["image_width"] == 320
    assert detection["image_height"] == 240
    assert detection["event_id"] == "event-a4"
    assert "image" not in payload
    assert "overlay" not in payload

    observed = datetime.fromtimestamp(
        payload["source_header_stamp"]["sec"]
        + payload["source_header_stamp"]["nanosec"] / 1e9,
        tz=timezone.utc,
    )
    assert observed.isoformat().startswith("2026-07-19T06:06:01.243101")


def test_vision_adapter_filters_source_nonmarker_and_keeps_newest_per_marker():
    from nav_app.services.vision_aruco import detector_payload_from_vision

    old = _event(timestamp="2026-07-19T15:06:00+09:00")
    old["event_id"] = "old"
    wrong_source = _event(source="tb3_1_picam")
    person = {**_event(), "class_name": "person", "marker_id": None}
    newest = _event(timestamp="2026-07-19T15:06:02+09:00")
    newest["event_id"] = "newest"

    payload = detector_payload_from_vision(
        {"events": [old, wrong_source, person, newest]},
        expected_source="tb3_2_picam",
    )

    assert payload is not None
    assert [item["event_id"] for item in payload["detections"]] == ["newest"]


def test_vision_adapter_returns_none_without_a_valid_freshness_timestamp():
    from nav_app.services.vision_aruco import detector_payload_from_vision

    invalid = _event(timestamp="not-a-timestamp")
    assert detector_payload_from_vision(
        {"events": [invalid]}, expected_source="tb3_2_picam"
    ) is None


def test_vision_http_fetch_uses_source_specific_read_only_endpoint(monkeypatch):
    from nav_app.services import vision_aruco

    requested = []

    class _Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return ('{"events":[' + __import__("json").dumps(_event()) + "]}").encode()

    def _open(request, timeout):
        requested.append((request.full_url, timeout, request.get_header("Accept")))
        return _Response()

    monkeypatch.setattr(vision_aruco, "urlopen", _open)

    payload = vision_aruco.fetch_detector_payload(
        api_base_url="http://smartfactory-vision.local:8100",
        source="tb3_2_picam",
        limit=7,
        timeout_sec=0.25,
    )

    assert payload is not None
    assert requested == [
        (
            "http://smartfactory-vision.local:8100/api/v1/detections/latest?source=tb3_2_picam&limit=7",
            0.25,
            "application/json",
        )
    ]
