import ast
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from app.factory import create_app
from app.main import app

ROOT = Path(__file__).resolve().parents[1]
SERVICE_DIR = ROOT

client = TestClient(app)


def test_main_dashboard_origin_is_allowed_by_cors():
    response = client.options(
        "/api/v1/vision/streams",
        headers={
            "Origin": "http://smartfactory-main.local:8088",
            "Access-Control-Request-Method": "GET",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == (
        "http://smartfactory-main.local:8088"
    )


def test_factory_creates_runtime_app_without_generator_bridge():
    from app.service_metadata import SERVICE_VERSION

    factory_app = create_app()
    route_paths = {getattr(route, "path", "") for route in factory_app.routes}

    assert factory_app.title == "SmartFactory AI Server"
    assert factory_app.version == SERVICE_VERSION
    assert "/api/v1/health" in route_paths
    assert "/api/v1/vision/streams" in route_paths
    assert "/api/v1/vision/streams/{source}/webrtc/offer" in route_paths


def test_source_registry_generator_uses_factory_seam_not_main_app_import():
    script = (ROOT / "scripts" / "generate" / "generate_source_registry_surfaces.py").read_text(
        encoding="utf-8"
    )

    assert "from app.factory import create_app" in script
    assert "from app.main import app" not in script
    assert "include_runtime_routes" not in script


def test_app_factory_has_no_temporary_runtime_bridge():
    factory_source = (SERVICE_DIR / "app" / "factory.py").read_text(encoding="utf-8")

    assert "include_runtime_routes" not in factory_source
    assert "from .main" not in factory_source


def test_runtime_state_default_context_preserves_compatibility_aliases():
    from app import runtime_state

    context = runtime_state.default_runtime_context
    assert runtime_state.store is context.store
    assert runtime_state.source_health is context.source_health
    assert runtime_state.metrics is context.metrics
    assert runtime_state.frame_store is context.frame_store
    assert runtime_state.overlay_cache is context.overlay_cache
    assert runtime_state._overlay_images is context.overlay_images
    assert runtime_state._overlay_images_lock is context.overlay_images_lock


def test_app_factory_accepts_injected_runtime_context():
    from app.runtime_state import create_runtime_context, default_runtime_context

    default_before = default_runtime_context.metrics.snapshot()["http"]["request_total"]
    injected_context = create_runtime_context()
    injected_app = create_app(runtime_context=injected_context)
    injected_client = TestClient(injected_app)

    response = injected_client.get("/api/v1/health")

    assert response.status_code == 200
    assert injected_app.state.runtime_context is injected_context
    assert injected_context is not default_runtime_context
    assert injected_context.metrics.snapshot()["http"]["request_total"] >= 1
    assert default_runtime_context.metrics.snapshot()["http"]["request_total"] == default_before


def test_injected_runtime_context_is_preserved_for_mjpeg_generator():
    import asyncio

    from app import runtime_routes
    from app.overlay import OverlayRenderResult
    from app.runtime_state import create_runtime_context, default_runtime_context

    injected_context = create_runtime_context()
    default_before = default_runtime_context.metrics.stream_snapshot()["frames_sent_total"]
    overlay = OverlayRenderResult(
        source="tb3_1_picam",
        frame_seq=1,
        frame_timestamp="2026-06-18T00:00:00+00:00",
        evidence_timestamp=None,
        overlay_timestamp="2026-06-18T00:00:01+00:00",
        latency_ms=None,
        event_count=0,
        stale=False,
        image_width=1,
        image_height=1,
        jpeg=b"jpeg-bytes",
    )
    with injected_context.overlay_images_lock:
        injected_context.overlay_images[overlay.source] = overlay

    async def first_chunk() -> bytes:
        generator = runtime_routes._mjpeg_latest_overlay_generator(
            overlay.source,
            max_fps=30,
            runtime_context=injected_context,
        )
        try:
            return await asyncio.wait_for(generator.__anext__(), timeout=1.0)
        finally:
            await generator.aclose()

    chunk = asyncio.run(first_chunk())

    assert b"jpeg-bytes" in chunk
    assert injected_context.metrics.stream_snapshot()["frames_sent_total"] == 1
    assert default_runtime_context.metrics.stream_snapshot()["frames_sent_total"] == default_before


def test_app_main_is_only_runtime_entrypoint_wrapper():
    main_source = (SERVICE_DIR / "app" / "main.py").read_text(encoding="utf-8")

    assert "sys.modules" not in main_source
    assert "include_runtime_routes" not in main_source
    assert "from .factory import create_app" in main_source
    assert "app = create_app()" in main_source


def test_vision_read_model_import_boundary_uses_facade_and_one_way_core():
    api_dir = SERVICE_DIR / "app" / "api"
    vision_tree = ast.parse((api_dir / "vision.py").read_text(encoding="utf-8"))
    facade_tree = ast.parse((api_dir / "vision_read_models.py").read_text(encoding="utf-8"))
    ros_core_tree = ast.parse((api_dir / "vision_read_model_ros.py").read_text(encoding="utf-8"))

    vision_imports = {
        node.module for node in ast.walk(vision_tree) if isinstance(node, ast.ImportFrom)
    }
    assert "vision_read_models" in vision_imports
    assert not any(module and module.startswith("vision_read_model_") for module in vision_imports)

    facade_imports = {
        node.module for node in ast.walk(facade_tree) if isinstance(node, ast.ImportFrom)
    }
    assert {
        "vision_read_model_debug",
        "vision_read_model_metrics",
        "vision_read_model_ros",
        "vision_read_model_streams",
        "vision_read_model_worker",
    }.issubset(facade_imports)

    ros_core_imports = {
        node.module for node in ast.walk(ros_core_tree) if isinstance(node, ast.ImportFrom)
    }
    assert (
        not {
            "vision_read_model_debug",
            "vision_read_model_metrics",
            "vision_read_model_streams",
            "vision_read_model_worker",
        }
        & ros_core_imports
    )


def test_vision_bundle_scripts_share_common_shell_helpers():
    common = ROOT / "scripts" / "lib" / "vision_bundle_common.sh"
    common_source = common.read_text(encoding="utf-8")

    assert "sf_lan_ip()" in common_source
    assert "sf_default_model_extra_pythonpath()" in common_source

    for script_name in (
        "run_d1_vision_multi_source_gateway_bundle.sh",
        "run_d1_vision_bundle.sh",
        "run_d1_vision_domain_sidecar.sh",
    ):
        script_source = (ROOT / "scripts" / "vision" / script_name).read_text(encoding="utf-8")
        assert 'source "${SCRIPT_DIR}/../lib/vision_bundle_common.sh"' in script_source
        assert '$(sf_repo_root_from_script "${BASH_SOURCE[0]}")' in script_source
        assert "$(sf_lan_ip" in script_source


def test_vision_bundle_scripts_preserve_operator_model_class_map_json():
    for script_name in (
        "run_d1_vision_multi_source_gateway_bundle.sh",
        "run_d1_vision_bundle.sh",
    ):
        script_source = (ROOT / "scripts" / "vision" / script_name).read_text(encoding="utf-8")
        assert 'VISION_MODEL_CLASS_MAP_JSON="${VISION_MODEL_CLASS_MAP_JSON:-' not in script_source
        assert (
            'export VISION_MODEL_CLASS_MAP_JSON=\'{"bottle":"box","person":"person"}\''
            in script_source
        )
        assert "export VISION_MODEL_CLASS_MAP_JSON\n" in script_source


def test_multi_source_bundle_does_not_advertise_runtime_ip_fallback() -> None:
    script_source = (
        ROOT / "scripts" / "vision" / "run_d1_vision_multi_source_gateway_bundle.sh"
    ).read_text(encoding="utf-8")

    for forbidden in (
        "VISION_API_FALLBACK_BASE_URL",
        "VISION_STREAM_FALLBACK_BASE_URL",
        "LMS_VISION_STREAM_FALLBACK_BASE_URL",
        "configure explicitly only if hostname resolution fails",
    ):
        assert forbidden not in script_source


def test_operator_wrapper_does_not_advertise_runtime_ip_fallback() -> None:
    wrapper_source = (ROOT / "scripts" / "vision" / "sf_vision.sh").read_text(
        encoding="utf-8"
    )
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "detected_lan_fallback=" not in wrapper_source
    assert "detected_lan_ip=" in wrapper_source
    assert "read-only hostname diagnosis; never a service endpoint" in wrapper_source
    assert "IP fallbacks empty by default" not in env_example
    assert "Direct-IP runtime fallbacks are prohibited" in env_example


def test_health_model_status_reports_invalid_class_map_as_error():
    from app.api.health import _vision_model_status
    from app.config import Settings

    settings = Settings(
        vision_model_path="/tmp/model.pt",
        vision_model_task="segment",
        vision_model_class_map_json='{"bottle":"box"}}',
    )

    assert _vision_model_status(settings) == "error"


def test_health_model_status_reports_invalid_source_config_as_error():
    from app.api.health import _vision_model_status
    from app.config import Settings

    settings = Settings(
        vision_model_path="/tmp/model.pt",
        vision_model_task="detect",
        vision_model_class_map_json='{"bottle":"box"}',
        vision_model_source_config_json='{"tb3_1_picam": false}',
    )

    assert _vision_model_status(settings) == "error"


def test_health_model_status_rejects_invalid_source_override_fields():
    from app.api.health import _vision_model_status
    from app.config import Settings

    invalid_task = Settings(
        vision_model_path="/tmp/model.pt",
        vision_model_task="detect",
        vision_model_class_map_json='{"bottle":"box"}',
        vision_model_source_config_json='{"global_cam_01": {"task": "seg", "imgsz": 640}}',
    )
    invalid_class_map = Settings(
        vision_model_path="/tmp/model.pt",
        vision_model_task="detect",
        vision_model_class_map_json='{"bottle":"box"}',
        vision_model_source_config_json='{"global_cam_01": {"task": "segment", "class_map": false}}',
    )

    assert _vision_model_status(invalid_task) == "error"
    assert _vision_model_status(invalid_class_map) == "error"


def test_health_matches_api_contract_fields():
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["service"] == "ai-server"
    assert body["status"] == "ok"
    assert body["service_version"] == "0.1.0"
    assert body["contract_version"] == "vision-event.v1"
    assert body["model_status"] in {"loaded", "disabled", "error"}
    assert body["models"]["marker"]["status"] == "loaded"
    assert body["models"]["marker"]["name"] == "opencv-marker-detector"
    assert body["models"]["lift_roi"]["status"] in {"loaded", "disabled", "error"}
    assert body["models"]["lift_roi"]["task"] in {"segment", "detect"}
    assert isinstance(body["models"]["lift_roi"]["class_map_valid"], bool)
    assert isinstance(body["models"]["lift_roi"]["source_config_valid"], bool)
    assert isinstance(body["models"]["lift_roi"]["source_overrides"], list)
    assert body["source_summary"]["configured"] == 3


def test_sources_match_api_contract_fields_and_do_not_require_ros_imports():
    response = client.get("/api/v1/sources")

    assert response.status_code == 200
    sources = {item["source"]: item for item in response.json()["sources"]}
    assert set(sources) == {"global_cam_01", "tb3_1_picam", "tb3_2_picam"}
    assert sources["global_cam_01"]["kind"] == "global_rgb"
    assert sources["global_cam_01"]["robot_id"] is None
    assert sources["tb3_1_picam"]["kind"] == "robot_pi_camera"
    assert sources["tb3_1_picam"]["robot_id"] == "tb3_1"
    assert all(item["enabled"] is True for item in sources.values())
    assert all(
        item["status"] in {"online", "stale", "offline", "disabled"} for item in sources.values()
    )


def test_latest_detections_contract_limit_is_bounded_to_50():
    response = client.get("/api/v1/detections/latest", params={"limit": 51})

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["request_id"]


def test_common_error_response_shape_includes_request_id_header():
    response = client.get(
        "/api/v1/detections/latest",
        params={"source": "bad_cam"},
        headers={"X-Request-ID": "req-contract-test"},
    )

    assert response.status_code == 400
    assert response.headers["X-Request-ID"] == "req-contract-test"
    assert response.json() == {
        "error": {
            "code": "BAD_REQUEST",
            "message": "unknown source: bad_cam",
            "details": [],
            "request_id": "req-contract-test",
        }
    }


def test_openapi_exposes_metrics_and_omits_legacy_lift_roi_routes():
    schema = app.openapi()

    assert "/api/v1/lift-roi/evaluate" not in schema["paths"]
    assert "/api/v1/lift-roi/evaluate-image" not in schema["paths"]

    metrics = schema["paths"]["/api/v1/metrics"]["get"]
    assert metrics["responses"]["200"]["content"]["application/json"]["schema"]["required"] == [
        "generated_at",
        "metrics",
        "event_store",
        "frame_store",
    ]


def test_openapi_exposes_lane_b_overlay_debug_surfaces():
    schema = app.openapi()

    assert "/api/v1/vision/synthetic/frame" in schema["paths"]
    assert "/api/v1/vision/worker/status" in schema["paths"]
    assert "/api/v1/vision/worker/tick" in schema["paths"]
    assert "/api/v1/vision/debug/sources" in schema["paths"]
    assert "/api/v1/vision/ros/topics" in schema["paths"]
    assert "/api/v1/vision/streams" in schema["paths"]
    assert "/api/v1/vision/streams/{source}/webrtc/offer" in schema["paths"]
    assert "/api/v1/vision/webrtc/demo" in schema["paths"]
    assert "/api/v1/vision/overlay/metadata" in schema["paths"]
    overlay_metadata_schema = schema["paths"]["/api/v1/vision/overlay/metadata"]["get"][
        "responses"
    ]["200"]["content"]["application/json"]["schema"]
    assert overlay_metadata_schema["required"] == [
        "generated_at",
        "requested_source",
        "requested_view",
        "sync",
        "overlay",
        "metadata_plane",
        "events",
    ]
    assert overlay_metadata_schema["properties"]["metadata_plane"]["properties"][
        "render_target"
    ] == {
        "const": "diagnostic_canvas_only_public_stream_is_burned_overlay",
        "type": "string",
    }
    assert overlay_metadata_schema["properties"]["metadata_plane"]["properties"][
        "client_rendering"
    ] == {
        "const": "diagnostic_only_not_required_for_main_streaming",
        "type": "string",
    }
    assert (
        overlay_metadata_schema["properties"]["events"]["items"]["properties"]["metadata"][
            "properties"
        ]["frame_seq"]["minimum"]
        == 1
    )
    stream_schema = schema["paths"]["/api/v1/vision/streams"]["get"]["responses"]["200"]["content"][
        "application/json"
    ]["schema"]
    assert stream_schema["properties"]["primary_stream_plane"] == {
        "const": "webrtc",
        "type": "string",
    }
    assert stream_schema["properties"]["fallback_stream_plane"] == {
        "const": "http_mjpeg_gateway",
        "type": "string",
    }
    assert stream_schema["properties"]["debug_only"] == {"const": False, "type": "boolean"}
    assert stream_schema["properties"]["motion_command_allowed"] == {
        "const": False,
        "type": "boolean",
    }
    assert stream_schema["properties"]["control_topics_published"]["maxItems"] == 0
    assert "stream_base_url" in stream_schema["required"]
    assert stream_schema["not"] == {"required": ["rosbridge_url"]}
    internal_rosbridge_schema = stream_schema["properties"]["internal_rosbridge"]
    assert internal_rosbridge_schema["properties"]["scope"] == {
        "const": "operator_prototype_only",
        "type": "string",
    }
    assert internal_rosbridge_schema["properties"]["exposes_all_topics"] == {
        "const": False,
        "type": "boolean",
    }
    assert "/api/v1/vision/frame" in schema["paths"]
    assert "/api/v1/vision/frame/process" in schema["paths"]
    assert "/api/v1/vision/frame/latest" in schema["paths"]
    assert "/api/v1/vision/frame/latest/image" in schema["paths"]
    assert "/api/v1/vision/overlay/latest" in schema["paths"]
    assert "/api/v1/vision/overlay/latest/image" in schema["paths"]
    assert "/api/v1/vision/stream/{source}.mjpeg" in schema["paths"]
    synthetic_responses = schema["paths"]["/api/v1/vision/synthetic/frame"]["post"]["responses"]
    assert "200" in synthetic_responses
    assert "400" in synthetic_responses
    assert "422" in synthetic_responses
    worker_responses = schema["paths"]["/api/v1/vision/worker/tick"]["post"]["responses"]
    assert "200" in worker_responses
    assert "400" in worker_responses
    assert "422" in worker_responses
    worker_status_responses = schema["paths"]["/api/v1/vision/worker/status"]["get"]["responses"]
    assert "200" in worker_status_responses
    assert "400" in worker_status_responses
    assert "422" in worker_status_responses
    debug_source_responses = schema["paths"]["/api/v1/vision/debug/sources"]["get"]["responses"]
    assert "200" in debug_source_responses
    assert "400" in debug_source_responses
    frame_ingest_responses = schema["paths"]["/api/v1/vision/frame"]["post"]["responses"]
    assert "200" in frame_ingest_responses
    assert "400" in frame_ingest_responses
    assert "422" in frame_ingest_responses
    frame_process_responses = schema["paths"]["/api/v1/vision/frame/process"]["post"]["responses"]
    assert "200" in frame_process_responses
    assert "400" in frame_process_responses
    assert "422" in frame_process_responses
    frame_process_schema = frame_process_responses["200"]["content"]["application/json"]["schema"]
    assert "frame_seq" in frame_process_schema["required"]
    assert "event_count" in frame_process_schema["required"]
    latest_frame_responses = schema["paths"]["/api/v1/vision/frame/latest"]["get"]["responses"]
    assert "200" in latest_frame_responses
    assert "400" in latest_frame_responses
    assert "404" in latest_frame_responses
    assert "404" in schema["paths"]["/api/v1/vision/frame/latest/image"]["get"]["responses"]
    ros_topic_responses = schema["paths"]["/api/v1/vision/ros/topics"]["get"]["responses"]
    assert "200" in ros_topic_responses
    stream_get = schema["paths"]["/api/v1/vision/stream/{source}.mjpeg"]["get"]
    assert "404" in schema["paths"]["/api/v1/vision/overlay/latest"]["get"]["responses"]
    assert "400" in stream_get["responses"]
    params = {param["name"]: param for param in stream_get["parameters"]}
    assert params["max_fps"]["schema"]["default"] == 10
    assert params["max_fps"]["schema"]["minimum"] == 1
    assert params["max_fps"]["schema"]["maximum"] == 30


def test_generated_openapi_artifact_matches_current_app_schema():
    generated_path = ROOT / "docs" / "contracts" / "ai-server-openapi.json"

    generated_schema = json.loads(generated_path.read_text(encoding="utf-8"))

    assert generated_schema == app.openapi()


def test_ai_server_dependencies_exclude_yolo_torch_and_ros2_imports():
    dependency_text = "\n".join(
        (SERVICE_DIR / name).read_text(encoding="utf-8")
        for name in ("requirements.txt", "requirements-dev.txt", "requirements.lock")
    ).lower()
    assert "torch" not in dependency_text
    assert "ultralytics" not in dependency_text
    assert "yolo" not in dependency_text

    app_source = "\n".join(
        path.read_text(encoding="utf-8") for path in (SERVICE_DIR / "app").glob("*.py")
    ).lower()
    assert "rclpy" not in app_source
    assert "sensor_msgs" not in app_source


def test_ai_test_script_clears_ros_pythonpath_contamination():
    script = (ROOT / "scripts" / "ai" / "test_ai_server.sh").read_text(encoding="utf-8")

    assert "unset PYTHONPATH" in script
    assert "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1" in script
    assert "PYTHONNOUSERSITE=1" in script


def test_ai_server_imports_do_not_require_ros2_yolo_or_torch_modules():
    code = r"""
import importlib
import importlib.abc
import sys

blocked = {"torch", "ultralytics", "rclpy", "sensor_msgs", "cv_bridge"}

class BlockForbidden(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".", 1)[0] in blocked:
            raise AssertionError(f"forbidden import attempted: {fullname}")
        return None

sys.meta_path.insert(0, BlockForbidden())
importlib.import_module("app.detectors")
importlib.import_module("app.model_adapters")
importlib.import_module("app.observability")
importlib.import_module("app.vision_interfaces")
importlib.import_module("app.main")
print("import guard ok")
"""
    import subprocess

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=SERVICE_DIR,
        text=True,
        capture_output=True,
        check=True,
    )

    assert "import guard ok" in result.stdout
