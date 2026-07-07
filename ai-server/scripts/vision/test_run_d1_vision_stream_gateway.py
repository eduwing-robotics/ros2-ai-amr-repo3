from __future__ import annotations

import importlib.util
import json
import subprocess
from http import HTTPStatus
from pathlib import Path
from types import SimpleNamespace

import pytest

MODULE_PATH = Path(__file__).resolve().parent / "run_d1_vision_stream_gateway.py"
spec = importlib.util.spec_from_file_location("run_d1_vision_stream_gateway", MODULE_PATH)
gateway = importlib.util.module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(gateway)


def test_env_source_upstreams_defaults_to_internal_loopback_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VISION_STREAM_SOURCE_UPSTREAMS_JSON", raising=False)

    assert gateway._env_source_upstreams() == {
        "global_cam_01": "http://127.0.0.1:8100",
        "tb3_1_picam": "http://127.0.0.1:18090",
        "tb3_2_picam": "http://127.0.0.1:18091",
    }


def test_env_source_upstreams_requires_json_object_and_loopback_http_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("VISION_STREAM_SOURCE_UPSTREAMS_JSON", '["http://127.0.0.1:18090"]')
    with pytest.raises(ValueError, match="JSON object"):
        gateway._env_source_upstreams()

    monkeypatch.setenv(
        "VISION_STREAM_SOURCE_UPSTREAMS_JSON",
        json.dumps({"tb3_1_picam": "file:///tmp/not-an-internal-stream"}),
    )
    with pytest.raises(ValueError, match="invalid source upstream mapping"):
        gateway._env_source_upstreams()

    monkeypatch.setenv(
        "VISION_STREAM_SOURCE_UPSTREAMS_JSON",
        json.dumps({"tb3_1_picam": "http://203.0.113.10:18090"}),
    )
    monkeypatch.delenv("VISION_STREAM_ALLOW_NON_LOOPBACK_UPSTREAMS", raising=False)
    with pytest.raises(ValueError, match="invalid source upstream mapping"):
        gateway._env_source_upstreams()

    monkeypatch.setenv("VISION_STREAM_ALLOW_NON_LOOPBACK_UPSTREAMS", "true")
    assert gateway._env_source_upstreams() == {"tb3_1_picam": "http://203.0.113.10:18090"}


def test_clamp_fps_keeps_stream_gateway_bounded() -> None:
    assert gateway._clamp_fps(None) == 30.0
    assert gateway._clamp_fps("bad") == 30.0
    assert gateway._clamp_fps("0") == 1.0
    assert gateway._clamp_fps("120") == 30.0
    assert gateway._clamp_fps("12.5") == 12.5


