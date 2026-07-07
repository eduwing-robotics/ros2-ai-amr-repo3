from __future__ import annotations

import json
import re
from datetime import date
from functools import lru_cache
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import jsonschema

from .config import SERVICE_DIR, get_settings


class ContractValidationError(ValueError):
    """Raised when an event does not satisfy canonical contract policy."""


EVIDENCE_IMAGE_ROUTE_PREFIX = "/api/v1/evidence/images/"
EVIDENCE_IMAGE_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
VISION_MONITOR_EVENT_SCHEMA_PATH = (
    SERVICE_DIR / "docs" / "contracts" / "vision-monitor-event.v1.schema.json"
)
VISION_MONITOR_FORBIDDEN_KEYS = {
    "bbox",
    "bbox_xyxy",
    "mask",
    "mask_rle",
    "polygon",
    "raw_detections",
    "detections",
    "E_STOP",
    "HOLD",
    "STOP_COMMAND",
    "MOTION_CANCELLED",
}
VISION_MONITOR_FORBIDDEN_VALUES = {
    "E_STOP",
    "HOLD",
    "STOP_COMMAND",
    "MOTION_CANCELLED",
}


@lru_cache(maxsize=1)
def _validator() -> jsonschema.Draft202012Validator:
    settings = get_settings()
    schema_path = Path(settings.contract_schema_path)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.FormatChecker(),
    )


@lru_cache(maxsize=1)
def _lift_roi_validator() -> jsonschema.Draft202012Validator:
    settings = get_settings()
    schema_path = Path(settings.lift_roi_evidence_schema_path)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.FormatChecker(),
    )


@lru_cache(maxsize=1)
def _evidence_evaluation_validator() -> jsonschema.Draft202012Validator:
    settings = get_settings()
    schema_path = Path(settings.evidence_evaluation_schema_path)
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.FormatChecker(),
    )


@lru_cache(maxsize=1)
def _vision_monitor_event_validator() -> jsonschema.Draft202012Validator:
    schema = json.loads(VISION_MONITOR_EVENT_SCHEMA_PATH.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.FormatChecker(),
    )


def validate_vision_event(event: dict[str, Any]) -> None:
    """Validate a VisionEvent against schema and MVP1 policy checks."""

    _validator().validate(event)

    bbox = event.get("bbox_xyxy")
    if bbox is not None:
        x1, y1, x2, y2 = bbox
        if not (x1 < x2 and y1 < y2):
            raise ContractValidationError("bbox_xyxy must satisfy x1 < x2 and y1 < y2")

    source = event.get("source")
    robot_id = event.get("robot_id")
    expected_robot = {
        "global_cam_01": None,
        "tb3_1_picam": "tb3_1",
        "tb3_2_picam": "tb3_2",
    }.get(source)
    if robot_id != expected_robot:
        raise ContractValidationError(f"source {source!r} requires robot_id {expected_robot!r}")

    if event.get("depth_median_m") is not None:
        raise ContractValidationError("depth_median_m must remain null in MVP1")


