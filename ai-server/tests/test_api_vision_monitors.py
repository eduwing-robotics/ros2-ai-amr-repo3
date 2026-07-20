import asyncio
import hashlib
import hmac
import json
import time
from time import perf_counter

import cv2
import numpy as np
from fastapi.testclient import TestClient as FastAPITestClient

from app.api import vision as vision_api
from app.config import get_settings
from app.factory import create_app
from app.runtime_state import create_runtime_context
from app.vision_monitor_profiles import (
    DROP_WATCH_PROFILE_ID,
    PERSON_DRIVE_PROFILE_ID,
    PERSON_DRIVE_THRESHOLD_SET_ID,
)

_TEST_SECRET = "test-main-hmac-secret"
get_settings().main_hmac_secret = _TEST_SECRET


class TestClient(FastAPITestClient):
    """Existing monitor API tests exercise the same signed Main mutation contract."""

    def request(self, method, url, *args, **kwargs):
        get_settings().main_hmac_secret = _TEST_SECRET
        if method.upper() in {"POST", "PUT"} and ("/monitors/" in str(url) or "lift-load/evaluate" in str(url)):
            body = kwargs.get("content")
            if body is None and "json" in kwargs:
                body = json.dumps(kwargs["json"], separators=(",", ":")).encode()
                kwargs["content"] = body
                kwargs.pop("json")
                headers = dict(kwargs.get("headers") or {})
                headers["content-type"] = "application/json"
                kwargs["headers"] = headers
            body = body if isinstance(body, bytes) else str(body or "").encode()
            timestamp, nonce = str(int(time.time())), "test-" + str(time.time_ns())
            path = str(url)
            payload = "\n".join((method.upper(), path, timestamp, nonce, hashlib.sha256(body).hexdigest())).encode()
            signature = hmac.new(_TEST_SECRET.encode(), payload, hashlib.sha256).hexdigest()
            headers = dict(kwargs.pop("headers", {}) or {})
            headers.update({"X-SF-Timestamp": timestamp, "X-SF-Nonce": nonce, "X-SF-Signature": signature})
            kwargs["headers"] = headers
        return super().request(method, url, *args, **kwargs)


def _client():
    context = create_runtime_context()
    return TestClient(create_app(runtime_context=context))


def test_monitor_state_defaults_are_disabled_for_known_profiles():
    client = _client()

    response = client.get("/api/v1/vision/monitors")

    assert response.status_code == 200
    body = response.json()
    monitors = {item["monitor_id"]: item for item in body["monitors"]}
    assert set(monitors) == {"person_drive", "drop_watch", "lift_evidence"}
    assert all(item["enabled"] is False for item in monitors.values())
    assert all(item["operation_state"] == "IDLE" for item in monitors.values())
    assert all(item["revision"] == 0 for item in monitors.values())


def test_put_monitor_state_enables_person_drive_and_infers_robot_from_picam_source():
    client = _client()

    response = client.put(
        "/api/v1/vision/monitors/person_drive/state",
        json={
            "enabled": True,
            "source": "tb3_1_picam",
            "operation_state": "DRIVE",
            "task_id": 101,
            "target_fps": 3,
            "profile_id": PERSON_DRIVE_PROFILE_ID,
            "threshold_set_id": PERSON_DRIVE_THRESHOLD_SET_ID,
        },
    )

    assert response.status_code == 200
    monitor = response.json()["monitor"]
    assert monitor["enabled"] is True
    assert monitor["source"] == "tb3_1_picam"
    assert monitor["robot_id"] == "tb3_1"
    assert monitor["operation_state"] == "DRIVE"
    assert monitor["target_fps"] == 3.0
    assert monitor["updated_at"] is not None
    assert monitor["revision"] == 1

    get_response = client.get("/api/v1/vision/monitors/person_drive/state")
    assert get_response.status_code == 200
    assert get_response.json()["monitor"] == monitor

    second_response = client.put(
        "/api/v1/vision/monitors/person_drive/state",
        json={
            "enabled": True,
            "source": "tb3_1_picam",
            "operation_state": "DRIVE",
            "task_id": 102,
            "target_fps": 2,
        },
    )
    assert second_response.status_code == 200
    assert second_response.json()["monitor"]["revision"] == 2