def test_env_ai_mjpeg_sources_defaults_to_global_source(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VISION_STREAM_AI_MJPEG_SOURCES", raising=False)
    monkeypatch.delenv("VISION_GLOBAL_SOURCE_ID", raising=False)
    assert gateway._env_ai_mjpeg_sources() == {"global_cam_01"}

    monkeypatch.setenv("VISION_GLOBAL_SOURCE_ID", "ceiling_cam")
    assert gateway._env_ai_mjpeg_sources() == {"ceiling_cam"}

    monkeypatch.setenv("VISION_STREAM_AI_MJPEG_SOURCES", "  ")
    assert gateway._env_ai_mjpeg_sources() == {"ceiling_cam"}


def test_env_ai_mjpeg_sources_accepts_explicit_csv(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VISION_STREAM_AI_MJPEG_SOURCES", "global_cam_01, aux_cam ,")
    assert gateway._env_ai_mjpeg_sources() == {"global_cam_01", "aux_cam"}


def test_validate_ai_mjpeg_sources_rejects_unknown_source_role() -> None:
    with pytest.raises(
        ValueError, match="not present in VISION_STREAM_SOURCE_UPSTREAMS_JSON: typo_cam"
    ):
        gateway._validate_ai_mjpeg_sources(
            {"global_cam_01", "typo_cam"},
            {"global_cam_01": "http://127.0.0.1:8100"},
            ai_server_url="http://127.0.0.1:8100",
        )


def test_validate_ai_mjpeg_sources_requires_ai_server_upstream_kind() -> None:
    with pytest.raises(ValueError, match="must use AI_SERVER_URL as upstream: global_cam_01"):
        gateway._validate_ai_mjpeg_sources(
            {"global_cam_01"},
            {"global_cam_01": "http://127.0.0.1:18090"},
            ai_server_url="http://127.0.0.1:8100",
        )

    gateway._validate_ai_mjpeg_sources(
        {"global_cam_01"},
        {"global_cam_01": "http://127.0.0.1:8100/"},
        ai_server_url="http://127.0.0.1:8100",
    )


def test_stream_gateway_server_validates_ai_source_role_against_upstream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "VISION_STREAM_SOURCE_UPSTREAMS_JSON",
        json.dumps({"global_cam_01": "http://127.0.0.1:18090"}),
    )
    monkeypatch.setenv("VISION_STREAM_AI_MJPEG_SOURCES", "global_cam_01")
    monkeypatch.setenv("AI_SERVER_URL", "http://127.0.0.1:8100")

    with pytest.raises(ValueError, match="must use AI_SERVER_URL as upstream"):
        gateway.VisionStreamGatewayServer(("127.0.0.1", 0), gateway.VisionStreamGatewayHandler)


def test_stream_gateway_server_allows_current_default_source_route_matrix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("VISION_STREAM_SOURCE_UPSTREAMS_JSON", raising=False)
    monkeypatch.delenv("VISION_STREAM_AI_MJPEG_SOURCES", raising=False)
    monkeypatch.delenv("VISION_GLOBAL_SOURCE_ID", raising=False)
    monkeypatch.delenv("AI_SERVER_URL", raising=False)

    server = gateway.VisionStreamGatewayServer(("127.0.0.1", 0), gateway.VisionStreamGatewayHandler)
    try:
        assert server.ai_mjpeg_sources == {"global_cam_01"}
        assert server.source_upstreams["tb3_1_picam"] == "http://127.0.0.1:18090"
        assert server.source_upstreams["tb3_2_picam"] == "http://127.0.0.1:18091"
    finally:
        server.server_close()


def test_overlay_upstream_url_routes_global_source_to_ai_server_view_endpoint() -> None:
    assert gateway._overlay_upstream_url(
        upstream_base_url="http://127.0.0.1:8100",
        ai_mjpeg_sources={"global_cam_01"},
        source="global_cam_01",
        view="lift_roi",
        max_fps=12.5,
    ) == (
        "http://127.0.0.1:8100/api/v1/vision/stream/global_cam_01.mjpeg?view=lift_roi&max_fps=12.5"
    )


def test_overlay_upstream_url_routes_robot_source_to_domain_overlay_bridge() -> None:
    assert (
        gateway._overlay_upstream_url(
            upstream_base_url="http://127.0.0.1:18090",
            ai_mjpeg_sources={"global_cam_01"},
            source="tb3_1_picam",
            view="full",
            max_fps=30.0,
        )
        == "http://127.0.0.1:18090/api/v1/vision/overlay/stream?source=tb3_1_picam&max_fps=30"
    )


def test_overlay_upstream_url_uses_explicit_source_role_not_upstream_url_alias() -> None:
    assert gateway._overlay_upstream_url(
        upstream_base_url="http://smartfactory-vision.local:8100",
        ai_mjpeg_sources={"global_cam_01"},
        source="tb3_1_picam",
        view="full",
        max_fps=15.0,
    ) == (
        "http://smartfactory-vision.local:8100/api/v1/vision/overlay/stream"
        "?source=tb3_1_picam&max_fps=15"
    )


def test_overlay_upstream_url_keeps_future_second_robot_on_domain_overlay_bridge() -> None:
    assert (
        gateway._overlay_upstream_url(
            upstream_base_url="http://127.0.0.1:18091",
            ai_mjpeg_sources={"global_cam_01"},
            source="tb3_2_picam",
            view="full",
            max_fps=30.0,
        )
        == "http://127.0.0.1:18091/api/v1/vision/overlay/stream?source=tb3_2_picam&max_fps=30"
    )


class _MethodCaptureHandler(gateway.VisionStreamGatewayHandler):
    def __init__(self) -> None:
        self.responses: list[int] = []
        self.headers: list[tuple[str, str]] = []
        self.wfile = SimpleNamespace(payload=b"")
        self.wfile.write = lambda data: setattr(self.wfile, "payload", self.wfile.payload + data)

    def send_response(self, code: int, message: str | None = None) -> None:  # type: ignore[override]
        self.responses.append(code)

    def send_header(self, keyword: str, value: str) -> None:  # type: ignore[override]
        self.headers.append((keyword, value))

    def end_headers(self) -> None:  # type: ignore[override]
        return None


def test_mutating_http_methods_are_read_only() -> None:
    handler = _MethodCaptureHandler()

    handler.do_POST()

    assert handler.responses == [HTTPStatus.METHOD_NOT_ALLOWED.value]
    assert ("Allow", "GET, OPTIONS") in handler.headers
    assert json.loads(handler.wfile.payload.decode("utf-8")) == {
        "ok": False,
        "error": "read-only gateway",
    }


def test_multi_source_bundle_print_config_keeps_source_bridges_loopback_only() -> None:
    result = subprocess.run(
        ["bash", "scripts/vision/run_d1_vision_multi_source_gateway_bundle.sh", "--print-config"],
        check=True,
        cwd=Path(__file__).resolve().parents[2],
        text=True,
        capture_output=True,
    )

    assert "public_gateway: 0.0.0.0:8090" in result.stdout
    assert '"global_cam_01":"http://127.0.0.1:8100"' in result.stdout
    assert '"tb3_1_picam":"http://127.0.0.1:18090"' in result.stdout
    assert '"tb3_2_picam":"http://127.0.0.1:18091"' in result.stdout
    assert "ai_mjpeg_sources: global_cam_01" in result.stdout
    assert "http://0.0.0.0:8100" not in result.stdout
    assert "http://0.0.0.0:18090" not in result.stdout
    assert "http://0.0.0.0:18091" not in result.stdout
