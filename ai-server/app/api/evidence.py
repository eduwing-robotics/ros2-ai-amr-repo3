from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import HTTPException
from fastapi.responses import FileResponse
from jsonschema import ValidationError as JsonSchemaValidationError
from pydantic import BaseModel, Field

from ..config import get_settings
from ..contracts import (
    ContractValidationError,
    validate_evidence_evaluation,
    validate_evidence_image_route_segments,
    validate_lift_roi_evidence,
    validate_vision_event,
)
from ..evidence_cache import DEFAULT_VIEW_ID, normalize_view_id
from ..evidence_evaluation import (
    EVENT_TYPE_VALUES,
    EvidenceEvaluationError,
    build_no_frame_evaluation,
    build_quality_review_evaluation,
    map_lift_roi_evidence_to_evaluation,
    map_vision_event_to_evaluation,
    record_evidence_evaluation_observability,
    save_evidence_image,
)
from ..frame_store import StoredFrame
from ..openapi_schemas import (
    ERROR_RESPONSE_OPENAPI,
    SOURCE_ID_OPENAPI_EXTRA,
    _evidence_evaluation_openapi_schema,
    _json_response_openapi,
)
from ..runtime_state import RuntimeContext
from .dependencies import ContextGetter


class EvidenceEvaluateRequest(BaseModel):
    """Connector-facing advisory evidence-evaluation request."""

    source: str = Field(..., json_schema_extra=SOURCE_ID_OPENAPI_EXTRA)
    view: str = DEFAULT_VIEW_ID
    operation: str = "UNKNOWN"
    expected_evidence_type: str | None = None
    expected_count: int | None = Field(default=None, ge=0)
    task_ref: dict[str, Any] | None = None
    image_policy: dict[str, Any] = Field(
        default_factory=dict,
        description="Proof-image policy. Canonical keys: save_proof and proof_label.",
        json_schema_extra={
            "additionalProperties": False,
            "properties": {
                "save_proof": {"type": "boolean", "default": False},
                "proof_label": {"type": "string"},
            },
        },
    )
    quality_flags: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Optional conservative quality guardrail. Canonical keys: "
            "low_pixel_budget, low_quality_evidence, reason_code, and details."
        ),
        json_schema_extra={
            "additionalProperties": False,
            "properties": {
                "low_pixel_budget": {"type": "boolean", "default": False},
                "low_quality_evidence": {"type": "boolean", "default": False},
                "reason_code": {
                    "type": "string",
                    "enum": ["LOW_PIXEL_BUDGET", "LOW_QUALITY_EVIDENCE"],
                },
                "details": {"type": "object", "additionalProperties": True},
            },
        },
    )
    image_uri: str | None = Field(
        default=None,
        description="Rejected on request. Evidence image URIs are server-generated response fields.",
        json_schema_extra={"deprecated": True},
    )
    vision_event: dict[str, Any] | None = None
    lift_roi_evidence: dict[str, Any] | None = None
    max_frame_age_s: float | None = Field(default=None, ge=0)


def _ensure_known_source_view(source: str, view: str | None) -> str:
    settings = get_settings()
    if source not in settings.source_ids:
        raise HTTPException(status_code=400, detail=f"unknown source: {source}")
    view_id = normalize_view_id(view)
    try:
        settings.source_registry.resolve_view(source, view_id)
    except KeyError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"unknown view for source {source}: {view_id}",
        ) from exc
    return view_id


def _parse_frame_timestamp(frame: StoredFrame) -> datetime:
    timestamp = datetime.fromisoformat(frame.timestamp)
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone()


def _frame_age_s(frame: StoredFrame) -> float:
    return max(
        0.0,
        (datetime.now(timezone.utc).astimezone() - _parse_frame_timestamp(frame)).total_seconds(),
    )


_ALLOWED_IMAGE_POLICY_KEYS = {"save_proof", "proof_label"}
_ALLOWED_QUALITY_FLAG_KEYS = {
    "low_pixel_budget",
    "low_quality_evidence",
    "reason_code",
    "details",
}
_QUALITY_REASON_CODES = {"LOW_PIXEL_BUDGET", "LOW_QUALITY_EVIDENCE"}


def _ensure_image_policy(image_policy: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(image_policy, dict):
        raise HTTPException(status_code=400, detail="image_policy must be an object")
    unknown = sorted(set(image_policy) - _ALLOWED_IMAGE_POLICY_KEYS)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unknown image_policy keys: {', '.join(unknown)}",
        )
    return image_policy


def _ensure_quality_flags(quality_flags: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(quality_flags, dict):
        raise HTTPException(status_code=400, detail="quality_flags must be an object")
    unknown = sorted(set(quality_flags) - _ALLOWED_QUALITY_FLAG_KEYS)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"unknown quality_flags keys: {', '.join(unknown)}",
        )
    for key in ("low_pixel_budget", "low_quality_evidence"):
        if key in quality_flags and not isinstance(quality_flags[key], bool):
            raise HTTPException(
                status_code=400,
                detail=f"quality_flags.{key} must be a boolean",
            )
    reason_code = quality_flags.get("reason_code")
    if reason_code is not None and reason_code not in _QUALITY_REASON_CODES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown quality_flags.reason_code: {reason_code}",
        )
    details = quality_flags.get("details")
    if details is not None and not isinstance(details, dict):
        raise HTTPException(
            status_code=400,
            detail="quality_flags.details must be an object",
        )
    return quality_flags