def test_monitor_state_accepts_global_drop_watch_context_without_fixed_robot_identity():
    client = _client()

    response = client.put(
        "/api/v1/vision/monitors/drop_watch/state",
        json={
            "enabled": True,
            "source": "global_cam_01",
            "operation_state": "DRIVE",
            "target_fps": 2,
            "profile_id": DROP_WATCH_PROFILE_ID,
        },
    )

    assert response.status_code == 200
    monitor = response.json()["monitor"]
    assert monitor["source"] == "global_cam_01"
    assert monitor["robot_id"] is None
    assert monitor["operation_state"] == "DRIVE"


def test_monitor_state_requires_lift_evidence_robot_context():
    client = _client()

    response = client.put(
        "/api/v1/vision/monitors/lift_evidence/state",
        json={"enabled": True, "source": "global_cam_01", "operation_state": "PICKUP"},
    )

    assert response.status_code == 400
    assert "requires robot_id" in response.json()["error"]["message"]


def test_monitor_state_rejects_invalid_source_robot_mapping():
    client = _client()

    response = client.put(
        "/api/v1/vision/monitors/person_drive/state",
        json={
            "enabled": True,
            "source": "tb3_1_picam",
            "robot_id": "tb3_2",
            "operation_state": "DRIVE",
        },
    )

    assert response.status_code == 400
    assert "requires robot_id" in response.json()["error"]["message"]


def test_monitor_state_rejects_wrong_operation_for_drive_only_monitors():
    client = _client()

    response = client.put(
        "/api/v1/vision/monitors/drop_watch/state",
        json={"enabled": True, "source": "global_cam_01", "operation_state": "PICKUP"},
    )

    assert response.status_code == 400
    assert "DROP_WATCH" not in response.text
    assert "drop_watch can be enabled only in DRIVE" in response.json()["error"]["message"]


def test_monitor_state_rejects_unknown_monitor_id():
    client = _client()

    response = client.get("/api/v1/vision/monitors/not_a_monitor/state")

    assert response.status_code == 400
    assert "unknown monitor_id" in response.json()["error"]["message"]


