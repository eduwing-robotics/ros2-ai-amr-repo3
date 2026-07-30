"""HMAC boundary tests for Main-controlled Nav mutations."""
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nav_app.security import sign_headers
from nav_app.server_core import register_app
from tests.contracts.test_fastapi_contract import _mock_startup


@pytest.fixture
def nav_client(monkeypatch):
    monkeypatch.setenv("SIMULATION_MODE", "1")
    app = FastAPI(title="auth-test")
    register_app(app)
    _mock_startup()
    with TestClient(app) as client:
        yield client


def _headers(path, body, *, secret="test-main-nav-secret", timestamp=None, nonce=None):
    signed = sign_headers(secret, "POST", path, body) if timestamp is None else _signed(secret, path, body, timestamp, nonce)
    return {"content-type": "application/json", **signed}


def _signed(secret, path, body, timestamp, nonce):
    import hashlib
    import hmac
    from nav_app.security import HEADER_NONCE, HEADER_SIGNATURE, HEADER_TIMESTAMP, _payload
    nonce = nonce or "nonce-for-test"
    stamp = str(timestamp)
    return {HEADER_TIMESTAMP: stamp, HEADER_NONCE: nonce, HEADER_SIGNATURE: hmac.new(secret.encode(), _payload("POST", path, stamp, nonce, body), hashlib.sha256).hexdigest()}


def test_mutation_rejects_unsigned_wrong_stale_and_replay(nav_client, monkeypatch):
    client = nav_client
    monkeypatch.setenv("NAV_MAIN_HMAC_SECRET", "test-main-nav-secret")
    path = "/movement-api/v1/routes/preview"
    body = b'{"command_id":"auth-1","robot_name":"tb3_1","x":1,"y":2,"yaw":0}'
    assert client.post(path, content=body, headers={"content-type": "application/json"}).status_code == 401
    assert client.post(path, content=body, headers=_headers(path, body, secret="wrong-secret")).status_code == 403
    assert client.post(path, content=body, headers=_headers(path, body, timestamp=1)).status_code == 401
    headers = _headers(path, body)
    assert client.post(path, content=body, headers=headers).status_code == 200
    assert client.post(path, content=body, headers=headers).status_code == 401


def test_missing_secret_fails_closed(nav_client, monkeypatch):
    client = nav_client
    monkeypatch.delenv("NAV_MAIN_HMAC_SECRET", raising=False)
    monkeypatch.delenv("LMS_MOVEMENT_HMAC_SECRET", raising=False)
    assert client.post("/movement-api/v1/routes/preview", json={}).status_code == 503


def test_robot_command_cancel_requires_hmac_and_rejects_replay(nav_client, monkeypatch):
    from nav_app.runtime import runtime

    monkeypatch.setenv("NAV_MAIN_HMAC_SECRET", "test-main-nav-secret")
    path = "/robot-commands/cmd-cancel-auth/cancel"
    body = b"{}"
    runtime.movement_commands["cmd-cancel-auth"] = {
        "command_id": "cmd-cancel-auth",
        "task_id": 42,
        "robot_name": "tb3_1",
        "state": "ACCEPTED",
        "traffic_segments": [],
    }

    assert nav_client.post(path, content=body, headers={"content-type": "application/json"}).status_code == 401
    headers = _headers(path, body)
    response = nav_client.post(path, content=body, headers=headers)
    assert response.status_code == 200
    assert response.json()["state"] == "CANCELED"
    assert nav_client.post(path, content=body, headers=headers).status_code == 401


def test_retired_manual_override_cannot_bypass_busy_autonomy(nav_client, monkeypatch):
    import json

    from nav_app.runtime import runtime
    from nav_app.services import manual_control, robot_context

    monkeypatch.setenv("NAV_MAIN_HMAC_SECRET", "test-main-nav-secret")
    monkeypatch.setattr(manual_control, "_is_busy", lambda: True)
    path = "/movement-api/v1/manual/translate"
    body = json.dumps(
        {
            "robot_name": robot_context.active_bridge_robot_id(),
            "direction": "forward",
            "duration_sec": 0.2,
            "linear_x": 0.1,
            "override_nav": True,
        },
        separators=(",", ":"),
    ).encode()

    response = nav_client.post(path, content=body, headers=_headers(path, body))

    assert response.status_code == 409
    assert "canonical command cancel" in response.json()["detail"]
    runtime.navigator.nav.cancelTask.assert_not_called()


def test_arrived_docking_gate_is_exposed_for_teleop_safe_cancel(nav_client):
    from nav_app.runtime import runtime
    from nav_app.services import robot_context

    robot_name = robot_context.active_bridge_robot_id()
    runtime.movement_commands["cmd-arrived"] = {
        "command_id": "cmd-arrived",
        "robot_name": robot_name,
        "state": "ARRIVED",
    }

    response = nav_client.get(
        f"/movement-api/v1/robots/{robot_name}/nav-state"
    )

    assert response.status_code == 200
    assert "cmd-arrived" in response.json()["active_commands"]


