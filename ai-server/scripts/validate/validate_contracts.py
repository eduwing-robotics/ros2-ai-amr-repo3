#!/usr/bin/env python3
"""Validate SmartFactory API contract fixtures.

This script intentionally validates both valid and invalid fixtures:
- files named vision-event.valid.*.json must pass JSON Schema and policy checks
- files named vision-event.invalid.*.json must fail either JSON Schema or policy checks
- files named lift-roi-evidence.valid.*.json must pass JSON Schema and policy checks
- files named lift-roi-evidence.invalid.*.json must fail either JSON Schema or policy checks
- files named evidence-evaluation.valid.*.json must pass JSON Schema and policy checks
- files named evidence-evaluation.invalid.*.json must fail either JSON Schema or policy checks
"""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

try:
    import jsonschema
except ImportError as exc:  # pragma: no cover
    raise SystemExit(
        "Missing dependency: jsonschema. Install it in the contract/dev environment."
    ) from exc

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.source_registry import load_source_registry  # noqa: E402

VISION_EVENT_SCHEMA_PATH = ROOT / "docs/contracts/vision-event.schema.json"
LIFT_ROI_EVIDENCE_SCHEMA_PATH = ROOT / "docs/contracts/lift-roi-evidence.schema.json"
EVIDENCE_EVALUATION_SCHEMA_PATH = ROOT / "docs/contracts/evidence-evaluation.v1.schema.json"
FIXTURE_DIR = ROOT / "docs/contracts/fixtures"
SOURCE_REGISTRY_PATH = ROOT / "config/vision/sources.yaml"
MARKER_CLASSES = {"aruco_marker", "qr_marker", "apriltag_marker"}
DETECTION_CLASSES = {"person", "obstacle", "box", "dropped_item", "pallet", "unknown"}
EVIDENCE_IMAGE_ROUTE_PREFIX = "/api/v1/evidence/images/"
EVIDENCE_IMAGE_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class PolicyError(ValueError):
    """Raised when a fixture passes JSON Schema but violates MVP1 event policy."""


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


SOURCE_REGISTRY = load_source_registry(SOURCE_REGISTRY_PATH).as_snapshot()
SOURCE_BY_ID = {item["source_id"]: item for item in SOURCE_REGISTRY.get("sources", [])}


def validate_policy(event: dict[str, Any]) -> None:
    source = event.get("source")
    robot_id = event.get("robot_id")
    expected = SOURCE_BY_ID.get(source)
    if expected is None:
        raise PolicyError(f"unknown source {source!r} is not in source registry")
    if robot_id != expected.get("robot_id"):
        raise PolicyError(f"{source} events must use robot_id {expected.get('robot_id')!r}")
    if event.get("frame_id") != expected.get("frame_id"):
        raise PolicyError(f"{source} events must use frame_id {expected.get('frame_id')!r}")

    if event.get("depth_median_m") is not None:
        raise PolicyError("depth_median_m must be null in MVP1")

    kind = event.get("event_kind")
    cls = event.get("class_name")
    marker_id = event.get("marker_id")
    bbox = event.get("bbox_xyxy")

    if kind == "STALE":
        if cls != "unknown" or event.get("wms_hint") != "VISION_STALE":
            raise PolicyError("STALE events must use class_name unknown and wms_hint VISION_STALE")
        if event.get("confidence") is not None or bbox is not None:
            raise PolicyError("STALE events must not include confidence or bbox evidence")

    if kind == "CONFIRMED" and cls in MARKER_CLASSES and not marker_id:
        raise PolicyError("CONFIRMED marker events require marker_id")

    if kind in {"CANDIDATE", "CONFIRMED"} and cls in DETECTION_CLASSES:
        if not isinstance(bbox, list) or len(bbox) != 4:
            raise PolicyError("Detection CANDIDATE/CONFIRMED events require bbox_xyxy")
        x1, y1, x2, y2 = bbox
        if not (x1 < x2 and y1 < y2):
            raise PolicyError("bbox_xyxy must satisfy x1 < x2 and y1 < y2")


def validate_event(path: Path, schema: dict[str, Any]) -> None:
    event = load_json(path)
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    validator.validate(event)
    validate_policy(event)


def _validate_bbox_order(bbox: list[Any]) -> None:
    x1, y1, x2, y2 = bbox
    if not (x1 < x2 and y1 < y2):
        raise PolicyError("bbox_xyxy must satisfy x1 < x2 and y1 < y2")


