from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from nav_app.runtime import runtime
from nav_app.server_core import register_app


def test_pose_and_nav_state_share_readiness_without_server_error(monkeypatch):
    from nav_app.routers import movement_api

    pose = {
        "source": "tf",
        "frame_id": "map",
        "child_frame_id": "base_link",
        "x": 1.0,
        "y": 2.0,
        "yaw": 0.5,
        "age_sec": 0.2,
    }
    navigator = MagicMock()
    navigator.get_current_pose.return_value = pose
    navigator.nav2_ready = True
    navigator.status = "IDLE"
    navigator.safety.estop = False
    navigator.has_amcl_pose.return_value = True
    navigator.has_simulated_pose.return_value = False
    navigator.cmd_vel_subscribers.return_value = []
    mission_manager = MagicMock(dry_run=False, mission_status="IDLE")
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(runtime, "mission_manager", mission_manager)
    monkeypatch.setattr(runtime, "movement_commands", {})
    monkeypatch.setattr(movement_api.robot_context, "active_bridge_robot_id", lambda: "tb3_2")
    monkeypatch.setattr(movement_api.robot_context, "active_robot_online", lambda: True)

    app = FastAPI()
    register_app(app)
    client = TestClient(app)
    pose_response = client.get("/movement-api/v1/robots/tb3_2/pose")
    nav_state_response = client.get("/movement-api/v1/robots/tb3_2/nav-state")

    assert pose_response.status_code == 200
    assert pose_response.json()["localized"] is True
    assert pose_response.json()["pose_fresh"] is True
    assert pose_response.json()["pose_in_map"] is True
    assert pose_response.json()["pose"] == pose
    assert nav_state_response.status_code == 200
    assert nav_state_response.json()["reason"] == "ok"


def test_readiness_marks_stale_pose(monkeypatch):
    from nav_app.services import robot_context

    navigator = MagicMock()
    navigator.get_current_pose.return_value = {"frame_id": "map", "age_sec": 5.1}
    navigator.nav2_ready = True
    monkeypatch.setattr(runtime, "navigator", navigator)
    monkeypatch.setattr(runtime, "mission_manager", MagicMock(dry_run=False))
    monkeypatch.setattr(robot_context, "active_robot_online", lambda: True)

    readiness = robot_context.readiness_snapshot()

    assert readiness["pose_fresh"] is False
    assert readiness["reason"] == "pose_stale"
