from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from .alert_window import build_alert_window_metadata
from .config import get_settings
from .contracts import validate_evidence_evaluation
from .observability import structured_log

EVIDENCE_EVALUATION_SCHEMA_VERSION = "evidence-evaluation.v1"
MAPPER_VERSION = "evidence-evaluation-mapper.v1"

EvaluationStatus = str
EvaluationValidity = str
ReasonCode = str

QUALITY_REVIEW_REASON_CODES = {"LOW_PIXEL_BUDGET", "LOW_QUALITY_EVIDENCE"}

EVENT_TYPE_VALUES = {
    "NAV_REACHED",
    "ARUCO_DETECTED",
    "LOAD_DETECTED",
    "ITEM_PICKED",
    "ITEM_PLACED",
    "ITEM_PLACEMENT_READY",
    "SLOT_CONFIRMED",
    "HUMAN_DETECTED",
    "HUMAN_CLEAR",
    "ITEM_DROPPED_CANDIDATE",
    "ERROR",
    "STATUS",
}


class EvidenceEvaluationError(ValueError):
    """Raised for caller-supplied evidence-evaluation mapping errors."""


@dataclass(frozen=True)
class EvidenceImageLocation:
    """Filesystem/public-URI pair for a saved proof image."""

    path: Path
    image_uri: str
    content_type: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat()


def _parse_observed_at(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc).astimezone()
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise EvidenceEvaluationError("observed_at must be ISO-8601") from exc
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone()


def _safe_path_token(value: Any, *, fallback: str = "none") -> str:
    token = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value or "").strip()).strip(".-")
    return token or fallback


def _extension_for_content_type(content_type: str) -> str:
    normalized = content_type.split(";", 1)[0].strip().lower()
    return {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
    }.get(normalized, "jpg")


def build_evidence_image_location(
    *,
    source: str,
    view: str,
    evaluation_id: str,
    observed_at: str | None = None,
    content_type: str = "image/jpeg",
    root: Path | None = None,
    base_uri: str | None = None,
    filename_hint: str | None = None,
) -> EvidenceImageLocation:
    """Build the local path and public image_uri for a proof image.

    The path is deterministic and rooted under ``settings.evidence_image_root`` by
    default, so tests can inject ``tmp_path`` and production can mount a stable
    evidence volume. The returned URI intentionally points to the AI Server
    evidence image route and contains no DB/Main identifier assumptions.
    """

    settings = get_settings()
    observed = _parse_observed_at(observed_at)
    date_part = observed.date().isoformat()
    extension = _extension_for_content_type(content_type)
    safe_source = _safe_path_token(source, fallback="unknown-source")
    safe_view = _safe_path_token(view, fallback="full")
    if not str(evaluation_id or "").strip():
        raise EvidenceEvaluationError("evaluation_id must be a non-empty string")
    safe_eval = _safe_path_token(evaluation_id)
    safe_hint = _safe_path_token(filename_hint, fallback="proof")
    filename = f"{safe_hint}-{safe_eval}.{extension}"
    image_root = root if root is not None else settings.evidence_image_root
    image_base_uri = base_uri if base_uri is not None else settings.evidence_image_base_uri
    path = image_root / safe_source / safe_view / date_part / filename
    uri = "/".join(
        part.strip("/")
        for part in (
            image_base_uri,
            safe_source,
            safe_view,
            date_part,
            filename,
        )
        if part.strip("/")
    )
    if image_base_uri.startswith("http://") or image_base_uri.startswith("https://"):
        # Preserve the scheme separator stripped by the generic join above.
        uri = image_base_uri.rstrip("/") + f"/{safe_source}/{safe_view}/{date_part}/{filename}"
    else:
        uri = "/" + uri
    return EvidenceImageLocation(path=path, image_uri=uri, content_type=content_type)


