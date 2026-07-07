from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STREAM_GATEWAY = ROOT / "scripts" / "vision" / "run_d1_vision_stream_gateway.py"
DASHBOARD_CHECKER = ROOT / "scripts" / "validate" / "check_main_dashboard_vision_routes.py"


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_stream_gateway_keeps_main_overlay_and_frame_stream_routes_read_only():
    source = STREAM_GATEWAY.read_text(encoding="utf-8")

    assert 'parsed.path == "/api/v1/vision/overlay/stream"' in source
    assert 'parsed.path == "/api/v1/vision/frame/stream"' in source
    assert "def _overlay_upstream_url(" in source
    assert "/api/v1/vision/stream/" in source
    assert "/api/v1/vision/overlay/stream?" in source
    assert "/api/v1/vision/frame/latest?" in source
    assert "/api/v1/vision/frame/latest/image?" in source

    for method_name in ("do_POST", "do_PUT", "do_PATCH", "do_DELETE"):
        method_start = source.index(f"def {method_name}")
        method_body = source[method_start : source.index("\n    def ", method_start + 1)]
        assert "self._method_not_allowed()" in method_body
    assert 'self.send_header("Allow", "GET, OPTIONS")' in source
    assert '"read-only gateway"' in source


def test_stream_gateway_fps_clamp_and_default_source_mapping_are_stable():
    gateway = _load_module(STREAM_GATEWAY, "run_d1_vision_stream_gateway_contract_test")

    assert gateway._clamp_fps("0") == 1.0
    assert gateway._clamp_fps("120") == 30.0
    assert gateway._clamp_fps("15") == 15.0
    assert gateway.DEFAULT_SOURCES["global_cam_01"] == "http://127.0.0.1:8100"
    assert set(gateway.DEFAULT_SOURCES) == {
        "global_cam_01",
        "tb3_1_picam",
        "tb3_2_picam",
    }


def test_main_dashboard_route_checker_accepts_current_dynamic_bundle_fixture():
    checker = _load_module(DASHBOARD_CHECKER, "check_main_dashboard_vision_routes_test")
    fixture = """
      const Zg=(r,s,o=15)=>`/api/v1/vision/${s}/stream?source=${encodeURIComponent(r)}&max_fps=${o}`;
      const streamKinds=["overlay","frame"];
      Zg("global_cam_01","overlay",15);
      Zg("global_cam_01","frame",15);
    """

    result = checker.check_dashboard_text(
        fixture,
        checked_url="http://smartfactory-main.local:8088/",
    )

    assert result.ok is True
    assert result.source == "fixture"
    assert result.checked_url == "http://smartfactory-main.local:8088/"
    assert result.routes == {"overlay": True, "frame": True}


def test_main_dashboard_route_checker_rejects_overlay_only_dynamic_bundle():
    checker = _load_module(
        DASHBOARD_CHECKER,
        "check_main_dashboard_vision_routes_overlay_only_test",
    )
    fixture = """
      const Zg=(r,s,o=15)=>`/api/v1/vision/${s}/stream?source=${encodeURIComponent(r)}&max_fps=${o}`;
      Zg("global_cam_01","overlay",15);
      const unrelatedCopy = "raw frame metrics";
    """

    result = checker.check_dashboard_text(
        fixture,
        checked_url="http://smartfactory-main.local:8088/",
    )

    assert result.ok is False
    assert result.routes == {"overlay": True, "frame": False}


def test_main_dashboard_route_checker_fixture_fallback_cli_succeeds(capsys):
    checker = _load_module(DASHBOARD_CHECKER, "check_main_dashboard_vision_routes_cli_test")
    fixture = (
        "const Zg=(r,s,o=15)=>`/api/v1/vision/${s}/stream?source="
        '${encodeURIComponent(r)}&max_fps=${o}`; const streamKinds=["overlay","frame"];'
    )

    exit_code = checker.main(
        [
            "--url",
            "http://127.0.0.1:9/",
            "--timeout",
            "0.01",
            "--fixture-text",
            fixture,
        ]
    )

    captured = capsys.readouterr().out
    assert exit_code == 0
    assert '"source": "fixture"' in captured
    assert '"overlay": true' in captured
    assert '"frame": true' in captured


def test_main_dashboard_route_checker_does_not_mask_live_route_mismatch(capsys, monkeypatch):
    checker = _load_module(
        DASHBOARD_CHECKER,
        "check_main_dashboard_vision_routes_live_mismatch_test",
    )
    monkeypatch.setattr(
        checker,
        "check_dashboard_url",
        lambda url, timeout: checker.DashboardRouteCheck(
            ok=False,
            source="live",
            routes={"overlay": False, "frame": False},
            checked_url=url,
            error=None,
        ),
    )
    fixture = (
        "const Zg=(r,s,o=15)=>`/api/v1/vision/${s}/stream?source="
        '${encodeURIComponent(r)}&max_fps=${o}`; const streamKinds=["overlay","frame"];'
    )

    exit_code = checker.main(
        [
            "--url",
            "http://smartfactory-main.local:8088/",
            "--fixture-text",
            fixture,
        ]
    )

    captured = capsys.readouterr().out
    assert exit_code == 1
    assert '"source": "live"' in captured
    assert '"overlay": false' in captured
