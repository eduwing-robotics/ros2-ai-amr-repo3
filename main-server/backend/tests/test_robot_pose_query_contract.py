"""Robot pose reads must never cross map identities."""

from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routers import robot_poses
from app.services.pose_runtime import PoseRuntime


def _snapshot(robot_id: str, map_id: str) -> dict:
    return {
        "robot_id": robot_id,
        "map_id": map_id,
        "x": 1.0,
        "y": 2.0,
        "yaw": 0.0,
        "linear_velocity": None,
        "angular_velocity": None,
        "source": "ros_tf",
        "command_id": None,
        "source_reported_at": None,
        "received_at": "2026-07-15T00:00:00Z",
        "source_age_sec": None,
        "receive_age_sec": 0.0,
        "source_state": "unknown",
        "receive_state": "live",
        "pose_state": "live",
        "localized": True,
        "in_bounds": True,
        "quality_reasons": [],
        "version": 1,
    }


def test_robot_poses_query_returns_only_matching_map_identity() -> None:
    app = FastAPI()
    app.include_router(robot_poses.router)
    snapshots = [
        _snapshot("tb3_1", "robot2_map"),
        _snapshot("tb3_2", "another_map"),
    ]

    with (
        TestClient(app) as client,
        patch.object(robot_poses.pose_runtime, "list_snapshots", return_value=snapshots),
    ):
        matching = client.get("/robot-poses?map_id=robot2_map")
        mismatch = client.get("/robot-poses?map_id=missing_map")
        all_maps = client.get("/robot-poses")

    assert matching.status_code == 200
    assert [row["robot_id"] for row in matching.json()] == ["tb3_1"]
    assert mismatch.status_code == 200
    assert mismatch.json() == []
    assert all_maps.status_code == 200
    assert [row["robot_id"] for row in all_maps.json()] == ["tb3_1", "tb3_2"]


def test_canonical_pose_ingest_rejects_wrong_runtime_map() -> None:
    runtime = PoseRuntime()
    runtime.configure({"tb3_1"}, {"active_map_id": "robot2_map"})
    app = FastAPI()
    app.include_router(robot_poses.router)
    app.dependency_overrides[robot_poses.require_nav_callback_signature] = lambda: None

    with TestClient(app) as client, patch.object(robot_poses, "pose_runtime", runtime):
        wrong_map = client.post(
            "/robots/tb3_1/pose",
            json={"map_id": "another_map", "x": 1.0, "y": 2.0},
        )
        assert runtime.list_snapshots() == []
        correct_map = client.post(
            "/robots/tb3_1/pose",
            json={"map_id": "robot2_map", "x": 1.0, "y": 2.0},
        )

    assert wrong_map.status_code == 422
    assert "map_id" in wrong_map.json()["detail"]
    assert correct_map.status_code == 200
    assert runtime.list_snapshots()[0]["map_id"] == "robot2_map"
