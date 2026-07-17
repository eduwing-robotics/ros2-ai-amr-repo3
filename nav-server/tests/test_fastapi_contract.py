from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from nav_app.bootstrap import ensure_import_paths

ensure_import_paths()

from nav_app.runtime import runtime  # noqa: E402
from nav_app.security import sign_headers  # noqa: E402
from nav_app.server_core import register_app  # noqa: E402
from nav_app.services import robot_context  # noqa: E402


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
    runtime.navigator.request_global_localization.return_value = {
        "accepted": True,
        "strategy": "observe_only",
        "motion_started": False,
        "reason": "amcl_global_search_started",
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
    runtime.localization = None


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("SIMULATION_MODE", "1")
    monkeypatch.setenv("NAV_MAIN_HMAC_SECRET", "test-main-nav-secret")
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
    assert state["active_map_id"] == "robot2_map"
    assert Path(state["map_yaml"]).resolve() == (root / "map" / "robot2_map.yaml").resolve()
    assert state["map_yaml_sha256"] == hashlib.sha256((root / "map" / "robot2_map.yaml").read_bytes()).hexdigest()
    assert state["image_sha256"] == hashlib.sha256((root / "map" / "robot2_map.pgm").read_bytes()).hexdigest()
    assert state["map_identity"]


def test_health_ok(client):
    response = client.get("/movement-api/v1/health")
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["simulation_mode"] is True


def test_pose_route_uses_lightweight_localization_refresh(client, monkeypatch):
    runtime.navigator.get_current_pose.return_value = {
        "source": "tf",
        "x": 1.0,
        "y": 2.0,
        "yaw": 0.1,
        "age_sec": 0.02,
    }
    localization_health = MagicMock(return_value={"localized": True, "state": "LOCALIZED"})
    monkeypatch.setattr(robot_context, "localization_health", localization_health)

    response = client.get("/movement-api/v1/robots/tb3_1/pose")

    assert response.status_code == 200
    assert response.json()["localized"] is True
    localization_health.assert_called_once_with(refresh_alignment=False)


def test_endpoints_contract_shape(client):
    response = client.get("/movement-api/v1/endpoints")
    assert response.status_code == 200
    body = response.json()
    for field in ("policy", "active_robot_id", "nav_api_url", "main_api_base", "webhook_endpoint", "resolution", "robots"):
        assert field in body


def test_route_preview_coordinates(client):
    body = b'{"command_id":"preview-1","robot_name":"tb3_1","x":1.0,"y":2.0,"yaw":0.0}'
    # TestClient serializes this compact JSON identically; explicit data keeps the signed raw body exact.
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


def test_real_command_returns_fast_503_while_background_nav2_readiness_is_pending(client, monkeypatch):
    monkeypatch.setenv("SIMULATION_MODE", "0")
    runtime.mission_manager.dry_run = False
    runtime.navigator.nav2_ready = False
    runtime.navigator.ensure_nav2_ready.reset_mock()
    runtime.navigator.start_nav2_readiness_monitor.reset_mock()
    monkeypatch.setattr(robot_context, "localization_health", lambda: {"localized": True})
    monkeypatch.setattr(robot_context, "active_robot_online", lambda: True)
    body = b'{"command_id":"nav2-pending","robot_name":"tb3_1","steps":[{"action":"move_to_point","payload":{"x":1,"y":2}}]}'

    response = client.post(
        "/movement-api/v1/commands",
        content=body,
        headers={
            "content-type": "application/json",
            **sign_headers("test-main-nav-secret", "POST", "/movement-api/v1/commands", body),
        },
    )

    assert response.status_code == 503
    assert response.json()["detail"]["nav2_ready"] is False
    runtime.navigator.start_nav2_readiness_monitor.assert_called_once_with()
    runtime.navigator.ensure_nav2_ready.assert_not_called()


def test_explicit_dry_run_bypasses_localization(client):
    body = b'{"command_id":"localization-dry-run","robot_name":"tb3_1","steps":[{"action":"move_to_point","payload":{"x":1,"y":2,"dry_run":true}}]}'
    response = client.post("/movement-api/v1/commands", content=body, headers={"content-type": "application/json", **sign_headers("test-main-nav-secret", "POST", "/movement-api/v1/commands", body)})
    assert response.status_code == 200


def test_raw_movement_command_cannot_forge_metric_docking_admission(client):
    path = "/movement-api/v1/commands"
    body = (
        b'{"command_id":"raw-metric-bypass","robot_name":"tb3_1","steps":['
        b'{"action":"dock_transfer","payload":{"dry_run":true,"aruco_marker_id":7,'
        b'"action":"load","level":1,"metric_precision_insert":true,'
        b'"return_target_pose":{"x":0,"y":0,"yaw":0}}}]}'
    )
    response = client.post(
        path,
        content=body,
        headers={
            "content-type": "application/json",
            **sign_headers("test-main-nav-secret", "POST", path, body),
        },
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "metric_docking_gate_required"


def test_global_localization_defaults_to_observe_only(client):
    path = "/movement-api/v1/robots/tb3_1/localization/global-search"
    body = b'{"strategy":"observe_only","allow_motion":false}'
    response = client.post(
        path,
        content=body,
        headers={"content-type": "application/json", **sign_headers("test-main-nav-secret", "POST", path, body)},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is True
    assert payload["search"]["motion_started"] is False


def test_explicit_global_localization_restart_replaces_existing_search(client):
    path = "/movement-api/v1/robots/tb3_1/localization/global-search"
    body = b'{"strategy":"observe_only","allow_motion":false,"restart_existing":true}'
    response = client.post(
        path,
        content=body,
        headers={"content-type": "application/json", **sign_headers("test-main-nav-secret", "POST", path, body)},
    )

    assert response.status_code == 200
    request = runtime.navigator.request_global_localization.call_args.args[0]
    assert request["strategy"] == "observe_only"
    assert request["allow_motion"] is False
    assert request["restart_existing"] is True


def test_automatic_localization_uses_profile_policy_once(client):
    runtime.localization = None
    runtime.navigator.request_global_localization.reset_mock()
    runtime.navigator.localization_observation.return_value = None

    first = robot_context.localization_health()
    second = robot_context.localization_health()

    assert first["state"] == "GLOBAL_SEARCH"
    assert second["state"] == "GLOBAL_SEARCH"
    runtime.navigator.request_global_localization.assert_called_once()
    request = runtime.navigator.request_global_localization.call_args.args[0]
    assert request["strategy"] == "observe_only"
    assert request["allow_motion"] is False
    assert request["coarse_consecutive_samples"] == 3
    assert request["fine_consecutive_samples"] == 6
    assert request["max_global_reinitializations"] == 2
    assert request["covariance_limits"] == {"x": 0.25, "y": 0.25, "yaw": 0.35}


def test_global_localization_motion_requires_explicit_permission(client):
    path = "/movement-api/v1/robots/tb3_1/localization/global-search"
    body = b'{"strategy":"bounded_linear_wiggle","allow_motion":false}'
    response = client.post(
        path,
        content=body,
        headers={"content-type": "application/json", **sign_headers("test-main-nav-secret", "POST", path, body)},
    )

    assert response.status_code == 400