def _assert_no_vision_monitor_forbidden_payload(value: Any, *, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in VISION_MONITOR_FORBIDDEN_KEYS:
                raise ContractValidationError(
                    f"vision monitor event must not include raw/control key {path}.{key}"
                )
            _assert_no_vision_monitor_forbidden_payload(child, path=f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _assert_no_vision_monitor_forbidden_payload(child, path=f"{path}[{index}]")
        return
    if isinstance(value, str) and value in VISION_MONITOR_FORBIDDEN_VALUES:
        raise ContractValidationError(
            f"vision monitor event must not include control-action value {value!r}"
        )


def validate_vision_monitor_event(payload: dict[str, Any]) -> None:
    """Validate VisionMonitorEvent against schema and advisory-only policy."""

    _vision_monitor_event_validator().validate(payload)

    if payload.get("trusted") is not False:
        raise ContractValidationError("vision monitor event trusted must remain false")

    _assert_no_vision_monitor_forbidden_payload(payload)

    source = payload.get("source")
    robot_id = payload.get("robot_id")
    expected_robot = {
        "global_cam_01": None,
        "tb3_1_picam": "tb3_1",
        "tb3_2_picam": "tb3_2",
    }.get(source)
    if expected_robot is not None and robot_id != expected_robot:
        raise ContractValidationError(f"source {source!r} requires robot_id {expected_robot!r}")

    data_json = payload.get("data_json", {})
    for field in ("result", "reason_code", "policy_version", "profile_id", "threshold_set_id"):
        if data_json.get(field) != payload.get(field):
            raise ContractValidationError(f"data_json.{field} must match top-level {field}")

    event_type = payload.get("event_type")
    result = payload.get("result")
    if event_type in {"ITEM_PICKED", "ITEM_PLACED"} and result != "PASS":
        raise ContractValidationError("command-satisfying lift evidence must use result PASS")
    if result == "UNCERTAIN" and event_type in {"ITEM_PICKED", "ITEM_PLACED"}:
        raise ContractValidationError("UNCERTAIN lift evidence must not satisfy command progress")


def _validate_bbox_order(bbox: list[Any]) -> None:
    x1, y1, x2, y2 = bbox
    if not (x1 < x2 and y1 < y2):
        raise ContractValidationError("bbox_xyxy must satisfy x1 < x2 and y1 < y2")


def validate_evidence_image_route_segments(
    *,
    source: str,
    view: str,
    date_part: str,
    filename: str,
) -> tuple[str, str, str, str]:
    """Validate and decode public proof-image route segments.

    The public proof-image route is intentionally a route path, not an arbitrary
    filesystem path. Validate decoded segments so encoded traversal/separators
    such as ``%2E%2E`` and ``..%2Fsecret.jpg`` cannot pass either contract
    validation or the serving endpoint.
    """

    decoded: dict[str, str] = {}
    for name, value in {
        "source": source,
        "view": view,
        "date": date_part,
        "filename": filename,
    }.items():
        segment = unquote(str(value))
        if not segment or segment in {".", ".."} or "/" in segment or "\\" in segment:
            raise ContractValidationError(f"evidence image {name} contains unsafe path segment")
        decoded[name] = segment

    decoded_date = decoded["date"]
    if not EVIDENCE_IMAGE_DATE_RE.fullmatch(decoded_date):
        raise ContractValidationError("evidence image date must use YYYY-MM-DD")
    try:
        date.fromisoformat(decoded_date)
    except ValueError as exc:
        raise ContractValidationError("evidence image date must be valid YYYY-MM-DD") from exc

    return decoded["source"], decoded["view"], decoded_date, decoded["filename"]


def validate_evidence_image_uri(image_uri: str) -> None:
    """Validate the server-generated public proof image API path."""

    parsed = urlparse(image_uri)
    if parsed.scheme or parsed.netloc:
        raise ContractValidationError(
            "evidence evaluation image_uri must be a server-generated API path"
        )
    if parsed.query or parsed.fragment:
        raise ContractValidationError(
            "evidence evaluation image_uri must not include query or fragment"
        )
    if not image_uri.startswith("/"):
        raise ContractValidationError("evidence evaluation image_uri must be an API path")
    route_path = parsed.path

    if "/api/v1/evidence/files/" in route_path:
        raise ContractValidationError(
            "evidence evaluation image_uri must not use stale /evidence/files route"
        )
    if not route_path.startswith(EVIDENCE_IMAGE_ROUTE_PREFIX):
        raise ContractValidationError(
            "evidence evaluation image_uri must start with /api/v1/evidence/images/"
        )

    route_suffix = route_path[len(EVIDENCE_IMAGE_ROUTE_PREFIX) :]
    parts = route_suffix.split("/")
    if len(parts) != 4 or any(not part for part in parts):
        raise ContractValidationError(
            "evidence evaluation image_uri must use /api/v1/evidence/images/{source}/{view}/{date}/{filename}"
        )
    validate_evidence_image_route_segments(
        source=parts[0],
        view=parts[1],
        date_part=parts[2],
        filename=parts[3],
    )


def validate_lift_roi_evidence(payload: dict[str, Any]) -> None:
    """Validate LiftRoiEvidence against schema and MVP1 policy checks."""

    _lift_roi_validator().validate(payload)

    load = payload["load"]
    accepted = load["accepted_items"]
    rejected = load["rejected_items"]
    if load["count"] != len(accepted):
        raise ContractValidationError("lift ROI load.count must equal accepted_items length")
    if load["empty"] != (load["count"] == 0):
        raise ContractValidationError("lift ROI load.empty must match count == 0")

    for item in accepted:
        _validate_bbox_order(item["bbox_xyxy"])
        if item["reason"] != "accepted":
            raise ContractValidationError("accepted lift ROI items must use reason accepted")
        if not item["center_inside_roi"]:
            raise ContractValidationError(
                "accepted lift ROI items must have center_inside_roi true"
            )
    for item in rejected:
        _validate_bbox_order(item["bbox_xyxy"])
        if item["reason"] == "accepted":
            raise ContractValidationError("rejected lift ROI items must not use reason accepted")

    verification = payload["verification"]
    if verification["status"] == "CONFIRMED" and payload["operation"] == "PICKUP":
        if payload["expected_count"] is None:
            raise ContractValidationError(
                "confirmed pickup lift ROI evidence requires expected_count"
            )
        if load["count"] != payload["expected_count"]:
            raise ContractValidationError(
                "confirmed pickup lift ROI evidence count must match expected_count"
            )
        if not payload["count_stable"]:
            raise ContractValidationError(
                "confirmed pickup lift ROI evidence requires count_stable true"
            )
        if payload["lift_sensor"].get("lift_up") is not True:
            raise ContractValidationError(
                "confirmed pickup lift ROI evidence requires lift_up true"
            )
        if payload["dropped_item_count"] != 0:
            raise ContractValidationError(
                "confirmed pickup lift ROI evidence requires dropped_item_count 0"
            )

    if verification["status"] == "CONFIRMED" and payload["operation"] == "DROPOFF":
        if payload["lift_sensor"].get("lift_down_complete") is not True:
            raise ContractValidationError(
                "confirmed dropoff lift ROI evidence requires lift_down_complete true"
            )
        if payload["lift_sensor"].get("backoff_complete") is not True:
            raise ContractValidationError(
                "confirmed dropoff lift ROI evidence requires backoff_complete true"
            )


def validate_evidence_evaluation(payload: dict[str, Any]) -> None:
    """Validate EvidenceEvaluation against schema and Stage 1 advisory policy."""

    _evidence_evaluation_validator().validate(payload)

    if payload.get("trusted") is not False:
        raise ContractValidationError("evidence evaluation trusted must remain false")

    status = payload.get("verification_status")
    validity = payload.get("validity")
    judgement = payload.get("data_json", {}).get("ai_judgement", {})
    if judgement.get("verification_status") != status:
        raise ContractValidationError(
            "data_json.ai_judgement.verification_status must match top-level"
        )
    if judgement.get("validity") != validity:
        raise ContractValidationError("data_json.ai_judgement.validity must match top-level")
    if judgement.get("reason_code") != payload.get("reason_code"):
        raise ContractValidationError("data_json.ai_judgement.reason_code must match top-level")

    if status == "PASS" and validity != "VALID_CANDIDATE":
        raise ContractValidationError("PASS evidence evaluation must be VALID_CANDIDATE")
    if status == "UNCERTAIN" and validity != "NEEDS_REVIEW":
        raise ContractValidationError("UNCERTAIN evidence evaluation must be NEEDS_REVIEW")
    if payload.get("reason_code") in {"LOW_PIXEL_BUDGET", "LOW_QUALITY_EVIDENCE"}:
        if status != "UNCERTAIN" or validity != "NEEDS_REVIEW":
            raise ContractValidationError(
                "quality-review evidence evaluation must be UNCERTAIN/NEEDS_REVIEW"
            )

    image_uri = payload.get("image_uri")
    if image_uri is not None:
        validate_evidence_image_uri(image_uri)
