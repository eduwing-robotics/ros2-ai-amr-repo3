import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.config import REPO_ROOT, _legacy_source_registry, get_settings
from app.main import app
from app.source_registry import SourceRegistryError, load_source_registry

client = TestClient(app)


def test_source_registry_loads_mvp_sources_and_topics():
    registry = get_settings().source_registry

    assert registry.schema_version == "vision-sources.v1"
    assert registry.source_ids == ["global_cam_01", "tb3_1_picam", "tb3_2_picam"]
    assert registry.all_source_ids == [
        "global_cam_01",
        "global_depth_01",
        "tb3_1_picam",
        "tb3_2_picam",
    ]
    tb3_1 = registry.get("tb3_1_picam")
    assert tb3_1.robot_id == "tb3_1"
    assert tb3_1.frame_id == "tb3_1_pi_camera_optical_frame"
    assert tb3_1.physical_input.topic == "/tb3_1/camera/image_raw/compressed"
    assert tb3_1.physical_input.message_type == "sensor_msgs/msg/CompressedImage"
    assert tb3_1.normalized_topics.overlay == "/sf/vision/sources/tb3_1_picam/overlay/compressed"
    assert tb3_1.budgets.preview_media_fps == 30.0
    assert tb3_1.budgets.ai_monitor_fps == 10.0
    assert tb3_1.budgets.evidence_imgsz is None
    assert tb3_1.budgets.browser_primary_transport_semantics == "legacy_internal_rosbridge_metadata"


def test_source_registry_budget_semantics_separate_preview_ai_and_evidence():
    registry = get_settings().source_registry
    global_cam = registry.get("global_cam_01")

    assert global_cam.target_fps == 10.0
    assert global_cam.budgets.as_snapshot() == {
        "target_fps_semantics": "legacy_ai_ingest_default",
        "preview_media_fps": 30.0,
        "ai_monitor_fps": 5.0,
        "evidence_imgsz": 960,
        "browser_primary_transport_semantics": "legacy_internal_rosbridge_metadata",
    }


def _source_registry_yaml_with_budget_line(line: str) -> str:
    return f"""
schema_version: vision-sources.v1
sources:
  - source_id: test_cam
    kind: global_rgb
    robot_id: null
    frame_id: test_frame
    enabled: true
    target_fps: 10.0
    notes: test
    budgets:
      target_fps_semantics: legacy_ai_ingest_default
      {line}
      browser_primary_transport_semantics: legacy_internal_rosbridge_metadata
    physical_input:
      topic: /test/image_raw
      message_type: sensor_msgs/msg/Image
      content_type: image/raw
      preferred_transport: raw
    browser:
      legacy_topic: null
      legacy_message_type: null
      primary_transport: rosbridge
    normalized_topics:
      image: /sf/vision/sources/test_cam/image/compressed
      overlay: /sf/vision/sources/test_cam/overlay/compressed
    evidence_event_topic: /sf/vision/events
    views:
      - view_id: full
        kind: full_frame
        can_confirm_internal_color_indexing: false
"""


@pytest.mark.parametrize(
    "line",
    [
        "preview_media_fps: true",
        "preview_media_fps: 0",
        "preview_media_fps: -1",
        'preview_media_fps: "fast"',
    ],
)
def test_source_registry_rejects_invalid_budget_float_values(tmp_path: Path, line: str):
    path = tmp_path / "sources.yaml"
    path.write_text(_source_registry_yaml_with_budget_line(line), encoding="utf-8")

    with pytest.raises(SourceRegistryError, match="preview_media_fps must be a positive number"):
        load_source_registry(path)


def test_source_registry_rejects_invalid_evidence_imgsz_bool(tmp_path: Path):
    path = tmp_path / "sources.yaml"
    path.write_text(
        _source_registry_yaml_with_budget_line("evidence_imgsz: true"), encoding="utf-8"
    )

    with pytest.raises(SourceRegistryError, match="evidence_imgsz must be a positive integer"):
        load_source_registry(path)


def test_source_registry_rejects_view_parent_that_is_not_declared(tmp_path: Path):
    path = tmp_path / "sources.yaml"
    path.write_text(
        _source_registry_yaml_with_budget_line("preview_media_fps: 30")
        + """
      - view_id: crop
        kind: cropped
        parent_view: missing
        can_confirm_internal_color_indexing: false
""",
        encoding="utf-8",
    )

    with pytest.raises(SourceRegistryError, match="parent_view must reference an existing view"):
        load_source_registry(path)