def validate_lift_roi_policy(payload: dict[str, Any]) -> None:
    source = payload.get("source")
    robot_id = payload.get("robot_id")
    expected = SOURCE_BY_ID.get(source)
    if expected is None:
        raise PolicyError(f"unknown source {source!r} is not in source registry")
    if robot_id != expected.get("robot_id"):
        raise PolicyError(
            f"{source} lift ROI evidence must use robot_id {expected.get('robot_id')!r}"
        )
    if payload.get("frame_id") != expected.get("frame_id"):
        raise PolicyError(
            f"{source} lift ROI evidence must use frame_id {expected.get('frame_id')!r}"
        )

    load = payload["load"]
    accepted = load["accepted_items"]
    rejected = load["rejected_items"]
    if load["count"] != len(accepted):
        raise PolicyError("lift ROI load.count must equal accepted_items length")
    if load["empty"] != (load["count"] == 0):
        raise PolicyError("lift ROI load.empty must match count == 0")

    for item in accepted:
        _validate_bbox_order(item["bbox_xyxy"])
        if item["reason"] != "accepted":
            raise PolicyError("accepted lift ROI items must use reason accepted")
        if not item["center_inside_roi"]:
            raise PolicyError("accepted lift ROI items must have center_inside_roi true")
    for item in rejected:
        _validate_bbox_order(item["bbox_xyxy"])
        if item["reason"] == "accepted":
            raise PolicyError("rejected lift ROI items must not use reason accepted")

    verification = payload["verification"]
    if verification["status"] == "CONFIRMED" and payload["operation"] == "PICKUP":
        if payload["expected_count"] is None:
            raise PolicyError("confirmed pickup lift ROI evidence requires expected_count")
        if load["count"] != payload["expected_count"]:
            raise PolicyError("confirmed pickup lift ROI evidence count must match expected_count")
        if not payload["count_stable"]:
            raise PolicyError("confirmed pickup lift ROI evidence requires count_stable true")
        if payload["lift_sensor"].get("lift_up") is not True:
            raise PolicyError("confirmed pickup lift ROI evidence requires lift_up true")
        if payload["dropped_item_count"] != 0:
            raise PolicyError("confirmed pickup lift ROI evidence requires dropped_item_count 0")

    if verification["status"] == "CONFIRMED" and payload["operation"] == "DROPOFF":
        if payload["lift_sensor"].get("lift_down_complete") is not True:
            raise PolicyError(
                "confirmed dropoff lift ROI evidence requires lift_down_complete true"
            )
        if payload["lift_sensor"].get("backoff_complete") is not True:
            raise PolicyError("confirmed dropoff lift ROI evidence requires backoff_complete true")


def validate_lift_roi_evidence(path: Path, schema: dict[str, Any]) -> None:
    payload = load_json(path)
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    validator.validate(payload)
    validate_lift_roi_policy(payload)


def validate_evidence_evaluation_policy(payload: dict[str, Any]) -> None:
    if payload.get("trusted") is not False:
        raise PolicyError("evidence evaluation trusted must remain false")

    judgement = payload.get("data_json", {}).get("ai_judgement", {})
    for key in ("verification_status", "validity", "reason_code"):
        if judgement.get(key) != payload.get(key):
            raise PolicyError(f"data_json.ai_judgement.{key} must match top-level {key}")

    status = payload.get("verification_status")
    validity = payload.get("validity")
    if status == "PASS" and validity != "VALID_CANDIDATE":
        raise PolicyError("PASS evidence evaluation must be VALID_CANDIDATE")
    if status == "UNCERTAIN" and validity != "NEEDS_REVIEW":
        raise PolicyError("UNCERTAIN evidence evaluation must be NEEDS_REVIEW")
    if payload.get("reason_code") in {"LOW_PIXEL_BUDGET", "LOW_QUALITY_EVIDENCE"}:
        if status != "UNCERTAIN" or validity != "NEEDS_REVIEW":
            raise PolicyError("quality-review evidence evaluation must be UNCERTAIN/NEEDS_REVIEW")

    image_uri = payload.get("image_uri")
    if image_uri is not None:
        validate_evidence_image_uri_policy(image_uri)


def validate_evidence_image_route_segments_policy(
    *,
    source: str,
    view: str,
    date_part: str,
    filename: str,
) -> tuple[str, str, str, str]:
    decoded: dict[str, str] = {}
    for name, value in {
        "source": source,
        "view": view,
        "date": date_part,
        "filename": filename,
    }.items():
        segment = unquote(str(value))
        if not segment or segment in {".", ".."} or "/" in segment or "\\" in segment:
            raise PolicyError(f"evidence image {name} contains unsafe path segment")
        decoded[name] = segment

    decoded_date = decoded["date"]
    if not EVIDENCE_IMAGE_DATE_RE.fullmatch(decoded_date):
        raise PolicyError("evidence image date must use YYYY-MM-DD")
    try:
        date.fromisoformat(decoded_date)
    except ValueError as exc:
        raise PolicyError("evidence image date must be valid YYYY-MM-DD") from exc

    return decoded["source"], decoded["view"], decoded_date, decoded["filename"]