def test_main_dashboard_cors_allows_put_monitor_state():
    client = _client()

    response = client.options(
        "/api/v1/vision/monitors/person_drive/state",
        headers={
            "Origin": "http://smartfactory-main.local:8088",
            "Access-Control-Request-Method": "PUT",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://smartfactory-main.local:8088"
    assert "PUT" in response.headers["access-control-allow-methods"]


def _flatten(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _flatten(child)
    elif isinstance(value, list):
        for child in value:
            yield from _flatten(child)
    else:
        yield value


def _marker_image(marker_id: int, marker_size: int = 160) -> np.ndarray:
    aruco_dict = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_50)
    if hasattr(cv2.aruco, "generateImageMarker"):
        return cv2.aruco.generateImageMarker(aruco_dict, marker_id, marker_size)
    marker = np.zeros((marker_size, marker_size), dtype=np.uint8)
    cv2.aruco.drawMarker(aruco_dict, marker_id, marker_size, marker, 1)
    return marker


def _global_frame_with_marker(
    marker_id: int,
    *,
    center_norm: tuple[float, float] = (0.31, 0.85),
    marker_size: int = 160,
) -> np.ndarray:
    image = np.full((1080, 1920, 3), 255, dtype=np.uint8)
    marker = cv2.cvtColor(_marker_image(marker_id, marker_size=marker_size), cv2.COLOR_GRAY2BGR)
    center_x = int(center_norm[0] * image.shape[1])
    center_y = int(center_norm[1] * image.shape[0])
    x = max(0, min(image.shape[1] - marker_size, center_x - marker_size // 2))
    y = max(0, min(image.shape[0] - marker_size, center_y - marker_size // 2))
    image[y : y + marker_size, x : x + marker_size] = marker
    return image


def _global_frame_with_markers(
    markers: list[tuple[int, tuple[float, float]]],
    *,
    marker_size: int = 80,
) -> np.ndarray:
    image = np.full((1080, 1920, 3), 255, dtype=np.uint8)
    for marker_id, center_norm in markers:
        marker = cv2.cvtColor(_marker_image(marker_id, marker_size=marker_size), cv2.COLOR_GRAY2BGR)
        center_x = int(center_norm[0] * image.shape[1])
        center_y = int(center_norm[1] * image.shape[0])
        x = max(0, min(image.shape[1] - marker_size, center_x - marker_size // 2))
        y = max(0, min(image.shape[0] - marker_size, center_y - marker_size // 2))
        image[y : y + marker_size, x : x + marker_size] = marker
    return image


def test_person_hazard_latest_returns_no_active_monitor_until_drive_monitor_enabled():
    client = _client()

    response = client.get("/api/v1/vision/hazards/person/latest", params={"robot_id": "tb3_1"})

    assert response.status_code == 200
    body = response.json()
    assert body["result"] == "NO_ACTIVE_MONITOR"
    assert body["event"] is None


def test_person_hazard_latest_maps_existing_person_event_to_advisory_payload():
    context = create_runtime_context()
    client = TestClient(create_app(runtime_context=context))
    context.store.add(
        {
            "event_id": "source-person-event-1",
            "source": "tb3_1_picam",
            "class_name": "person",
            "confidence": 0.87,
            "timestamp": "2026-06-30T05:00:00+00:00",
            "bbox_xyxy": [1, 2, 3, 4],
        }
    )
    context.store.add(
        {
            "event_id": "source-marker-event-1",
            "source": "tb3_1_picam",
            "class_name": "aruco_marker",
            "confidence": 0.99,
            "timestamp": "2026-06-30T05:00:01+00:00",
        }
    )
    client.put(
        "/api/v1/vision/monitors/person_drive/state",
        json={
            "enabled": True,
            "source": "tb3_1_picam",
            "operation_state": "DRIVE",
            "task_id": 777,
        },
    )

    response = client.get("/api/v1/vision/hazards/person/latest", params={"robot_id": "tb3_1"})

    assert response.status_code == 200
    body = response.json()
    event = body["event"]
    assert body["result"] == "ADVISORY"
    assert body["reason_code"] == "HUMAN_DETECTED"
    assert event["schema_version"] == "vision-monitor-event.v1"
    assert event["event_type"] == "HUMAN_DETECTED"
    assert event["source"] == "tb3_1_picam"
    assert event["robot_id"] == "tb3_1"
    assert event["task_id"] == 777
    assert event["trusted"] is False
    assert event["confidence"] == 0.87
    assert event["data_json"]["source_event_id"] == "source-person-event-1"
    assert "bbox_xyxy" not in set(_flatten(event))
    assert "HOLD" not in set(_flatten(event))


def test_person_hazard_latest_returns_empty_when_monitor_active_but_no_person_event():
    context = create_runtime_context()
    client = TestClient(create_app(runtime_context=context))
    context.store.add(
        {
            "event_id": "source-marker-event-2",
            "source": "tb3_2_picam",
            "class_name": "aruco_marker",
            "confidence": 0.99,
            "timestamp": "2026-06-30T05:00:01+00:00",
        }
    )
    client.put(
        "/api/v1/vision/monitors/person_drive/state",
        json={"enabled": True, "source": "tb3_2_picam", "operation_state": "DRIVE"},
    )

    response = client.get("/api/v1/vision/hazards/person/latest", params={"robot_id": "tb3_2"})

    assert response.status_code == 200
    body = response.json()
    assert body["result"] == "NO_RELEVANT_DETECTION"
    assert body["event"] is None


def test_person_drive_monitor_supports_two_robots_driving_at_the_same_time():
    context = create_runtime_context()
    client = TestClient(create_app(runtime_context=context))
    context.store.add(
        {
            "event_id": "tb3-1-person",
            "source": "tb3_1_picam",
            "class_name": "person",
            "confidence": 0.81,
            "timestamp": "2026-06-30T05:00:00+00:00",
        }
    )
    context.store.add(
        {
            "event_id": "tb3-2-person",
            "source": "tb3_2_picam",
            "class_name": "person",
            "confidence": 0.91,
            "timestamp": "2026-06-30T05:00:01+00:00",
        }
    )

    tb3_1_on = client.put(
        "/api/v1/vision/monitors/person_drive/state",
        json={
            "enabled": True,
            "source": "tb3_1_picam",
            "operation_state": "DRIVE",
            "task_id": 101,
        },
    )
    tb3_2_on = client.put(
        "/api/v1/vision/monitors/person_drive/state",
        json={
            "enabled": True,
            "source": "tb3_2_picam",
            "operation_state": "DRIVE",
            "task_id": 202,
        },
    )
    assert tb3_1_on.status_code == 200
    assert tb3_2_on.status_code == 200

    tb3_1_state = client.get(
        "/api/v1/vision/monitors/person_drive/state",
        params={"robot_id": "tb3_1"},
    ).json()["monitor"]
    tb3_2_state = client.get(
        "/api/v1/vision/monitors/person_drive/state",
        params={"robot_id": "tb3_2"},
    ).json()["monitor"]
    assert tb3_1_state["enabled"] is True
    assert tb3_1_state["source"] == "tb3_1_picam"
    assert tb3_1_state["task_id"] == 101
    assert tb3_2_state["enabled"] is True
    assert tb3_2_state["source"] == "tb3_2_picam"
    assert tb3_2_state["task_id"] == 202

    tb3_1_latest = client.get(
        "/api/v1/vision/hazards/person/latest",
        params={"robot_id": "tb3_1"},
    ).json()
    tb3_2_latest = client.get(
        "/api/v1/vision/hazards/person/latest",
        params={"robot_id": "tb3_2"},
    ).json()
    assert tb3_1_latest["result"] == "ADVISORY"
    assert tb3_1_latest["event"]["task_id"] == 101
    assert tb3_1_latest["event"]["data_json"]["source_event_id"] == "tb3-1-person"
    assert tb3_2_latest["result"] == "ADVISORY"
    assert tb3_2_latest["event"]["task_id"] == 202
    assert tb3_2_latest["event"]["data_json"]["source_event_id"] == "tb3-2-person"


def test_disabling_one_person_drive_robot_keeps_the_other_robot_active():
    context = create_runtime_context()
    client = TestClient(create_app(runtime_context=context))
    for source, event_id in (
        ("tb3_1_picam", "tb3-1-person"),
        ("tb3_2_picam", "tb3-2-person"),
    ):
        context.store.add(
            {
                "event_id": event_id,
                "source": source,
                "class_name": "person",
                "confidence": 0.88,
                "timestamp": "2026-06-30T05:00:00+00:00",
            }
        )
        client.put(
            "/api/v1/vision/monitors/person_drive/state",
            json={
                "enabled": True,
                "source": source,
                "operation_state": "DRIVE",
            },
        )

    response = client.put(
        "/api/v1/vision/monitors/person_drive/state",
        json={
            "enabled": False,
            "source": "tb3_1_picam",
            "operation_state": "IDLE",
        },
    )
    assert response.status_code == 200

    tb3_1_latest = client.get(
        "/api/v1/vision/hazards/person/latest",
        params={"robot_id": "tb3_1"},
    ).json()
    tb3_2_latest = client.get(
        "/api/v1/vision/hazards/person/latest",
        params={"robot_id": "tb3_2"},
    ).json()
    assert tb3_1_latest["result"] == "NO_ACTIVE_MONITOR"
    assert tb3_1_latest["event"] is None
    assert tb3_2_latest["result"] == "ADVISORY"
    assert tb3_2_latest["event"]["source"] == "tb3_2_picam"


def test_person_hazard_latest_rejects_robot_source_mismatch():
    client = _client()

    response = client.get(
        "/api/v1/vision/hazards/person/latest",
        params={"robot_id": "tb3_1", "source": "tb3_2_picam"},
    )

    assert response.status_code == 400
    assert "requires source tb3_1_picam" in response.json()["error"]["message"]


def test_lift_load_evaluate_passes_expected_aruco_in_requested_zone():
    context = create_runtime_context()
    client = TestClient(create_app(runtime_context=context))
    context.frame_store.put_decoded(
        source="global_cam_01",
        image_bgr=_global_frame_with_marker(20, center_norm=(0.31, 0.85)),
    )

    response = client.post(
        "/api/v1/vision/evidence/lift-load/evaluate",
        json={
            "source": "global_cam_01",
            "robot_id": "tb3_1",
            "task_id": 303,
            "command_id": 3,
            "operation": "PICK_UP",
            "expected_item_id": "item-red",
            "expected_marker_id": 20,
            "expected_item_count": 1,
            "vision_zone_id": "inbound_static_item_zone",
            "burst_frames": 1,
            "min_pass_frames": 1,
            "sample_interval_ms": 0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    event = body["event"]
    assert body["schema_version"] == "vision-lift-load-evaluate.v1"
    assert body["result"] == "PASS"
    assert body["reason_code"] == "EXPECTED_ITEM_COUNT_MATCH_AND_STABLE"
    assert body["operation"] == "PICKUP"
    assert body["vision_zone_id"] == "inbound_static_item_zone"
    assert event["event_type"] == "ITEM_PICKED"
    assert event["trusted"] is False
    assert event["confidence"] == 1.0
    assert event["data_json"]["expected_count"] == 1
    assert event["data_json"]["expected_item_count"] == 1
    assert event["data_json"]["observed_count"] == 1
    assert event["data_json"]["detected_marker_id"] == "ARUCO_4X4_50_20"
    assert event["data_json"]["vision_zone_id"] == "inbound_static_item_zone"
    assert "bbox_xyxy" not in set(_flatten(event))
    assert "polygon" not in set(_flatten(event))
    assert "HOLD" not in set(_flatten(event))


def test_lift_load_evaluate_pre_dropoff_returns_placement_ready_not_placed():
    context = create_runtime_context()
    client = TestClient(create_app(runtime_context=context))
    context.frame_store.put_decoded(
        source="global_cam_01",
        image_bgr=_global_frame_with_marker(20, center_norm=(0.31, 0.85)),
    )

    response = client.post(
        "/api/v1/vision/evidence/lift-load/evaluate",
        json={
            "source": "global_cam_01",
            "robot_id": "tb3_1",
            "task_id": 305,
            "command_id": 5,
            "operation": "PRE_DROPOFF",
            "expected_item_id": "item-red",
            "expected_marker_id": 20,
            "expected_item_count": 1,
            "vision_zone_id": "inbound_static_item_zone",
            "burst_frames": 1,
            "min_pass_frames": 1,
            "sample_interval_ms": 0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    event = body["event"]
    assert body["result"] == "PASS"
    assert body["operation"] == "PRE_DROP_OFF"
    assert event["event_type"] == "ITEM_PLACEMENT_READY"
    assert event["trusted"] is False
    assert event["data_json"]["operation"] == "PRE_DROP_OFF"
    assert event["data_json"]["command_satisfying"] is True
    assert event["data_json"]["detected_marker_id"] == "ARUCO_4X4_50_20"
    assert "ITEM_PLACED" not in {event["event_type"]}


def test_lift_load_evaluate_default_burst_passes_with_one_frame_hit():
    context = create_runtime_context()
    client = TestClient(create_app(runtime_context=context))
    context.frame_store.put_decoded(
        source="global_cam_01",
        image_bgr=_global_frame_with_marker(20, center_norm=(0.31, 0.85)),
    )

    response = client.post(
        "/api/v1/vision/evidence/lift-load/evaluate",
        json={
            "source": "global_cam_01",
            "robot_id": "tb3_1",
            "operation": "PICK_UP",
            "expected_marker_id": 20,
            "vision_zone_id": "inbound_static_item_zone",
            "sample_interval_ms": 0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"] == "PASS"
    assert body["reason_code"] == "EXPECTED_ITEM_COUNT_MATCH_AND_STABLE"
    assert body["event"]["confidence"] == 0.1
    assert body["event"]["data_json"]["accepted_frames"] == 1
    assert body["event"]["data_json"]["total_frames"] == 1


def test_lift_load_evaluate_ignores_unregistered_extra_marker():
    context = create_runtime_context()
    client = TestClient(create_app(runtime_context=context))
    context.frame_store.put_decoded(
        source="global_cam_01",
        image_bgr=_global_frame_with_markers(
            [
                (20, (0.29, 0.85)),
                (21, (0.34, 0.85)),
            ]
        ),
    )

    response = client.post(
        "/api/v1/vision/evidence/lift-load/evaluate",
        json={
            "source": "global_cam_01",
            "robot_id": "tb3_1",
            "operation": "PICK_UP",
            "expected_marker_id": 20,
            "expected_item_count": 1,
            "vision_zone_id": "inbound_static_item_zone",
            "burst_frames": 1,
            "min_pass_frames": 1,
            "sample_interval_ms": 0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"] == "PASS"
    assert body["event"]["data_json"]["detected_marker_ids"] == ["ARUCO_4X4_50_20"]
    assert body["event"]["data_json"]["observed_count"] == 1


def test_lift_load_evaluate_resolves_location_id_only_through_zone_alias_config():
    context = create_runtime_context()
    client = TestClient(create_app(runtime_context=context))
    context.frame_store.put_decoded(
        source="global_cam_01",
        image_bgr=_global_frame_with_marker(20, center_norm=(0.31, 0.85)),
    )

    response = client.post(
        "/api/v1/vision/evidence/lift-load/evaluate",
        json={
            "source": "global_cam_01",
            "robot_id": "tb3_1",
            "operation": "PICK_UP",
            "expected_marker_id": 20,
            "location_id": "inbound",
            "burst_frames": 1,
            "min_pass_frames": 1,
            "sample_interval_ms": 0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"] == "PASS"
    assert body["vision_zone_id"] == "inbound_static_item_zone"
    assert body["event"]["data_json"]["location_id"] == "inbound"
    assert body["event"]["data_json"]["zone_resolution_source"] == "location_aliases"


def test_lift_load_evaluate_does_not_treat_unmapped_location_id_as_zone_id():
    context = create_runtime_context()
    client = TestClient(create_app(runtime_context=context))
    context.frame_store.put_decoded(
        source="global_cam_01",
        image_bgr=_global_frame_with_marker(20, center_norm=(0.31, 0.85)),
    )

    response = client.post(
        "/api/v1/vision/evidence/lift-load/evaluate",
        json={
            "source": "global_cam_01",
            "robot_id": "tb3_1",
            "operation": "PICK_UP",
            "expected_marker_id": 20,
            "location_id": "main-db-location-not-yet-mapped",
            "burst_frames": 1,
            "sample_interval_ms": 0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"] == "NO_DECISION"
    assert body["reason_code"] == "POLICY_NOT_APPLICABLE"
    assert body["vision_zone_id"] is None
    assert body["event"]["data_json"]["location_id"] == "main-db-location-not-yet-mapped"
    assert body["event"]["data_json"]["zone_resolution_source"] == "unmapped_location_id"


def test_lift_load_burst_sampling_yields_event_loop_between_attempts():
    async def run_check() -> tuple[float, list, object]:
        start = perf_counter()
        burst_task = asyncio.create_task(
            vision_api._latest_frame_burst(
                source="source_without_frames_for_async_regression",
                burst_frames=3,
                sample_interval_ms=50,
                max_frame_age_s=2.0,
            )
        )
        await asyncio.sleep(0.01)
        elapsed_before_tick = perf_counter() - start
        frames, latest_seen = await burst_task
        return elapsed_before_tick, frames, latest_seen

    elapsed_before_tick, frames, latest_seen = asyncio.run(run_check())

    assert elapsed_before_tick < 0.1
    assert frames == []
    assert latest_seen is None


def test_lift_load_evaluate_fails_when_different_item_marker_is_in_zone():
    context = create_runtime_context()
    client = TestClient(create_app(runtime_context=context))
    context.frame_store.put_decoded(
        source="global_cam_01",
        image_bgr=_global_frame_with_marker(22, center_norm=(0.31, 0.85)),
    )

    response = client.post(
        "/api/v1/vision/evidence/lift-load/evaluate",
        json={
            "source": "global_cam_01",
            "robot_id": "tb3_2",
            "task_id": 304,
            "command_id": 4,
            "operation": "DROP_OFF",
            "expected_marker_id": 20,
            "expected_item_count": 1,
            "vision_zone_id": "inbound_static_item_zone",
            "burst_frames": 1,
            "min_pass_frames": 1,
            "sample_interval_ms": 0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    event = body["event"]
    assert body["result"] == "FAIL"
    assert body["reason_code"] == "EXPECTED_ITEM_COUNT_MISMATCH"
    assert body["operation"] == "DROPOFF"
    assert event["event_type"] == "LIFT_LOAD_EVIDENCE"
    assert event["data_json"]["detected_marker_ids"] == ["ARUCO_4X4_50_22"]
    assert event["data_json"]["observed_count"] == 1
    assert event["data_json"]["command_satisfying"] is False


def test_lift_load_evaluate_reports_all_item_markers_when_expected_and_unexpected_are_mixed():
    context = create_runtime_context()
    client = TestClient(create_app(runtime_context=context))
    context.frame_store.put_decoded(
        source="global_cam_01",
        image_bgr=_global_frame_with_markers(
            [
                (20, (0.29, 0.85)),
                (22, (0.34, 0.85)),
            ]
        ),
    )

    response = client.post(
        "/api/v1/vision/evidence/lift-load/evaluate",
        json={
            "source": "global_cam_01",
            "robot_id": "tb3_1",
            "operation": "PICK_UP",
            "expected_marker_id": 20,
            "expected_item_count": 1,
            "vision_zone_id": "inbound_static_item_zone",
            "burst_frames": 1,
            "min_pass_frames": 1,
            "sample_interval_ms": 0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"] == "FAIL"
    assert body["reason_code"] == "EXPECTED_ITEM_COUNT_MISMATCH"
    assert body["event"]["data_json"]["observed_count"] == 2
    assert body["event"]["data_json"]["detected_marker_ids"] == [
        "ARUCO_4X4_50_20",
        "ARUCO_4X4_50_22",
    ]
    assert body["event"]["data_json"]["detected_marker_id"] is None


def test_lift_load_evaluate_ignores_non_natural_reference_zone():
    context = create_runtime_context()
    client = TestClient(create_app(runtime_context=context))
    context.frame_store.put_decoded(
        source="global_cam_01",
        image_bgr=_global_frame_with_marker(20, center_norm=(0.30, 0.62)),
    )

    response = client.post(
        "/api/v1/vision/evidence/lift-load/evaluate",
        json={
            "source": "global_cam_01",
            "robot_id": "tb3_1",
            "operation": "PICK_UP",
            "expected_marker_id": 20,
            "vision_zone_id": "charging_reference_zone",
            "burst_frames": 1,
            "sample_interval_ms": 0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"] == "NO_DECISION"
    assert body["reason_code"] == "POLICY_NOT_APPLICABLE"
    assert body["event"]["event_type"] == "NO_DECISION"


def test_lift_load_evaluate_rejects_reserved_map_marker_as_item_id():
    client = _client()

    response = client.post(
        "/api/v1/vision/evidence/lift-load/evaluate",
        json={
            "source": "global_cam_01",
            "robot_id": "tb3_1",
            "operation": "PICK_UP",
            "expected_marker_id": 6,
            "vision_zone_id": "inbound_static_item_zone",
        },
    )

    assert response.status_code == 400
    assert "0..19 are reserved" in response.json()["error"]["message"]


def test_lift_load_evaluate_rejects_unknown_request_fields():
    client = _client()

    response = client.post(
        "/api/v1/vision/evidence/lift-load/evaluate",
        json={
            "source": "global_cam_01",
            "robot_id": "tb3_1",
            "operation": "PICK_UP",
            "expected_marker_idd": 20,
            "vision_zone_id": "inbound_static_item_zone",
        },
    )

    assert response.status_code == 422


def test_lift_load_evaluate_rejects_min_pass_frames_greater_than_burst_frames():
    client = _client()

    response = client.post(
        "/api/v1/vision/evidence/lift-load/evaluate",
        json={
            "source": "global_cam_01",
            "robot_id": "tb3_1",
            "operation": "PICK_UP",
            "expected_marker_id": 20,
            "vision_zone_id": "inbound_static_item_zone",
            "burst_frames": 1,
            "min_pass_frames": 2,
        },
    )

    assert response.status_code == 422


def test_lift_load_evaluate_returns_no_decision_when_global_frame_is_missing():
    client = _client()

    response = client.post(
        "/api/v1/vision/evidence/lift-load/evaluate",
        json={
            "source": "global_cam_01",
            "robot_id": "tb3_1",
            "operation": "PICK_UP",
            "expected_marker_id": 20,
            "vision_zone_id": "inbound_static_item_zone",
            "burst_frames": 1,
            "sample_interval_ms": 0,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["result"] == "NO_DECISION"
    assert body["reason_code"] == "NO_RELEVANT_DETECTION"
    assert body["event"]["data_json"]["detected_marker_ids"] == []


def test_monitor_person_hazard_and_lift_load_routes_have_explicit_openapi_response_schemas():
    schema = create_app(runtime_context=create_runtime_context()).openapi()

    monitor_list_schema = schema["paths"]["/api/v1/vision/monitors"]["get"]["responses"]["200"][
        "content"
    ]["application/json"]["schema"]
    monitor_state_schema = schema["paths"]["/api/v1/vision/monitors/{monitor_id}/state"]["put"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    hazard_schema = schema["paths"]["/api/v1/vision/hazards/person/latest"]["get"]["responses"][
        "200"
    ]["content"]["application/json"]["schema"]
    lift_load_schema = schema["paths"]["/api/v1/vision/evidence/lift-load/evaluate"]["post"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]

    assert monitor_list_schema["additionalProperties"] is False
    assert monitor_list_schema["properties"]["monitors"]["minItems"] == 4
    assert (
        monitor_list_schema["properties"]["monitors"]["items"]["properties"]["revision"]["minimum"]
        == 0
    )
    assert monitor_state_schema["properties"]["monitor"]["description"].startswith("Process-local")
    assert hazard_schema["properties"]["event"]["anyOf"][0]["type"] == "null"
    assert (
        hazard_schema["properties"]["event"]["anyOf"][1]["properties"]["trusted"]["const"] is False
    )
    assert lift_load_schema["additionalProperties"] is False
    assert (
        lift_load_schema["properties"]["schema_version"]["const"] == "vision-lift-load-evaluate.v1"
    )
    assert lift_load_schema["properties"]["monitor_id"]["const"] == "lift_evidence"

    request_ref = schema["paths"]["/api/v1/vision/evidence/lift-load/evaluate"]["post"][
        "requestBody"
    ]["content"]["application/json"]["schema"]["$ref"]
    request_schema = schema["components"]["schemas"][request_ref.rsplit("/", 1)[-1]]
    assert request_schema["required"] == ["robot_id", "operation"]
    assert request_schema["additionalProperties"] is False
    assert request_schema["properties"]["source"]["const"] == "global_cam_01"
    assert request_schema["properties"]["robot_id"]["enum"] == ["tb3_1", "tb3_2"]
    assert request_schema["properties"]["operation"]["enum"] == [
        "PICK_UP",
        "PICKUP",
        "DROP_OFF",
        "DROPOFF",
        "PRE_DROP_OFF",
        "PRE_DROPOFF",
    ]
    assert lift_load_schema["properties"]["operation"]["enum"] == [
        "PICKUP",
        "DROPOFF",
        "PRE_DROP_OFF",
    ]
    assert request_schema["properties"]["expected_item_count"]["minimum"] == 1
    assert request_schema["properties"]["min_pass_frames"]["default"] == 1
