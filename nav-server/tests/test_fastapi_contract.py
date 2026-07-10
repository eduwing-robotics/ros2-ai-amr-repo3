from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nav_app.bootstrap import ensure_import_paths

ensure_import_paths()

from nav_app.runtime import runtime  # noqa: E402
from nav_app.server_core import register_app  # noqa: E402
from nav_app.security import sign_headers  # noqa: E402


def _mock_startup():
    runtime.zone_lock_manager = MagicMock()
    runtime.zone_lock_manager.list_locks.return_value = []
    runtime.zone_lock_manager.zone_ids = []
    runtime.zone_lock_manager.acquire.side_effect = Exception("unused in contract test")
    runtime.traffic_manager = MagicMock()
    runtime.traffic_manager.list_locks.return_value = []
    runtime.traffic_manager.segment_ids = []
    runtime.navigator = MagicMock()
    runtime.navigator.status = "IDLE"
    runtime.navigator.safety.estop = False
    runtime.navigator.get_current_pose.return_value = None
    runtime.navigator.cmd_vel_subscribers.return_value = []
    runtime.navigator.get_latest_aruco_detection.return_value = []
    runtime.navigator.has_amcl_pose.return_value = False
    runtime.navigator.has_simulated_pose.return_value = False
    runtime.navigator.battery_level = 100.0
    runtime.mission_manager = MagicMock()
    runtime.mission_manager.dry_run = True
    runtime.mission_manager.mission_status = "IDLE"
    runtime.mission_manager.get_status_snapshot.return_value = {
        "robot_id": "tb3_burger_01",
        "bridge_robot_id": "tb3_1",
        "ros_domain_id": 2,
        "center_domain_id": 1,
        "namespace": "/tb3_burger_01",
        "teleop_command_topic": "/mission/tb3_1/teleop_cmd",
        "camera_topic": "/mission/tb3_1/camera/compressed",
        "capabilities": ["navigate"],
        "navigator_status": "IDLE",
        "mission_status": "IDLE",
        "battery": 100.0,
        "is_emergency": False,
        "mission_type": None,
        "mission_id": None,
        "item_name": None,
        "count": 0,
        "last_error": None,
        "dry_run": True,
        "pose": None,
    }
    runtime.ros_executor = None
    runtime.ros_thread = None
    runtime.movement_commands = {}
    runtime.last_arrived_gate_by_robot = {}


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SIMULATION_MODE", "1")
    app = FastAPI(title="test")
    register_app(app)
    _mock_startup()
    with TestClient(app) as test_client:
        yield test_client


def test_map_state_is_content_bound(client):
    import hashlib
    from pathlib import Path

    response = client.get("/movement-api/v1/map-state")
    assert response.status_code == 200
    state = response.json()
    root = Path(__file__).resolve().parents[1]
    assert state["map_yaml_exists"] is True and state["image_exists"] is True
    assert state["map_yaml_sha256"] == hashlib.sha256((root / "map" / "robot1_map.yaml").read_bytes()).hexdigest()
    assert state["image_sha256"] == hashlib.sha256((root / "map" / "robot1_map.pgm").read_bytes()).hexdigest()
    assert state["map_identity"]


def test_health_ok(client):
    response = client.get("/movement-api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["simulation_mode"] is True


def test_endpoints_contract_shape(client):
    response = client.get("/movement-api/v1/endpoints")
    assert response.status_code == 200
    body = response.json()
    for field in ("policy", "active_robot_id", "nav_api_url", "main_api_base", "webhook_endpoint", "resolution", "robots"):
        assert field in body


def test_route_preview_coordinates(client):
    body = b'{"command_id":"preview-1","robot_name":"tb3_1","x":1.0,"y":2.0,"yaw":0.0}'
    # TestClient serializes this compact JSON identically; explicit data keeps the signed raw body exact.
    import os
    os.environ["NAV_MAIN_HMAC_SECRET"] = "test-main-nav-secret"
    response = client.post(
        "/movement-api/v1/routes/preview",
        content=body,
        headers={"content-type": "application/json", **sign_headers("test-main-nav-secret", "POST", "/movement-api/v1/routes/preview", body)},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["input_mode"] == "coordinates"
    assert body["steps"]


def test_real_command_rejected_until_localized(client, monkeypatch):
    monkeypatch.setenv("SIMULATION_MODE", "0")
    runtime.mission_manager.dry_run = False
    body = b'{"command_id":"localization-required","robot_name":"tb3_1","steps":[{"action":"move_to_point","payload":{"x":1,"y":2}}]}'
    response = client.post("/movement-api/v1/commands", content=body, headers={"content-type": "application/json", **sign_headers("test-main-nav-secret", "POST", "/movement-api/v1/commands", body)})
    assert response.status_code == 409


def test_explicit_dry_run_bypasses_localization(client):
    body = b'{"command_id":"localization-dry-run","robot_name":"tb3_1","steps":[{"action":"move_to_point","payload":{"x":1,"y":2,"dry_run":true}}]}'
    response = client.post("/movement-api/v1/commands", content=body, headers={"content-type": "application/json", **sign_headers("test-main-nav-secret", "POST", "/movement-api/v1/commands", body)})
    assert response.status_code == 200