def validate_evidence_image_uri_policy(image_uri: str) -> None:
    parsed = urlparse(image_uri)
    if parsed.scheme or parsed.netloc:
        raise PolicyError("evidence evaluation image_uri must be a server-generated API path")
    if parsed.query or parsed.fragment:
        raise PolicyError("evidence evaluation image_uri must not include query or fragment")
    if not image_uri.startswith("/"):
        raise PolicyError("evidence evaluation image_uri must be an API path")
    route_path = parsed.path

    if "/api/v1/evidence/files/" in route_path:
        raise PolicyError("evidence evaluation image_uri must not use stale /evidence/files route")
    if not route_path.startswith(EVIDENCE_IMAGE_ROUTE_PREFIX):
        raise PolicyError("evidence evaluation image_uri must start with /api/v1/evidence/images/")

    route_suffix = route_path[len(EVIDENCE_IMAGE_ROUTE_PREFIX) :]
    parts = route_suffix.split("/")
    if len(parts) != 4 or any(not part for part in parts):
        raise PolicyError(
            "evidence evaluation image_uri must use /api/v1/evidence/images/{source}/{view}/{date}/{filename}"
        )
    validate_evidence_image_route_segments_policy(
        source=parts[0],
        view=parts[1],
        date_part=parts[2],
        filename=parts[3],
    )


def validate_evidence_evaluation(path: Path, schema: dict[str, Any]) -> None:
    payload = load_json(path)
    validator = jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker())
    validator.validate(payload)
    validate_evidence_evaluation_policy(payload)


def validate_source_registry_surfaces(
    failures: list[str], vision_schema: dict[str, Any], lift_roi_schema: dict[str, Any]
) -> None:
    if not SOURCE_BY_ID:
        failures.append("authoritative source registry is empty")
        return
    source_ids = SOURCE_REGISTRY.get("source_ids")
    all_source_ids = SOURCE_REGISTRY.get("all_source_ids")
    expected_all_source_ids = list(SOURCE_BY_ID)
    expected_enabled_source_ids = [
        source_id for source_id, source in SOURCE_BY_ID.items() if source.get("enabled") is True
    ]
    if all_source_ids != expected_all_source_ids:
        failures.append("source registry all_source_ids do not match sources order")
    if source_ids != expected_enabled_source_ids:
        failures.append("source registry source_ids do not match enabled sources order")
    if vision_schema.get("properties", {}).get("source", {}).get("enum") != source_ids:
        failures.append("VisionEvent source enum does not match source registry")
    if lift_roi_schema.get("properties", {}).get("source", {}).get("enum") != source_ids:
        failures.append("LiftRoiEvidence source enum does not match source registry")


def validate_fixture_set(
    *,
    contract_name: str,
    schema: dict[str, Any],
    valid_glob: str,
    invalid_glob: str,
    validate_fn,
    failures: list[str],
) -> None:
    valid = sorted(FIXTURE_DIR.glob(valid_glob))
    invalid = sorted(FIXTURE_DIR.glob(invalid_glob))

    for path in valid:
        try:
            validate_fn(path, schema)
            print(f"VALID ok: {path.relative_to(ROOT)}")
        except Exception as exc:  # noqa: BLE001 - report all validation failures
            failures.append(f"VALID {contract_name} fixture failed {path.name}: {exc}")

    for path in invalid:
        try:
            validate_fn(path, schema)
        except Exception as exc:  # expected path
            print(f"INVALID rejected: {path.relative_to(ROOT)} ({exc.__class__.__name__}: {exc})")
        else:
            failures.append(f"INVALID {contract_name} fixture unexpectedly passed {path.name}")


def main() -> int:
    vision_event_schema = load_json(VISION_EVENT_SCHEMA_PATH)
    lift_roi_schema = load_json(LIFT_ROI_EVIDENCE_SCHEMA_PATH)
    evidence_evaluation_schema = load_json(EVIDENCE_EVALUATION_SCHEMA_PATH)
    failures: list[str] = []

    validate_source_registry_surfaces(failures, vision_event_schema, lift_roi_schema)

    validate_fixture_set(
        contract_name="VisionEvent",
        schema=vision_event_schema,
        valid_glob="vision-event.valid.*.json",
        invalid_glob="vision-event.invalid.*.json",
        validate_fn=validate_event,
        failures=failures,
    )
    validate_fixture_set(
        contract_name="LiftRoiEvidence",
        schema=lift_roi_schema,
        valid_glob="lift-roi-evidence.valid.*.json",
        invalid_glob="lift-roi-evidence.invalid.*.json",
        validate_fn=validate_lift_roi_evidence,
        failures=failures,
    )
    validate_fixture_set(
        contract_name="EvidenceEvaluation",
        schema=evidence_evaluation_schema,
        valid_glob="evidence-evaluation.valid.*.json",
        invalid_glob="evidence-evaluation.invalid.*.json",
        validate_fn=validate_evidence_evaluation,
        failures=failures,
    )

    if failures:
        print("\nContract validation failed:", file=sys.stderr)
        for failure in failures:
            print(f"- {failure}", file=sys.stderr)
        return 1

    print("\nAll contract fixtures behaved as expected.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
