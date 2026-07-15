from __future__ import annotations

import hashlib
import hmac
import json
import time

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.factory import create_app
from app.runtime_state import create_runtime_context


def _headers(
    secret: str, method: str, path: str, body: bytes, *, nonce: str = "auth-test-nonce"
) -> dict[str, str]:
    timestamp = str(int(time.time()))
    payload = "\n".join((method, path, timestamp, nonce, hashlib.sha256(body).hexdigest())).encode()
    return {"X-SF-Timestamp": timestamp, "X-SF-Nonce": nonce, "X-SF-Signature": hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest(), "Content-Type": "application/json"}


def test_production_mutations_fail_closed_and_reject_replays(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "main_hmac_secret", "")
    client = TestClient(create_app())
    monitor_path = "/api/v1/vision/monitors/person_drive/state"
    monitor_body = json.dumps({"enabled": False}, separators=(",", ":")).encode()
    debug_path = "/api/v1/vision/synthetic/frame"
    debug_body = json.dumps({"source": "tb3_1_picam"}, separators=(",", ":")).encode()

    # Public discovery remains public, but every evidence-affecting ingress is closed.
    assert client.get("/api/v1/vision/streams").status_code == 200
    assert client.post(debug_path, content=debug_body).status_code == 503
    assert client.post("/api/v1/evidence/evaluate", json={"source": "tb3_1_picam"}).status_code == 503
    assert client.put(monitor_path, content=monitor_body).status_code == 503

    monkeypatch.setattr(settings, "main_hmac_secret", "shared-secret")
    assert client.post(debug_path, content=debug_body).status_code == 401
    response = client.post(
        debug_path,
        content=debug_body,
        headers=_headers("shared-secret", "POST", debug_path, debug_body),
    )
    assert response.status_code == 200
    # A replay cannot change the evidence cache a second time.
    assert (
        client.post(
            debug_path,
            content=debug_body,
            headers=_headers("shared-secret", "POST", debug_path, debug_body),
        ).status_code
        == 401
    )


def test_debug_mutations_have_no_unauthenticated_fixture_exception(monkeypatch):
    settings = get_settings()
    assert not hasattr(settings, "ai_debug_mutations_enabled")
    monkeypatch.setattr(settings, "main_hmac_secret", "")
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/vision/synthetic/frame",
        json={"source": "tb3_2_picam", "marker_id": 7},
    )

    assert response.status_code == 503


@pytest.mark.parametrize(
    ("path", "request_kwargs"),
    [
        ("/api/v1/vision/worker/tick", {"json": {}}),
        ("/api/v1/vision/synthetic/frame", {"json": {"source": "tb3_1_picam"}}),
        ("/api/v1/evidence/evaluate", {"json": {"source": "tb3_1_picam"}}),
        (
            "/api/v1/vision/frame",
            {"data": {"source": "tb3_1_picam"}, "files": {"image": ("frame.jpg", b"jpeg")}},
        ),
        (
            "/api/v1/vision/frame/process",
            {"data": {"source": "tb3_1_picam"}, "files": {"image": ("frame.jpg", b"jpeg")}},
        ),
        (
            "/api/v1/detect/image",
            {"data": {"source": "tb3_1_picam"}, "files": {"image": ("frame.jpg", b"jpeg")}},
        ),
    ],
)
def test_all_debug_evidence_ingress_routes_require_hmac_in_production(
    monkeypatch, path, request_kwargs
):
    settings = get_settings()
    monkeypatch.setattr(settings, "main_hmac_secret", "shared-secret")

    response = TestClient(create_app()).post(path, **request_kwargs)

    # Frame cache ingress has a separate scoped gateway credential and fails
    # closed when it is absent; every other debug mutation uses Main HMAC.
    expected_status = 503 if path.startswith("/api/v1/vision/frame") else 401
    assert response.status_code == expected_status


def test_signed_evidence_cannot_consume_an_unauthenticated_injected_frame(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "main_hmac_secret", "shared-secret")
    context = create_runtime_context()
    client = TestClient(create_app(runtime_context=context))
    frame_path = "/api/v1/vision/synthetic/frame"
    frame_body = json.dumps({"source": "tb3_1_picam"}, separators=(",", ":")).encode()

    assert client.post(frame_path, content=frame_body).status_code == 401
    assert context.frame_store.latest("tb3_1_picam") is None

    evaluation_path = "/api/v1/evidence/evaluate"
    evaluation_body = json.dumps({"source": "tb3_1_picam"}, separators=(",", ":")).encode()
    response = client.post(
        evaluation_path,
        content=evaluation_body,
        headers=_headers(
            "shared-secret", "POST", evaluation_path, evaluation_body, nonce="evidence-request"
        ),
    )

    assert response.status_code == 200
    assert response.json()["reason_code"] == "NO_FRAME"
