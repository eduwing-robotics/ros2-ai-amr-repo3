"""ROS pose bridge must use the canonical signed trusted-site ingress."""

from __future__ import annotations

import json
from dataclasses import replace
from unittest.mock import MagicMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from tools.ros_pose_bridge import ros_pose_bridge as bridge

from app.api.routers import movement, robot_poses
from app.services.pose_runtime import PoseRuntime


def _pose() -> dict:
    return {"map_id": "robot2_map", "x": 1.0, "y": 2.0, "yaw": 0.3}


def test_bridge_defaults_use_canonical_site_map_and_host():
    cfg = bridge.BridgeConfig(robot_id="tb3_1")

    assert cfg.map_id == "robot2_map"
    assert cfg.api_base == "http://smartfactory-main.local:8088/api/v1"


def test_bridge_fails_closed_without_movement_hmac_secret(monkeypatch):
    monkeypatch.delenv("NAV_MAIN_HMAC_SECRET", raising=False)
    monkeypatch.delenv("LMS_MOVEMENT_HMAC_SECRET", raising=False)
    cfg = bridge.BridgeConfig(robot_id="tb3_1")

    with patch.object(bridge, "urlopen") as urlopen:
        ok, detail = bridge.post_pose(cfg, _pose())

    assert ok is False
    assert "HMAC secret" in detail
    urlopen.assert_not_called()


def test_bridge_posts_canonical_body_with_signature_headers(monkeypatch):
    monkeypatch.setenv("NAV_MAIN_HMAC_SECRET", "pose-secret")
    cfg = bridge.BridgeConfig(robot_id="tb3_1")
    response = MagicMock(status=200)
    response.__enter__.return_value = response

    with (
        patch.object(bridge, "sign_headers", return_value={"X-SF-Signature": "signed"}) as sign,
        patch.object(bridge, "urlopen", return_value=response) as urlopen,
    ):
        ok, detail = bridge.post_pose(cfg, _pose())

    assert ok is True
    assert detail == "HTTP 200"
    request = urlopen.call_args.args[0]
    body = json.dumps(_pose()).encode("utf-8")
    sign.assert_called_once_with("pose-secret", "POST", cfg.pose_url, body)
    assert request.data == body
    assert dict(request.header_items())["X-sf-signature"] == "signed"


def test_bridge_signature_is_accepted_by_canonical_pose_route(monkeypatch):
    secret = "pose-secret"
    monkeypatch.setenv("NAV_MAIN_HMAC_SECRET", secret)
    cfg = bridge.BridgeConfig(robot_id="tb3_1")
    body = json.dumps(_pose()).encode("utf-8")
    headers = bridge.pose_headers(cfg, body)
    runtime = PoseRuntime()
    runtime.configure({"tb3_1"}, {"active_map_id": "robot2_map"})
    app = FastAPI()
    app.include_router(robot_poses.router, prefix="/api/v1")

    with (
        patch.object(
            movement,
            "settings",
            replace(movement.settings, movement_hmac_secret=secret),
        ),
        patch.object(movement, "_callback_replay_cache", movement.ReplayCache()),
        patch.object(robot_poses, "pose_runtime", runtime),
        TestClient(app) as client,
    ):
        unsigned = client.post(
            "/api/v1/robots/tb3_1/pose",
            content=body,
            headers={"content-type": "application/json"},
        )
        signed = client.post(
            "/api/v1/robots/tb3_1/pose",
            content=body,
            headers=headers,
        )

    assert unsigned.status_code == 401
    assert signed.status_code == 200
    assert runtime.list_snapshots()[0]["map_id"] == "robot2_map"
