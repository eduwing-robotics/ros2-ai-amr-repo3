import copy
import json
from pathlib import Path

import jsonschema
import pytest

from app.contracts import ContractValidationError, validate_vision_monitor_event

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs" / "contracts" / "vision-monitor-event.v1.schema.json"
FIXTURE_DIR = ROOT / "docs" / "contracts" / "fixtures" / "vision-monitor-event"

CONTROL_ACTION_VALUES = {"E_STOP", "HOLD", "STOP_COMMAND", "MOTION_CANCELLED"}
RAW_PAYLOAD_KEYS = {
    "bbox",
    "bbox_xyxy",
    "mask",
    "mask_rle",
    "polygon",
    "raw_detections",
    "detections",
}


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _walk(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)
    else:
        yield value


def test_vision_monitor_event_schema_is_draft_2020_12_and_advisory_only():
    schema = _load(SCHEMA_PATH)

    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["properties"]["schema_version"]["const"] == "vision-monitor-event.v1"
    assert schema["properties"]["trusted"]["const"] is False
    assert not (set(schema["properties"]["result"]["enum"]) & CONTROL_ACTION_VALUES)
    assert not (set(schema["properties"]["event_type"]["enum"]) & CONTROL_ACTION_VALUES)


def test_vision_monitor_event_valid_fixtures_cover_required_no_hardware_cases():
    fixture_names = {path.name for path in FIXTURE_DIR.glob("valid.*.json")}

    assert fixture_names == {
        "valid.person-hazard.json",
        "valid.dropped-item-candidate.json",
        "valid.lift-evidence-pass-pickup.json",
        "valid.lift-evidence-fail-pickup.json",
        "valid.lift-evidence-uncertain.json",
        "valid.no-decision.json",
    }

    payloads = [_load(path) for path in sorted(FIXTURE_DIR.glob("valid.*.json"))]
    for payload in payloads:
        validate_vision_monitor_event(payload)

    assert {payload["event_type"] for payload in payloads} >= {
        "HUMAN_DETECTED",
        "DROPPED_ITEM_CANDIDATE",
        "ITEM_PICKED",
        "LIFT_LOAD_EVIDENCE",
        "LIFT_LOAD_UNCERTAIN",
        "NO_DECISION",
    }
    assert {payload["result"] for payload in payloads} >= {
        "ADVISORY",
        "CANDIDATE",
        "PASS",
        "FAIL",
        "UNCERTAIN",
        "NO_DECISION",
    }


def test_vision_monitor_event_valid_fixtures_are_minimal_and_main_facing():
    for path in FIXTURE_DIR.glob("valid.*.json"):
        payload = _load(path)
        flattened = set(_walk(payload))

        assert payload["trusted"] is False
        assert not flattened & CONTROL_ACTION_VALUES
        assert not flattened & RAW_PAYLOAD_KEYS
        assert payload["data_json"]["result"] == payload["result"]
        assert payload["data_json"]["reason_code"] == payload["reason_code"]
        assert payload["data_json"]["policy_version"] == payload["policy_version"]
        assert payload["data_json"]["profile_id"] == payload["profile_id"]
        assert payload["data_json"]["threshold_set_id"] == payload["threshold_set_id"]


def test_lift_uncertain_does_not_satisfy_pick_or_drop_command_progress():
    payload = _load(FIXTURE_DIR / "valid.lift-evidence-uncertain.json")

    assert payload["result"] == "UNCERTAIN"
    assert payload["event_type"] not in {"ITEM_PICKED", "ITEM_PLACED"}

    mutated = copy.deepcopy(payload)
    mutated["event_type"] = "ITEM_PICKED"

    with pytest.raises(Exception):
        validate_vision_monitor_event(mutated)


@pytest.mark.parametrize(
    "fixture_name",
    [
        "invalid.control-action-result.json",
        "invalid.raw-bbox-in-data-json.json",
        "invalid.trusted-true.json",
    ],
)
def test_vision_monitor_event_invalid_fixtures_rejected(fixture_name):
    with pytest.raises(Exception):
        validate_vision_monitor_event(_load(FIXTURE_DIR / fixture_name))


def test_vision_monitor_event_json_schema_rejects_nested_raw_ai_judgement_keys():
    schema = _load(SCHEMA_PATH)
    validator = jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.FormatChecker(),
    )
    payload = _load(FIXTURE_DIR / "valid.lift-evidence-pass-pickup.json")
    payload["data_json"]["ai_judgement"]["bbox_xyxy"] = [1, 2, 3, 4]

    with pytest.raises(jsonschema.ValidationError):
        validator.validate(payload)


def test_pibase_source_requires_matching_robot_id():
    payload = _load(FIXTURE_DIR / "valid.person-hazard.json")
    payload["robot_id"] = "tb3_2"

    with pytest.raises(ContractValidationError, match="requires robot_id"):
        validate_vision_monitor_event(payload)


def test_global_source_may_be_resolved_to_robot_by_policy_context():
    payload = _load(FIXTURE_DIR / "valid.dropped-item-candidate.json")

    assert payload["source"] == "global_cam_01"
    assert payload["robot_id"] == "tb3_2"
    validate_vision_monitor_event(payload)