def test_source_registry_view_contract_keeps_realsense_planned_and_view_scoped():
    registry = get_settings().source_registry
    source = registry.get("global_depth_01")
    global_cam = registry.get("global_cam_01")

    assert not source.enabled
    assert source.view_ids == ("full", "pallet_zoom")
    assert global_cam.view_ids == ("full", "lift_roi", "pallet_zoom")
    assert source.resolve_view().view_id == "full"
    assert not registry.can_confirm_internal_color_indexing("global_depth_01")
    assert registry.can_confirm_internal_color_indexing("global_depth_01", "pallet_zoom")
    assert not registry.can_confirm_internal_color_indexing("global_cam_01")
    assert not registry.can_confirm_internal_color_indexing("global_cam_01", "lift_roi")
    assert registry.can_confirm_internal_color_indexing("global_cam_01", "pallet_zoom")
    try:
        registry.resolve_view("global_depth_01", "bad_view")
    except KeyError as exc:
        assert exc.args == ("bad_view",)
    else:  # pragma: no cover - defensive assertion
        raise AssertionError("unknown source view must be rejected")


def test_legacy_source_registry_keeps_implicit_full_view_contract():
    registry = _legacy_source_registry(
        source_ids=["legacy_cam"],
        image_topics=["/legacy/camera/image_raw"],
    )
    source = registry.get("legacy_cam")

    assert registry.source_ids == ["legacy_cam"]
    assert source.view_ids == ("full",)
    assert source.resolve_view().view_id == "full"
    assert not registry.can_confirm_internal_color_indexing("legacy_cam")


def test_contract_schema_source_enums_match_registry():
    source_ids = get_settings().source_registry.source_ids
    contract_dir = REPO_ROOT / "docs" / "contracts"

    for name in ("vision-event.schema.json", "lift-roi-evidence.schema.json"):
        schema = json.loads((contract_dir / name).read_text(encoding="utf-8"))
        assert schema["properties"]["source"]["enum"] == source_ids


def test_source_registry_generator_does_not_emit_static_registry_copies():
    result = subprocess.run(
        [sys.executable, "scripts/generate/generate_source_registry_surfaces.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert not (REPO_ROOT / "docs/contracts/generated/source-registry.snapshot.json").exists()
    assert not (REPO_ROOT / "docs/contracts/fixtures/source-registry.valid.json").exists()


def test_contract_validator_accepts_authoritative_source_registry_without_static_copy():
    result = subprocess.run(
        [sys.executable, "scripts/validate/validate_contracts.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_contract_validator_reports_source_enum_drift():
    validator_path = REPO_ROOT / "scripts/validate/validate_contracts.py"
    spec = importlib.util.spec_from_file_location("validate_contracts", validator_path)
    assert spec and spec.loader
    validator = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(validator)
    source_ids = get_settings().source_registry.source_ids
    drifted_schema = {"properties": {"source": {"enum": source_ids[:-1]}}}
    failures: list[str] = []

    validator.validate_source_registry_surfaces(failures, drifted_schema, drifted_schema)

    assert failures == [
        "VisionEvent source enum does not match source registry",
        "LiftRoiEvidence source enum does not match source registry",
    ]


def _source_property(schema: dict, path: str, method: str, name: str = "source") -> dict:
    operation = schema["paths"][path][method]
    for parameter in operation.get("parameters", []):
        if parameter["name"] == name:
            return parameter["schema"]
    body_ref = operation["requestBody"]["content"]
    content = next(iter(body_ref.values()))
    ref = content["schema"]["$ref"].rsplit("/", 1)[-1]
    return schema["components"]["schemas"][ref]["properties"][name]


def test_openapi_source_fields_expose_registry_enum_without_changing_runtime_400s():
    schema = app.openapi()
    source_ids = get_settings().source_registry.source_ids

    assert _source_property(schema, "/api/v1/vision/streams", "get")["enum"] == source_ids
    assert _source_property(schema, "/api/v1/vision/frame", "post")["enum"] == source_ids
    assert _source_property(schema, "/api/v1/vision/synthetic/frame", "post")["enum"] == source_ids
    assert _source_property(schema, "/api/v1/detect/image", "post")["enum"] == source_ids

    bad = client.get("/api/v1/vision/streams", params={"source": "bad_cam"})
    assert bad.status_code == 400
    assert bad.json()["error"]["code"] == "BAD_REQUEST"