def _image_policy_store_image(image_policy: dict[str, Any]) -> bool:
    policy = _ensure_image_policy(image_policy)
    save_proof = policy.get("save_proof", False)
    if not isinstance(save_proof, bool):
        raise HTTPException(status_code=400, detail="image_policy.save_proof must be a boolean")
    return save_proof


def _image_policy_filename_hint(
    image_policy: dict[str, Any],
    evaluation: dict[str, Any],
) -> str:
    policy = _ensure_image_policy(image_policy)
    hint = policy.get("proof_label")
    if hint is not None:
        if not isinstance(hint, str) or not hint.strip():
            raise HTTPException(
                status_code=400,
                detail="image_policy.proof_label must be a non-empty string",
            )
        return hint
    return str(evaluation.get("reason_code") or "evidence").lower()


def _ensure_expected_evidence_type(value: str | None) -> None:
    if value is not None and value not in EVENT_TYPE_VALUES:
        raise HTTPException(
            status_code=400,
            detail=f"unknown expected_evidence_type: {value}",
        )


def _attach_proof_image_if_requested(
    evaluation: dict[str, Any],
    *,
    request: EvidenceEvaluateRequest,
    frame: StoredFrame | None,
) -> dict[str, Any]:
    if request.image_uri:
        raise HTTPException(
            status_code=400,
            detail="image_uri is response-only; use image_policy.save_proof to store a server-generated proof image",
        )

    if not _image_policy_store_image(request.image_policy):
        return evaluation
    if frame is None:
        return evaluation

    try:
        location = save_evidence_image(
            frame.encoded,
            source=request.source,
            view=normalize_view_id(request.view),
            evaluation_id=evaluation["evaluation_id"],
            observed_at=evaluation["observed_at"],
            content_type=frame.content_type,
            filename_hint=_image_policy_filename_hint(request.image_policy, evaluation),
        )
    except EvidenceEvaluationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    evaluation["image_uri"] = location.image_uri
    evaluation["data_json"]["proof_image"] = {
        "image_uri": location.image_uri,
        "content_type": location.content_type,
    }
    validate_evidence_evaluation(evaluation)
    return evaluation


def _assert_original_source_matches_request(
    *,
    request: EvidenceEvaluateRequest,
    original: dict[str, Any],
    field: str,
) -> None:
    if original.get("source") != request.source:
        raise HTTPException(
            status_code=400,
            detail=f"{field}.source must match request source",
        )


def _evaluation_from_request_payload(
    *,
    request: EvidenceEvaluateRequest,
) -> dict[str, Any] | None:
    if request.lift_roi_evidence is not None:
        _assert_original_source_matches_request(
            request=request,
            original=request.lift_roi_evidence,
            field="lift_roi_evidence",
        )
        try:
            validate_lift_roi_evidence(request.lift_roi_evidence)
            return map_lift_roi_evidence_to_evaluation(
                request.lift_roi_evidence,
                view=normalize_view_id(request.view),
                expected_evidence_type=request.expected_evidence_type,
                expected_count=request.expected_count,
                task_ref=request.task_ref,
            )
        except (
            ContractValidationError,
            EvidenceEvaluationError,
            JsonSchemaValidationError,
            TypeError,
            ValueError,
        ) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    if request.vision_event is not None:
        _assert_original_source_matches_request(
            request=request,
            original=request.vision_event,
            field="vision_event",
        )
        try:
            validate_vision_event(request.vision_event)
            return map_vision_event_to_evaluation(
                request.vision_event,
                view=normalize_view_id(request.view),
                operation=request.operation,
                expected_evidence_type=request.expected_evidence_type,
                task_ref=request.task_ref,
                min_confidence=None,
            )
        except (
            ContractValidationError,
            EvidenceEvaluationError,
            JsonSchemaValidationError,
            TypeError,
            ValueError,
        ) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return None


