import json
from pathlib import Path

import jsonschema
import pytest

from app.contracts import validate_evidence_evaluation

ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "docs" / "contracts" / "evidence-evaluation.v1.schema.json"
FIXTURE_DIR = ROOT / "docs" / "contracts" / "fixtures"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_evidence_evaluation_schema_is_draft_2020_12():
    schema = _load(SCHEMA_PATH)

    jsonschema.Draft202012Validator.check_schema(schema)
    assert schema["properties"]["schema_version"]["const"] == "evidence-evaluation.v1"
    assert schema["properties"]["trusted"]["const"] is False


def test_evidence_evaluation_valid_fixtures_pass_contract_policy():
    fixtures = sorted(FIXTURE_DIR.glob("evidence-evaluation.valid.*.json"))

    assert {path.name for path in fixtures} == {
        "evidence-evaluation.valid.dropped-item-candidate.json",
        "evidence-evaluation.valid.fail.json",
        "evidence-evaluation.valid.pass.json",
        "evidence-evaluation.valid.uncertain-low-pixel-budget.json",
        "evidence-evaluation.valid.uncertain-no-frame.json",
    }
    for path in fixtures:
        validate_evidence_evaluation(_load(path))


def test_evidence_evaluation_status_and_validity_examples_are_covered():
    fixtures = [_load(path) for path in FIXTURE_DIR.glob("evidence-evaluation.valid.*.json")]

    assert {item["verification_status"] for item in fixtures} == {"PASS", "FAIL", "UNCERTAIN"}
    assert {item["validity"] for item in fixtures} == {
        "VALID_CANDIDATE",
        "INVALID_CANDIDATE",
        "NEEDS_REVIEW",
    }
    assert "DROPPED_ITEM_DETECTED" in {item["reason_code"] for item in fixtures}


def test_evidence_evaluation_fixtures_remain_advisory_not_trusted():
    for path in FIXTURE_DIR.glob("evidence-evaluation.valid.*.json"):
        payload = _load(path)
        assert payload["trusted"] is False
        assert (
            payload["data_json"]["ai_judgement"]["verification_status"]
            == payload["verification_status"]
        )
        assert payload["data_json"]["ai_judgement"]["validity"] == payload["validity"]
        assert payload["data_json"]["ai_judgement"]["reason_code"] == payload["reason_code"]


def test_quality_review_reason_codes_cannot_validate_as_pass():
    payload = _load(FIXTURE_DIR / "evidence-evaluation.valid.uncertain-low-pixel-budget.json")
    payload["verification_status"] = "PASS"
    payload["validity"] = "VALID_CANDIDATE"
    payload["data_json"]["ai_judgement"]["verification_status"] = "PASS"
    payload["data_json"]["ai_judgement"]["validity"] = "VALID_CANDIDATE"

    with pytest.raises(Exception):
        validate_evidence_evaluation(payload)


@pytest.mark.parametrize(
    "image_uri",
    [
        "http://ai-server.local:8100/api/v1/evidence/images/global_cam_01/full/2026-06-24/proof.jpg",
        "/api/v1/evidence/images/global_cam_01/full/2026-06-24/..%2Fsecret.jpg",
        "/api/v1/evidence/images/global_cam_01/%2E%2E/2026-06-24/proof.jpg",
        "/api/v1/evidence/images/global_cam_01/full/2026-06-24/proof.jpg?download=1",
    ],
)
def test_evidence_evaluation_rejects_non_server_generated_or_unsafe_image_uri(image_uri):
    payload = _load(FIXTURE_DIR / "evidence-evaluation.valid.pass.json")
    payload["image_uri"] = image_uri

    with pytest.raises(Exception):
        validate_evidence_evaluation(payload)
