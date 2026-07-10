from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path

from fastapi.testclient import TestClient
from generated_fixtures import aruco_png_bytes

from app.config import get_settings
from app.factory import create_app
from app.runtime_state import create_runtime_context

FRAME_IMAGE = aruco_png_bytes()

AUTH_HELPER = (
    Path(__file__).resolve().parents[1]
    / "ros2/smartfactory_perception_ros/smartfactory_perception_ros/vision_frame_gateway_auth.py"
)


def _load_auth_helper():
    spec = importlib.util.spec_from_file_location("vision_frame_gateway_auth_test", AUTH_HELPER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _frame_request(helper, secret: str, client: TestClient | None = None):
    if client is not None:
        request = client.build_request(
            "POST",
            "/api/v1/vision/frame/process",
            data={"source": "tb3_1_picam", "force": "true", "stale": "false"},
            files={"image": ("frame.png", FRAME_IMAGE, "image/png")},
        )
        body = request.read()
        request.headers.update(
            helper.build_gateway_auth_headers(
                secret=secret,
                method=request.method,
                url=str(request.url),
                body=body,
                timestamp=str(int(time.time())),
                nonce="gateway-frame-once",
            )
        )
        return request
    boundary = "gateway-test-boundary"
    body = (
        f"--{boundary}\r\n"
        "Content-Disposition: form-data; name=\"source\"\r\n\r\n"
        "tb3_1_picam\r\n"
        f"--{boundary}\r\n"
        "Content-Disposition: form-data; name=\"force\"\r\n\r\ntrue\r\n"
        f"--{boundary}\r\n"
        "Content-Disposition: form-data; name=\"stale\"\r\n\r\nfalse\r\n"
        f"--{boundary}\r\n"
        "Content-Disposition: form-data; name=\"image\"; filename=\"frame.png\"\r\n"
        "Content-Type: image/png\r\n\r\n"
    ).encode() + FRAME_IMAGE + f"\r\n--{boundary}--\r\n".encode()
    headers = {
        "Content-Type": f"multipart/form-data; boundary={boundary}",
        **helper.build_gateway_auth_headers(
            secret=secret,
            method="POST",
            url="http://testserver/api/v1/vision/frame/process",
            body=body,
            timestamp=str(int(time.time())),
            nonce="gateway-frame-once",
        ),
    }
    return body, headers


def test_ros_free_auth_helper_signs_exact_multipart_body_without_importing_rclpy():
    helper = _load_auth_helper()
    _body, headers = _frame_request(helper, "gateway-secret")

    assert headers[helper.HEADER_GATEWAY_SIGNATURE]
    assert headers[helper.HEADER_TIMESTAMP]
    assert headers[helper.HEADER_NONCE] == "gateway-frame-once"


def test_gateway_frame_ingress_accepts_signed_request_and_rejects_unsigned_or_replayed(monkeypatch):
    helper = _load_auth_helper()
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_debug_mutations_enabled", False)
    monkeypatch.setattr(settings, "vision_gateway_hmac_secret", "gateway-secret")
    context = create_runtime_context()
    client = TestClient(create_app(runtime_context=context))
    path = "/api/v1/vision/frame/process"

    # Unsigned ingress cannot seed the cache.
    assert client.post(path, data={"source": "tb3_1_picam"}, files={"image": ("x.jpg", b"x")}).status_code == 401
    assert context.frame_store.latest("tb3_1_picam") is None

    request = _frame_request(helper, "gateway-secret", client)
    response = client.send(request)
    assert response.status_code == 200
    accepted = context.frame_store.latest("tb3_1_picam")
    assert accepted is not None

    # Replaying the exact multipart request is rejected before cache mutation.
    assert client.send(request).status_code == 401
    assert context.frame_store.latest("tb3_1_picam").frame_seq == accepted.frame_seq


def test_gateway_frame_ingress_fails_closed_when_credential_is_missing(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "ai_debug_mutations_enabled", False)
    monkeypatch.setattr(settings, "vision_gateway_hmac_secret", "")
    context = create_runtime_context()

    response = TestClient(create_app(runtime_context=context)).post(
        "/api/v1/vision/frame",
        data={"source": "tb3_1_picam"},
        files={"image": ("frame.jpg", b"jpeg-frame", "image/jpeg")},
    )

    assert response.status_code == 503
    assert context.frame_store.latest("tb3_1_picam") is None