def _evaluation_from_quality_flags(
    *,
    request: EvidenceEvaluateRequest,
) -> dict[str, Any] | None:
    flags = _ensure_quality_flags(request.quality_flags)
    if not flags:
        return None
    reason_code = flags.get("reason_code")
    if reason_code is None:
        if flags.get("low_pixel_budget"):
            reason_code = "LOW_PIXEL_BUDGET"
        elif flags.get("low_quality_evidence"):
            reason_code = "LOW_QUALITY_EVIDENCE"
    if reason_code is None:
        return None
    try:
        return build_quality_review_evaluation(
            source=request.source,
            view=normalize_view_id(request.view),
            operation=request.operation,
            expected_evidence_type=request.expected_evidence_type,
            expected_count=request.expected_count,
            task_ref=request.task_ref,
            reason_code=reason_code,
            quality_details=flags.get("details") or {},
        )
    except EvidenceEvaluationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _evaluation_from_latest_runtime_state(
    *,
    request: EvidenceEvaluateRequest,
    runtime_context: RuntimeContext,
    frame: StoredFrame | None,
) -> dict[str, Any]:
    settings = get_settings()
    if frame is None:
        return build_no_frame_evaluation(
            source=request.source,
            view=normalize_view_id(request.view),
            operation=request.operation,
            expected_evidence_type=request.expected_evidence_type,
            expected_count=request.expected_count,
            task_ref=request.task_ref,
            reason_code="NO_FRAME",
        )

    max_frame_age_s = (
        request.max_frame_age_s
        if request.max_frame_age_s is not None
        else settings.source_stale_after_s
    )
    if _frame_age_s(frame) > max_frame_age_s:
        return build_no_frame_evaluation(
            source=request.source,
            view=normalize_view_id(request.view),
            operation=request.operation,
            expected_evidence_type=request.expected_evidence_type,
            expected_count=request.expected_count,
            task_ref=request.task_ref,
            reason_code="SOURCE_STALE",
        )

    latest_events = runtime_context.store.latest(source=request.source, limit=1)
    if latest_events:
        try:
            return map_vision_event_to_evaluation(
                latest_events[0],
                view=normalize_view_id(request.view),
                operation=request.operation,
                expected_evidence_type=request.expected_evidence_type,
                task_ref=request.task_ref,
                min_confidence=None,
            )
        except EvidenceEvaluationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return build_no_frame_evaluation(
        source=request.source,
        view=normalize_view_id(request.view),
        operation=request.operation,
        expected_evidence_type=request.expected_evidence_type,
        expected_count=request.expected_count,
        task_ref=request.task_ref,
        reason_code="OBJECT_NOT_FOUND",
    )


def evaluate_evidence(
    payload: EvidenceEvaluateRequest,
    *,
    runtime_context: RuntimeContext,
) -> dict[str, Any]:
    """Evaluate evidence for a Main-owned connector without DB/Main side effects."""

    _ensure_known_source_view(payload.source, payload.view)
    _ensure_expected_evidence_type(payload.expected_evidence_type)
    if payload.image_uri is not None:
        raise HTTPException(
            status_code=400,
            detail="image_uri is response-only; use image_policy.save_proof to store a server-generated proof image",
        )
    frame = runtime_context.frame_store.latest(payload.source)
    evaluation = _evaluation_from_quality_flags(request=payload)
    if evaluation is None:
        evaluation = _evaluation_from_request_payload(request=payload)
    if evaluation is None:
        evaluation = _evaluation_from_latest_runtime_state(
            request=payload,
            runtime_context=runtime_context,
            frame=frame,
        )
    evaluation = _attach_proof_image_if_requested(
        evaluation,
        request=payload,
        frame=frame,
    )
    record_evidence_evaluation_observability(runtime_context, evaluation)
    return evaluation


def _safe_image_path(
    *,
    source: str,
    view: str,
    date: str,
    filename: str,
) -> Path:
    try:
        safe_source, safe_view, safe_date, safe_filename = validate_evidence_image_route_segments(
            source=source,
            view=view,
            date_part=date,
            filename=filename,
        )
    except ContractValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    _ensure_known_source_view(safe_source, safe_view)
    if Path(safe_filename).name != safe_filename:
        raise HTTPException(status_code=400, detail="invalid evidence image filename")
    root = get_settings().evidence_image_root.resolve()
    path = (root / safe_source / safe_view / safe_date / safe_filename).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid evidence image path") from exc
    return path


def evidence_image(
    source: str,
    view: str,
    date: str,
    filename: str,
) -> FileResponse:
    """Serve saved proof images by the public image_uri returned by evaluate."""

    path = _safe_image_path(source=source, view=view, date=date, filename=filename)
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="evidence image not found")
    return FileResponse(path)


def register_evidence_routes(app, *, context_getter: ContextGetter) -> None:
    def evaluate_route(payload: EvidenceEvaluateRequest) -> dict[str, Any]:
        return evaluate_evidence(payload, runtime_context=context_getter())

    app.post(
        "/api/v1/evidence/evaluate",
        responses={
            200: _json_response_openapi(
                "Connector-facing advisory EvidenceEvaluation v1",
                _evidence_evaluation_openapi_schema(),
            ),
            400: ERROR_RESPONSE_OPENAPI,
            422: ERROR_RESPONSE_OPENAPI,
            500: ERROR_RESPONSE_OPENAPI,
        },
    )(evaluate_route)
    app.get(
        "/api/v1/evidence/images/{source}/{view}/{date}/{filename}",
        responses={400: ERROR_RESPONSE_OPENAPI, 404: ERROR_RESPONSE_OPENAPI},
    )(evidence_image)


__all__ = ["EvidenceEvaluateRequest", "evaluate_evidence", "register_evidence_routes"]