@pytest.mark.parametrize(
    ("stop_result", "expected_confirmed", "expected_state"),
    [
        (
            {
                "nav_cancelled": True,
                "base_stopped": True,
                "lift_stopped": True,
                "confirmed": True,
            },
            True,
            "STOPPED",
        ),
        (
            {
                "nav_cancelled": True,
                "base_stopped": False,
                "lift_stopped": True,
                "confirmed": False,
            },
            False,
            "STOP_UNCONFIRMED",
        ),
    ],
)
def test_manual_stop_reports_shared_physical_confirmation(
    nav_client,
    monkeypatch,
    stop_result,
    expected_confirmed,
    expected_state,
):
    import json

    from nav_app.routers import movement_api
    from nav_app.services import robot_context

    monkeypatch.setenv("NAV_MAIN_HMAC_SECRET", "test-main-nav-secret")
    monkeypatch.setattr(movement_api, "stop_active_motion", lambda: stop_result)
    path = "/movement-api/v1/manual/stop"
    body = json.dumps(
        {"robot_name": robot_context.active_bridge_robot_id()},
        separators=(",", ":"),
    ).encode()

    response = nav_client.post(path, content=body, headers=_headers(path, body))

    assert response.status_code == 200
    payload = response.json()
    assert payload["accepted"] is expected_confirmed
    assert payload["stopped"] is expected_confirmed
    assert payload["state"] == expected_state
    assert payload["stop_result"] == stop_result


def test_legacy_mission_start_is_disabled_by_default(nav_client, monkeypatch):
    monkeypatch.delenv("NAV_LEGACY_MISSION_START_ENABLED", raising=False)
    response = nav_client.post(
        "/mission/start",
        json={"robot_id": "tb3_burger_01", "item_name": "box", "mission_type": "inbound"},
    )
    assert response.status_code == 410


def test_enabled_legacy_mission_requires_hmac_and_rejects_replay(nav_client, monkeypatch):
    monkeypatch.setenv("NAV_LEGACY_MISSION_START_ENABLED", "1")
    monkeypatch.setenv("NAV_MAIN_HMAC_SECRET", "test-main-nav-secret")
    path = "/mission/start"
    body = b'{"robot_id":"tb3_burger_01","item_name":"box","mission_type":"inbound"}'

    assert nav_client.post(path, content=body, headers={"content-type": "application/json"}).status_code == 401
    headers = _headers(path, body)
    first = nav_client.post(path, content=body, headers=headers)
    assert first.status_code != 401
    assert nav_client.post(path, content=body, headers=headers).status_code == 401


def test_enabled_legacy_mission_requires_fresh_localization(nav_client, monkeypatch):
    from nav_app.runtime import runtime

    monkeypatch.setenv("NAV_LEGACY_MISSION_START_ENABLED", "1")
    monkeypatch.setenv("NAV_MAIN_HMAC_SECRET", "test-main-nav-secret")
    monkeypatch.setenv("SIMULATION_MODE", "0")
    runtime.mission_manager.dry_run = False
    path = "/mission/start"
    body = b'{"robot_id":"tb3_burger_01","item_name":"box","mission_type":"inbound"}'

    response = nav_client.post(path, content=body, headers=_headers(path, body))
    assert response.status_code == 409
    assert response.json()["detail"]["message"] == "legacy mission requires fresh localization state"


def test_enabled_legacy_mission_still_rejects_business_work_after_real_admission(nav_client, monkeypatch):
    from nav_app.runtime import runtime
    from nav_app.services import mission_helpers

    monkeypatch.setenv("NAV_LEGACY_MISSION_START_ENABLED", "1")
    monkeypatch.setenv("NAV_MAIN_HMAC_SECRET", "test-main-nav-secret")
    monkeypatch.setattr(
        mission_helpers.robot_context,
        "localization_health",
        lambda: {"localized": True, "scan_age_sec": 0.0, "tf_age_sec": 0.0},
    )
    monkeypatch.setattr(
        mission_helpers.robot_context,
        "localization_gate",
        lambda: SimpleNamespace(config={"max_scan_age_sec": 1.0, "max_tf_age_sec": 1.0}),
    )
    monkeypatch.setattr(mission_helpers.robot_context, "active_robot_online", lambda: True)
    runtime.navigator.ensure_nav2_ready.return_value = True
    path = "/mission/start"
    body = b'{"robot_id":"tb3_burger_01","item_name":"box","mission_type":"inbound"}'

    response = nav_client.post(path, content=body, headers=_headers(path, body))
    assert response.status_code == 410
    runtime.mission_manager.accept_mission.assert_not_called()


def test_lock_diagnostic_gets_are_public_read_only(nav_client, monkeypatch):
    monkeypatch.delenv("NAV_MAIN_HMAC_SECRET", raising=False)
    monkeypatch.delenv("LMS_MOVEMENT_HMAC_SECRET", raising=False)

    assert nav_client.get("/traffic/locks").status_code == 200
    assert nav_client.get("/zones/locks").status_code == 200


@pytest.mark.parametrize("path", ["/traffic/lock", "/traffic/release", "/zones/lock", "/zones/release"])
def test_traffic_and_zone_mutations_require_hmac_and_reject_replay(nav_client, monkeypatch, path):
    monkeypatch.setenv("NAV_MAIN_HMAC_SECRET", "test-main-nav-secret")
    body = b"{}"

    assert nav_client.post(path, content=body, headers={"content-type": "application/json"}).status_code == 401
    headers = _headers(path, body)
    # Authentication runs before request-model validation, so this proves a valid
    # signature was consumed even though the intentionally incomplete payload is 422.
    assert nav_client.post(path, content=body, headers=headers).status_code == 422
    assert nav_client.post(path, content=body, headers=headers).status_code == 401
