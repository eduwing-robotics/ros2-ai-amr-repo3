from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nav_app.bootstrap import ensure_import_paths

ensure_import_paths()

from nav_app.runtime import runtime
from nav_app.server_core import register_app


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
    runtime.navigator.get_battery_snapshot.return_value = {
        "battery": 58.4,
        "battery_received_monotonic": __import__("time").monotonic(),
    }
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
    runtime.state_store = None


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SIMULATION_MODE", "1")
    app = FastAPI(title="test")
    register_app(app)
    _mock_startup()
    with TestClient(app) as test_client:
        yield test_client


def test_robot_command_duplicate_returns_existing_state(client, monkeypatch):
    from nav_app.routers import movement_api

    monkeypatch.setattr(movement_api, "_dispatch_initial_acceptance", lambda command: None)
    monkeypatch.setattr(movement_api.movement_executor, "execute_movement_command", lambda req: None)
    payload = {
        "command_id": "lms-duplicate-1",
        "robot_id": "tb3_1",
        "robot_name": "tb3_1",
        "kind": "move_to_point",
        "dry_run": True,
        "params": {"x": 1.0, "y": 2.0, "yaw": 0.0},
        "callback_url": "http://smartfactory-main.local:8088/api/v1/movement/command-events",
    }

    first = client.post("/robot-commands", json=payload, headers={"Idempotency-Key": payload["command_id"]})
    duplicate = client.post("/robot-commands", json=payload, headers={"Idempotency-Key": payload["command_id"]})

    assert first.status_code == 200
    assert duplicate.status_code == 200
    assert duplicate.json()["duplicate"] is True
    assert list(runtime.movement_commands) == [payload["command_id"]]
    assert runtime.movement_commands[payload["command_id"]]["source_request_fingerprint"]


def test_robot_command_same_id_different_payload_is_conflict(client, monkeypatch):
    from nav_app.routers import movement_api

    monkeypatch.setattr(movement_api, "_dispatch_initial_acceptance", lambda command: None)
    monkeypatch.setattr(movement_api.movement_executor, "execute_movement_command", lambda req: None)
    payload = {
        "command_id": "lms-conflict-1",
        "robot_id": "tb3_1",
        "robot_name": "tb3_1",
        "kind": "move_to_point",
        "dry_run": True,
        "params": {"x": 1.0, "y": 2.0},
    }

    first = client.post("/robot-commands", json=payload)
    changed = {**payload, "params": {"x": 9.0, "y": 2.0}}
    conflict = client.post("/robot-commands", json=changed)

    assert first.status_code == 200
    assert conflict.status_code == 409


def test_health_ok(client):
    response = client.get("/movement-api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["battery"] == 58
    assert isinstance(body["battery"], int)
    assert body["simulation_mode"] is True


def test_endpoints_contract_shape(client):
    response = client.get("/movement-api/v1/endpoints")
    assert response.status_code == 200
    body = response.json()
    for field in ("policy", "active_robot_id", "nav_api_url", "main_api_base", "webhook_endpoint", "resolution", "robots"):
        assert field in body


def test_route_preview_coordinates(client):
    response = client.post(
        "/movement-api/v1/routes/preview",
        json={
            "command_id": "preview-1",
            "robot_name": "tb3_1",
            "x": 1.0,
            "y": 2.0,
            "yaw": 0.0,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["input_mode"] == "coordinates"
    assert body["steps"]


def test_inbound2_storage_b_scenario_rejects_wrong_robot(client):
    response = client.post(
        "/movement-api/v1/scenarios/inbound2-storage-b/preview",
        json={"command_id": "scenario-preview-1", "robot_name": "tb3_1"},
    )
    assert response.status_code == 400


def test_inbound2_storage_b_preview_has_nine_business_steps(client, monkeypatch):
    from nav_app.routers import movement_api

    monkeypatch.setattr(movement_api.robot_context, "active_bridge_robot_id", lambda: "tb3_2")
    response = client.post(
        "/movement-api/v1/scenarios/inbound2-storage-b/preview",
        json={"command_id": "scenario-preview-2", "robot_name": "tb3_2", "dry_run": True},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["scenario_id"] == "inbound2-storage-b"
    assert body["scenario_version"] == 1
    assert len(body["business_steps"]) == 9
    assert body["executable"] is True
    assert len(body["plan_hash"]) == 64


def test_scenario_idempotency_header_must_match(client, monkeypatch):
    from nav_app.routers import movement_api

    monkeypatch.setattr(movement_api.robot_context, "active_bridge_robot_id", lambda: "tb3_2")
    response = client.post(
        "/movement-api/v1/scenarios/inbound2-storage-b/commands",
        headers={"Idempotency-Key": "different"},
        json={"command_id": "scenario-command-1", "robot_name": "tb3_2", "dry_run": True},
    )
    assert response.status_code == 422


def test_safe_stop_marks_active_command_stopping(client):
    runtime.movement_commands["safe-stop-1"] = {
        "command_id": "safe-stop-1",
        "state": "RUNNING",
        "robot_name": "tb3_1",
    }
    response = client.post("/movement-api/v1/commands/safe-stop-1/safe-stop")
    assert response.status_code == 200
    assert response.json()["state"] == "STOPPING"
    assert runtime.movement_commands["safe-stop-1"]["safe_stop_requested"] is True