def save_evidence_image(
    encoded: bytes,
    *,
    source: str,
    view: str,
    evaluation_id: str,
    observed_at: str | None = None,
    content_type: str = "image/jpeg",
    root: Path | None = None,
    base_uri: str | None = None,
    filename_hint: str | None = None,
) -> EvidenceImageLocation:
    """Persist a proof image and return its public evidence image URI."""

    if not encoded:
        raise EvidenceEvaluationError("encoded evidence image must not be empty")
    location = build_evidence_image_location(
        source=source,
        view=view,
        evaluation_id=evaluation_id,
        observed_at=observed_at,
        content_type=content_type,
        root=root,
        base_uri=base_uri,
        filename_hint=filename_hint,
    )
    location.path.parent.mkdir(parents=True, exist_ok=True)
    location.path.write_bytes(encoded)
    return location


def _clean_task_ref(value: dict[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise EvidenceEvaluationError("task_ref must be an object or null")
    return {
        "task_id": value.get("task_id"),
        "command_id": value.get("command_id"),
        "location_id": value.get("location_id"),
    }


def _normalize_operation(value: Any) -> str:
    operation = str(value or "UNKNOWN").strip().upper()
    aliases = {
        "PICK_UP": "PICKUP",
        "PICKUP": "PICKUP",
        "DROP_OFF": "DROPOFF",
        "DROPOFF": "DROPOFF",
        "PRE_DROP_OFF": "PRE_DROP_OFF",
        "PRE_DROPOFF": "PRE_DROP_OFF",
        "MONITOR": "MONITOR",
    }
    return aliases.get(operation, "UNKNOWN")


def _normalize_event_type(value: Any) -> str | None:
    if value is None:
        return None
    event_type = str(value).strip().upper()
    return event_type if event_type in EVENT_TYPE_VALUES else None


def _validity_for_status(
    verification_status: EvaluationStatus,
    *,
    reason_code: ReasonCode,
) -> EvaluationValidity:
    if verification_status == "PASS":
        return "VALID_CANDIDATE"
    if verification_status == "UNCERTAIN":
        return "NEEDS_REVIEW"
    if reason_code == "DROPPED_ITEM_DETECTED":
        return "VALID_CANDIDATE"
    return "INVALID_CANDIDATE"


def _proposed_event_type_for_vision_event(event: dict[str, Any]) -> str | None:
    if event.get("event_kind") == "STALE":
        return "STATUS"
    if event.get("wms_hint") == "DROPPED_ITEM_CANDIDATE":
        return "ITEM_DROPPED_CANDIDATE"
    class_name = event.get("class_name")
    if class_name in {"aruco_marker", "qr_marker", "apriltag_marker"}:
        return "ARUCO_DETECTED"
    if class_name in {"box", "pallet"}:
        return "LOAD_DETECTED"
    if class_name == "person":
        return "HUMAN_DETECTED"
    if class_name == "dropped_item":
        return "ITEM_DROPPED_CANDIDATE"
    if class_name == "obstacle":
        return "ERROR"
    return "STATUS"


def _proposed_event_type_for_lift_roi(
    *,
    operation: str,
    expected_evidence_type: str | None,
    verification_status: str,
    dropped_item_count: int,
) -> str | None:
    if dropped_item_count > 0:
        return "ITEM_DROPPED_CANDIDATE"
    if verification_status == "FAIL":
        return "ERROR"
    if expected_evidence_type in EVENT_TYPE_VALUES:
        return expected_evidence_type
    if operation == "PICKUP":
        return "ITEM_PICKED"
    if operation == "DROPOFF":
        return "ITEM_PLACED"
    if operation == "PRE_DROP_OFF":
        return "ITEM_PLACEMENT_READY"
    if operation == "MONITOR":
        return "LOAD_DETECTED"
    return "STATUS"


def _confidence_from_lift_roi(evidence: dict[str, Any]) -> float | None:
    items = [
        *evidence.get("load", {}).get("accepted_items", []),
        *evidence.get("load", {}).get("rejected_items", []),
    ]
    confidences = [
        float(item["confidence"])
        for item in items
        if isinstance(item, dict) and isinstance(item.get("confidence"), int | float)
    ]
    if confidences:
        return round(max(confidences), 3)
    if evidence.get("load", {}).get("count", 0) == 0:
        return 0.0
    return None


def _lift_roi_status_reason(
    evidence: dict[str, Any],
    *,
    expected_count: int | None,
    expected_evidence_type: str | None,
) -> tuple[EvaluationStatus, ReasonCode]:
    verification = evidence.get("verification", {})
    verification_status = verification.get("status")
    verification_reason = str(verification.get("reason") or "")
    load = evidence.get("load", {})
    observed_count = load.get("count")
    dropped_item_count = int(evidence.get("dropped_item_count") or 0)

    if dropped_item_count > 0:
        if expected_evidence_type == "ITEM_DROPPED_CANDIDATE":
            return "PASS", "DROPPED_ITEM_DETECTED"
        return "FAIL", "DROPPED_ITEM_DETECTED"
    if verification_status == "CONFIRMED":
        return "PASS", "COUNT_MATCH_AND_STABLE"
    if expected_count is not None and observed_count != expected_count:
        return "FAIL", "COUNT_MISMATCH"
    if verification_status == "FAILED" or "mismatch" in verification_reason:
        return "FAIL", "COUNT_MISMATCH"
    if not evidence.get("count_stable"):
        return "UNCERTAIN", "ROI_NOT_STABLE"
    if observed_count in {None, 0}:
        return "UNCERTAIN", "OBJECT_NOT_FOUND"
    return "UNCERTAIN", "POLICY_NOT_APPLICABLE"


def _vision_event_status_reason(
    event: dict[str, Any],
    *,
    expected_evidence_type: str | None,
    min_confidence: float | None,
) -> tuple[EvaluationStatus, ReasonCode]:
    if event.get("event_kind") == "STALE":
        return "UNCERTAIN", "SOURCE_STALE"
    proposed = _proposed_event_type_for_vision_event(event)
    confidence = event.get("confidence")
    if isinstance(confidence, int | float) and min_confidence is not None:
        if float(confidence) < min_confidence:
            return "UNCERTAIN", "LOW_CONFIDENCE"
    if proposed == "ITEM_DROPPED_CANDIDATE":
        if expected_evidence_type == "ITEM_DROPPED_CANDIDATE":
            return "PASS", "DROPPED_ITEM_DETECTED"
        return "FAIL", "DROPPED_ITEM_DETECTED"
    if expected_evidence_type and proposed != expected_evidence_type:
        return "FAIL", "OBJECT_NOT_FOUND"
    if event.get("event_kind") in {"CONFIRMED", "CANDIDATE"}:
        return "PASS", "COUNT_MATCH_AND_STABLE"
    return "UNCERTAIN", "POLICY_NOT_APPLICABLE"


def _base_evaluation_payload(
    *,
    source: str,
    view: str,
    operation: str,
    expected_evidence_type: str | None,
    proposed_event_type: str | None,
    verification_status: EvaluationStatus,
    reason_code: ReasonCode,
    confidence: float | None,
    image_uri: str | None,
    task_ref: dict[str, Any] | None,
    observed_at: str,
    original_contract: str | None,
    original_payload: dict[str, Any] | None,
    ai_judgement_extra: dict[str, Any] | None = None,
    evaluation_id: str | None = None,
) -> dict[str, Any]:
    validity = _validity_for_status(verification_status, reason_code=reason_code)
    ai_judgement = {
        "verification_status": verification_status,
        "validity": validity,
        "reason_code": reason_code,
        **(ai_judgement_extra or {}),
    }
    data_json = {
        "ai_judgement": ai_judgement,
        "original_contract": original_contract,
        "original_payload": original_payload,
        "mapper_version": MAPPER_VERSION,
    }
    alert_window = build_alert_window_metadata(
        source=source,
        view=view,
        operation=operation,
        reason_code=reason_code,
        observed_at=observed_at,
    )
    if alert_window is not None:
        data_json["alert_window"] = alert_window
    payload = {
        "schema_version": EVIDENCE_EVALUATION_SCHEMA_VERSION,
        "evaluation_id": evaluation_id or str(uuid4()),
        "source": source,
        "view": view,
        "operation": operation,
        "expected_evidence_type": expected_evidence_type,
        "proposed_event_type": proposed_event_type,
        "verification_status": verification_status,
        "validity": validity,
        "reason_code": reason_code,
        "confidence": confidence,
        "trusted": False,
        "image_uri": image_uri,
        "task_ref": _clean_task_ref(task_ref),
        "data_json": data_json,
        "observed_at": observed_at,
    }
    validate_evidence_evaluation(payload)
    return payload


def map_lift_roi_evidence_to_evaluation(
    evidence: dict[str, Any],
    *,
    view: str = "lift_roi",
    expected_evidence_type: str | None = None,
    expected_count: int | None = None,
    task_ref: dict[str, Any] | None = None,
    image_uri: str | None = None,
    evaluation_id: str | None = None,
    observed_at: str | None = None,
) -> dict[str, Any]:
    """Map LiftRoiEvidence v1 to connector-facing EvidenceEvaluation v1."""

    if evidence.get("schema_version") != "lift-roi-evidence.v1":
        raise EvidenceEvaluationError("original payload must be lift-roi-evidence.v1")
    operation = _normalize_operation(evidence.get("operation"))
    effective_expected_count = (
        expected_count if expected_count is not None else evidence.get("expected_count")
    )
    expected_type = _normalize_event_type(expected_evidence_type)
    status, reason_code = _lift_roi_status_reason(
        evidence,
        expected_count=effective_expected_count,
        expected_evidence_type=expected_type,
    )
    observed_count = evidence.get("load", {}).get("count")
    dropped_item_count = int(evidence.get("dropped_item_count") or 0)
    proposed = _proposed_event_type_for_lift_roi(
        operation=operation,
        expected_evidence_type=expected_type,
        verification_status=status,
        dropped_item_count=dropped_item_count,
    )
    return _base_evaluation_payload(
        source=evidence["source"],
        view=view,
        operation=operation,
        expected_evidence_type=expected_type,
        proposed_event_type=proposed,
        verification_status=status,
        reason_code=reason_code,
        confidence=_confidence_from_lift_roi(evidence),
        image_uri=image_uri,
        task_ref=task_ref,
        observed_at=observed_at or evidence.get("timestamp") or _now_iso(),
        original_contract="lift-roi-evidence.v1",
        original_payload=evidence,
        ai_judgement_extra={
            "expected_count": effective_expected_count,
            "observed_count": observed_count,
            "stable_frames": evidence.get("stable_frames"),
        },
        evaluation_id=evaluation_id,
    )


def map_vision_event_to_evaluation(
    event: dict[str, Any],
    *,
    view: str = "full",
    operation: str = "UNKNOWN",
    expected_evidence_type: str | None = None,
    task_ref: dict[str, Any] | None = None,
    image_uri: str | None = None,
    evaluation_id: str | None = None,
    observed_at: str | None = None,
    min_confidence: float | None = None,
) -> dict[str, Any]:
    """Map VisionEvent v1 to connector-facing EvidenceEvaluation v1."""

    if event.get("schema_version") != "vision-event.v1":
        raise EvidenceEvaluationError("original payload must be vision-event.v1")
    expected_type = _normalize_event_type(expected_evidence_type)
    proposed = _proposed_event_type_for_vision_event(event)
    status, reason_code = _vision_event_status_reason(
        event,
        expected_evidence_type=expected_type,
        min_confidence=min_confidence,
    )
    confidence = event.get("confidence")
    numeric_confidence = (
        round(float(confidence), 3) if isinstance(confidence, int | float) else None
    )
    return _base_evaluation_payload(
        source=event["source"],
        view=view,
        operation=_normalize_operation(operation),
        expected_evidence_type=expected_type,
        proposed_event_type=proposed,
        verification_status=status,
        reason_code=reason_code,
        confidence=numeric_confidence,
        image_uri=image_uri,
        task_ref=task_ref,
        observed_at=observed_at or event.get("timestamp") or _now_iso(),
        original_contract="vision-event.v1",
        original_payload=event,
        ai_judgement_extra={
            "expected_count": None,
            "observed_count": 1 if proposed and proposed != "STATUS" else None,
            "stable_frames": event.get("metadata", {}).get("n_frame_count"),
        },
        evaluation_id=evaluation_id,
    )


def build_no_frame_evaluation(
    *,
    source: str,
    view: str,
    operation: str = "UNKNOWN",
    expected_evidence_type: str | None = None,
    expected_count: int | None = None,
    task_ref: dict[str, Any] | None = None,
    evaluation_id: str | None = None,
    observed_at: str | None = None,
    reason_code: ReasonCode = "NO_FRAME",
) -> dict[str, Any]:
    """Build an UNCERTAIN evaluation when no usable frame/original payload exists."""

    if reason_code not in {
        "NO_FRAME",
        "SOURCE_STALE",
        "MODEL_UNAVAILABLE",
        "OBJECT_NOT_FOUND",
        *QUALITY_REVIEW_REASON_CODES,
    }:
        raise EvidenceEvaluationError("unsupported no-frame reason_code")
    return _base_evaluation_payload(
        source=source,
        view=view,
        operation=_normalize_operation(operation),
        expected_evidence_type=_normalize_event_type(expected_evidence_type),
        proposed_event_type=None,
        verification_status="UNCERTAIN",
        reason_code=reason_code,
        confidence=None,
        image_uri=None,
        task_ref=task_ref,
        observed_at=observed_at or _now_iso(),
        original_contract=None,
        original_payload=None,
        ai_judgement_extra={
            "expected_count": expected_count,
            "observed_count": None,
            "stable_frames": 0,
        },
        evaluation_id=evaluation_id,
    )


def build_quality_review_evaluation(
    *,
    source: str,
    view: str,
    reason_code: ReasonCode,
    operation: str = "UNKNOWN",
    expected_evidence_type: str | None = None,
    expected_count: int | None = None,
    task_ref: dict[str, Any] | None = None,
    evaluation_id: str | None = None,
    observed_at: str | None = None,
    quality_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build an UNCERTAIN/NEEDS_REVIEW response for quality guardrails."""

    if reason_code not in QUALITY_REVIEW_REASON_CODES:
        raise EvidenceEvaluationError("unsupported quality-review reason_code")
    return _base_evaluation_payload(
        source=source,
        view=view,
        operation=_normalize_operation(operation),
        expected_evidence_type=_normalize_event_type(expected_evidence_type),
        proposed_event_type=None,
        verification_status="UNCERTAIN",
        reason_code=reason_code,
        confidence=None,
        image_uri=None,
        task_ref=task_ref,
        observed_at=observed_at or _now_iso(),
        original_contract=None,
        original_payload=None,
        ai_judgement_extra={
            "expected_count": expected_count,
            "observed_count": None,
            "stable_frames": 0,
            "quality_details": quality_details or {},
        },
        evaluation_id=evaluation_id,
    )


def record_evidence_evaluation_observability(
    runtime_context: Any,
    evaluation: dict[str, Any],
) -> None:
    """Record counters and one structured advisory-evaluation log line."""

    runtime_context.metrics.record_evidence_evaluation(
        source=evaluation["source"],
        verification_status=evaluation["verification_status"],
        reason_code=evaluation["reason_code"],
    )
    structured_log(
        runtime_context.logger,
        "evidence_evaluation",
        evaluation_id=evaluation["evaluation_id"],
        source=evaluation["source"],
        view=evaluation["view"],
        verification_status=evaluation["verification_status"],
        validity=evaluation["validity"],
        reason_code=evaluation["reason_code"],
        trusted=evaluation["trusted"],
    )


__all__ = [
    "EVIDENCE_EVALUATION_SCHEMA_VERSION",
    "EVENT_TYPE_VALUES",
    "EvidenceEvaluationError",
    "EvidenceImageLocation",
    "build_evidence_image_location",
    "build_no_frame_evaluation",
    "build_quality_review_evaluation",
    "map_lift_roi_evidence_to_evaluation",
    "map_vision_event_to_evaluation",
    "record_evidence_evaluation_observability",
    "save_evidence_image",
]
