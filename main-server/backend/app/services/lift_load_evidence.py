"""Main-side lift/load evidence recording and gating integration."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Literal

from app.core.config import settings
from app.db.repo_bridge import evidence_repo
from app.services.vision_proxy import VisionUpstreamError, post_lift_load_evaluate

logger = logging.getLogger(__name__)

LIFT_LOAD_SOURCE = "vision"
SKIP_EVENT = "LIFT_LOAD_EVIDENCE_SKIPPED"
ERROR_EVENT = "LIFT_LOAD_EVIDENCE_ERROR"
DEFAULT_EVENT = "LIFT_LOAD_EVIDENCE"
RESPONSE_SCHEMA_VERSION = "vision-lift-load-evaluate.v1"
EVENT_SCHEMA_VERSION = "vision-monitor-event.v1"

GateMode = Literal["record", "gate"]


class LiftLoadEvidenceSkip(ValueError):
    """Raised when Main does not have enough context to call AI evidence."""


def _mode() -> GateMode | None:
    if not bool(settings.lift_load_evidence_enabled):
        return None
    mode = str(settings.lift_load_evidence_mode or "record").strip().lower()
    return "gate" if mode == "gate" else "record" if mode == "record" else None


def _truthy_enabled() -> bool:
    return _mode() is not None


def _item_id(task: dict[str, Any]) -> str | None:
    value = task.get("item_id") or task.get("item_code")
    return str(value) if value else None


def _marker_for_item(item_id: str) -> str | None:
    marker = settings.lift_load_marker_map.get(item_id)
    return str(marker) if marker is not None and str(marker).strip() else None


def _storage_zone_for_floor(floor: Any) -> str:
    return "storage_upper_static_item_zone" if int(floor or 1) == 2 else "storage_lower_static_item_zone"


def _operation_and_zone(task: dict[str, Any], leg: dict[str, Any]) -> tuple[str, str]:
    task_type = str(task.get("task_type") or "").upper()
    params = leg.get("params") or {}
    action = str(params.get("action") or "").lower()
    operation_override = str(params.get("evidence_operation") or "").strip().upper()

    if task_type == "INBOUND" and action == "load":
        operation, zone = "PICK_UP", "inbound_static_item_zone"
    elif task_type == "INBOUND" and action == "unload":
        operation, zone = "DROP_OFF", _storage_zone_for_floor(task.get("to_floor"))
    elif task_type == "OUTBOUND" and action == "load":
        operation, zone = "PICK_UP", _storage_zone_for_floor(task.get("from_floor"))
    elif task_type == "OUTBOUND" and action == "unload":
        operation, zone = "DROP_OFF", "outbound_static_item_zone"
    else:
        raise LiftLoadEvidenceSkip(f"unsupported lift-load context task_type={task_type} action={action or 'none'}")

    if operation_override:
        if operation_override != "PRE_DROP_OFF" or action != "unload":
            raise LiftLoadEvidenceSkip(
                f"unsupported evidence_operation={operation_override} for task_type={task_type} action={action or 'none'}"
            )
        operation = operation_override
    return operation, zone


def build_request(task: dict[str, Any], leg: dict[str, Any], command_def_id: int | str | None) -> dict[str, object]:
    """Build the Main-facing AI Server request from task + dock_transfer leg context."""

    robot_id = task.get("assigned_robot_id")
    if not robot_id:
        raise LiftLoadEvidenceSkip("task has no assigned_robot_id")
    item_id = _item_id(task)
    if not item_id:
        raise LiftLoadEvidenceSkip("task has no item_id")
    marker_id = _marker_for_item(item_id)
    if marker_id is None:
        raise LiftLoadEvidenceSkip(f"item marker mapping missing: {item_id}")

    operation, vision_zone_id = _operation_and_zone(task, leg)
    return {
        "source": settings.lift_load_evidence_source or "global_cam_01",
        "robot_id": str(robot_id),
        "task_id": task.get("task_id"),
        "command_id": command_def_id,
        "operation": operation,
        "expected_item_id": item_id,
        "expected_marker_id": marker_id,
        "expected_item_count": 1,
        "vision_zone_id": vision_zone_id,
        "burst_frames": settings.lift_load_burst_frames,
        "min_pass_frames": settings.lift_load_min_pass_frames,
        "sample_interval_ms": settings.lift_load_sample_interval_ms,
        "max_frame_age_s": settings.lift_load_max_frame_age_s,
    }


def _compact_response(response: dict[str, Any]) -> dict[str, Any]:
    event = response.get("event") if isinstance(response.get("event"), dict) else {}
    data = event.get("data_json") if isinstance(event.get("data_json"), dict) else {}
    return {
        "schema_version": response.get("schema_version"),
        "monitor_id": response.get("monitor_id"),
        "result": response.get("result"),
        "reason_code": response.get("reason_code"),
        "event_type": event.get("event_type"),
        "event_id": event.get("event_id"),
        "profile_id": event.get("profile_id") or data.get("profile_id"),
        "threshold_set_id": event.get("threshold_set_id") or data.get("threshold_set_id"),
    }


def _normalize_operation(value: object) -> str | None:
    """Normalize the documented AI operation aliases for response binding.

    ``POST_PICK_UP``/``POST_PICKUP`` denotes Main's post-lift timing for the
    same physical pick-up assertion; it binds to the AI contract's ``PICKUP``.
    Main never sends this alias upstream--the request uses ``PICK_UP``--and
    all other aliases are the documented AI compatibility forms.
    """

    normalized = str(value or "").strip().upper().replace("-", "_")
    aliases = {
        "PICK_UP": "PICKUP",
        "PICKUP": "PICKUP",
        "POST_PICK_UP": "PICKUP",
        "POST_PICKUP": "PICKUP",
        "DROP_OFF": "DROPOFF",
        "DROPOFF": "DROPOFF",
        "PRE_DROP_OFF": "PRE_DROP_OFF",
        "PRE_DROPOFF": "PRE_DROP_OFF",
    }
    return aliases.get(normalized)


def _same_identity(left: object, right: object) -> bool:
    """Compare echoed trace identifiers without allowing omitted values."""

    return left is not None and right is not None and str(left) == str(right)


def _marker_id(value: object) -> str | None:
    raw = str(value or "").strip().upper()
    if raw.startswith("ARUCO_4X4_50_"):
        raw = raw.rsplit("_", 1)[-1]
    return str(int(raw)) if raw.isdigit() else None


def _event_observed_at_errors(event: dict[str, Any]) -> list[str]:
    raw = event.get("observed_at")
    if not isinstance(raw, str) or not raw.strip():
        return ["AI_EVIDENCE_OBSERVED_AT_MISSING"]
    try:
        observed_at = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return ["AI_EVIDENCE_OBSERVED_AT_MALFORMED"]
    if observed_at.tzinfo is None:
        return ["AI_EVIDENCE_OBSERVED_AT_MALFORMED"]

    now = datetime.now(timezone.utc)
    age_seconds = (now - observed_at.astimezone(timezone.utc)).total_seconds()
    max_age = float(settings.lift_load_evidence_max_age_s)
    skew = float(settings.lift_load_evidence_clock_skew_s)
    if age_seconds > max_age + skew:
        return ["AI_EVIDENCE_STALE"]
    if age_seconds < -skew:
        return ["AI_EVIDENCE_FUTURE"]
    return []


def _gate_binding_errors(response: dict[str, Any], request_payload: dict[str, object]) -> list[str]:
    """Return Main-owned reasons why advisory AI evidence cannot approve a gate.

    Only fields guaranteed by the lift-load endpoint and its nested monitor
    event are consulted. Missing echoed context is a failure, never a fallback
    to request context.
    """

    errors: list[str] = []
    event = response.get("event") if isinstance(response.get("event"), dict) else None
    if response.get("schema_version") != RESPONSE_SCHEMA_VERSION:
        errors.append("AI_EVIDENCE_RESPONSE_SCHEMA_MISMATCH")
    if response.get("trusted") is True:
        errors.append("AI_EVIDENCE_RESPONSE_TRUSTED_SPOOF")
    if event is None:
        return errors + ["AI_EVIDENCE_EVENT_MISSING"]
    if event.get("schema_version") != EVENT_SCHEMA_VERSION:
        errors.append("AI_EVIDENCE_EVENT_SCHEMA_MISMATCH")
    if event.get("trusted") is not False:
        errors.append("AI_EVIDENCE_EVENT_TRUSTED_SPOOF")

    for field, reason in (("source", "SOURCE"), ("robot_id", "ROBOT_ID"), ("task_id", "TASK_ID"), ("command_id", "COMMAND_ID")):
        expected = request_payload.get(field)
        if not _same_identity(response.get(field), expected) or not _same_identity(event.get(field), expected):
            errors.append(f"AI_EVIDENCE_{reason}_MISMATCH")

    request_operation = _normalize_operation(request_payload.get("operation"))
    response_operation = _normalize_operation(response.get("operation"))
    event_operation = _normalize_operation((event.get("data_json") or {}).get("operation")) if isinstance(event.get("data_json"), dict) else None
    if not request_operation or response_operation != request_operation or event_operation != request_operation:
        errors.append("AI_EVIDENCE_OPERATION_MISMATCH")

    data = event.get("data_json") if isinstance(event.get("data_json"), dict) else None
    if data is None:
        return errors + ["AI_EVIDENCE_EVENT_DATA_MISSING"]
    if response.get("vision_zone_id") != request_payload.get("vision_zone_id") or data.get("vision_zone_id") != request_payload.get("vision_zone_id"):
        errors.append("AI_EVIDENCE_ZONE_MISMATCH")
    if data.get("expected_item_id") != request_payload.get("expected_item_id"):
        errors.append("AI_EVIDENCE_ITEM_MISMATCH")
    expected_marker = _marker_id(request_payload.get("expected_marker_id"))
    returned_markers = data.get("expected_marker_ids")
    marker_ids = {_marker_id(marker) for marker in returned_markers} if isinstance(returned_markers, list) else set()
    if expected_marker is None or marker_ids != {expected_marker}:
        errors.append("AI_EVIDENCE_MARKER_MISMATCH")
    if data.get("expected_item_count") != request_payload.get("expected_item_count"):
        errors.append("AI_EVIDENCE_ITEM_COUNT_MISMATCH")

    expected_event_types = {
        "PICKUP": "ITEM_PICKED",
        "DROPOFF": "ITEM_PLACED",
        "PRE_DROP_OFF": "ITEM_PLACEMENT_READY",
    }
    if event.get("event_type") != expected_event_types.get(request_operation):
        errors.append("AI_EVIDENCE_EVENT_TYPE_MISMATCH")
    if response.get("result") != event.get("result") or data.get("result") != response.get("result"):
        errors.append("AI_EVIDENCE_RESULT_MISMATCH")
    if data.get("command_satisfying") is not True:
        errors.append("AI_EVIDENCE_COMMAND_NOT_SATISFYING")
    errors.extend(_event_observed_at_errors(event))
    return errors


def _response_data(response: dict[str, Any], request_payload: dict[str, object], task: dict[str, Any]) -> dict[str, Any]:
    event = response.get("event") if isinstance(response.get("event"), dict) else {}
    data = event.get("data_json") if isinstance(event.get("data_json"), dict) else {}
    return {
        "schema_version": response.get("schema_version"),
        "monitor_id": response.get("monitor_id"),
        "robot_id": response.get("robot_id") or request_payload.get("robot_id"),
        "operation": response.get("operation"),
        "request_operation": request_payload.get("operation"),
        "vision_zone_id": response.get("vision_zone_id") or data.get("vision_zone_id"),
        "zone_resolution_source": data.get("zone_resolution_source"),
        "location_id": data.get("location_id"),
        "expected_item_id": data.get("expected_item_id") or request_payload.get("expected_item_id"),
        "expected_marker_id": request_payload.get("expected_marker_id"),
        "expected_marker_ids": data.get("expected_marker_ids") or [request_payload.get("expected_marker_id")],
        "expected_item_count": data.get("expected_item_count") or request_payload.get("expected_item_count"),
        "task_quantity": task.get("quantity"),
        "result": response.get("result"),
        "reason_code": response.get("reason_code"),
        "command_satisfying": bool(data.get("command_satisfying")),
        "observed_count": data.get("observed_count"),
        "accepted_frames": data.get("accepted_frames"),
        "total_frames": data.get("total_frames"),
        "detected_marker_id": data.get("detected_marker_id"),
        "detected_marker_ids": data.get("detected_marker_ids"),
        "upstream_response_summary": _compact_response(response),
        # Keep the original advisory payload for audit/debugging. `_append`
        # always persists it as trusted=False; no AI field becomes Main truth.
        "upstream_response": response,
    }


def _append(
    conn,
    *,
    task_id: int | None,
    command_def_id: int | str | None,
    event_type: str,
    data_json: dict[str, Any],
    confidence: float | None = None,
) -> int:
    command_id: int | None
    try:
        command_id = int(command_def_id) if command_def_id is not None else None
    except (TypeError, ValueError):
        command_id = None
    return evidence_repo(conn).append(
        task_id=task_id,
        command_id=command_id,
        event_type=event_type,
        source=LIFT_LOAD_SOURCE,
        confidence=confidence,
        trusted=False,
        data_json=data_json,
    )


def record_skip(conn, *, task: dict[str, Any], command_def_id: int | str | None, reason: str) -> int:
    return _append(
        conn,
        task_id=task.get("task_id"),
        command_def_id=command_def_id,
        event_type=SKIP_EVENT,
        data_json={"reason": reason, "robot_id": task.get("assigned_robot_id"), "item_id": _item_id(task)},
    )


def record_error(
    conn,
    *,
    task: dict[str, Any],
    command_def_id: int | str | None,
    request_payload: dict[str, object] | None,
    error: str,
    status_code: int | None = None,
) -> int:
    return _append(
        conn,
        task_id=task.get("task_id"),
        command_def_id=command_def_id,
        event_type=ERROR_EVENT,
        data_json={
            "error": error,
            "status_code": status_code,
            "request": request_payload or {},
        },
    )


def _gate_result(
    *,
    evidence_id: int | None,
    result: str | None,
    reason_code: str | None,
    command_satisfying: bool,
    status: str = "recorded",
    binding_errors: list[str] | None = None,
) -> dict[str, Any]:
    binding_errors = binding_errors or []
    if binding_errors and status == "recorded":
        status = "hold"
        reason_code = binding_errors[0]
    approved = status == "recorded" and str(result or "").upper() == "PASS" and command_satisfying is True and not binding_errors
    return {
        "evidence_id": evidence_id,
        "advisory_evidence_id": evidence_id,
        "result": result,
        "reason_code": reason_code,
        "command_satisfying": bool(command_satisfying),
        "approved": approved,
        "status": status,
        "binding_errors": binding_errors,
    }


def evaluate_and_record(conn, task: dict[str, Any], leg: dict[str, Any], command_def_id: int | str | None) -> int | dict[str, Any] | None:
    """Call AI lift-load evidence and record the advisory result.

    In ``record`` mode this preserves the historical contract: return the
    created evidence id, or ``None`` when disabled/non-dock. In ``gate`` mode
    it returns a structured decision input with evidence id/result/reason code
    and ``command_satisfying``; only PASS + command_satisfying true is approved.
    """

    mode = _mode()
    if mode is None:
        return None
    gate = mode == "gate"
    if str(leg.get("kind") or "") != "dock_transfer":
        return _gate_result(evidence_id=None, result=None, reason_code="NOT_DOCK_TRANSFER", command_satisfying=False, status="skip") if gate else None

    try:
        request_payload = build_request(task, leg, command_def_id)
    except LiftLoadEvidenceSkip as exc:
        ev_id = record_skip(conn, task=task, command_def_id=command_def_id, reason=str(exc))
        return _gate_result(evidence_id=ev_id, result=None, reason_code=str(exc), command_satisfying=False, status="skip") if gate else ev_id

    try:
        response = post_lift_load_evaluate(request_payload)
    except VisionUpstreamError as exc:
        ev_id = record_error(
            conn,
            task=task,
            command_def_id=command_def_id,
            request_payload=request_payload,
            error=str(exc),
            status_code=exc.status_code,
        )
        return _gate_result(evidence_id=ev_id, result="ERROR", reason_code=str(exc), command_satisfying=False, status="error") if gate else ev_id
    except Exception as exc:  # pragma: no cover - defensive boundary for record-only hook
        logger.exception("lift-load evidence call failed")
        ev_id = record_error(
            conn,
            task=task,
            command_def_id=command_def_id,
            request_payload=request_payload,
            error=str(exc),
        )
        return _gate_result(evidence_id=ev_id, result="ERROR", reason_code=str(exc), command_satisfying=False, status="error") if gate else ev_id

    event = response.get("event") if isinstance(response.get("event"), dict) else {}
    data = event.get("data_json") if isinstance(event.get("data_json"), dict) else {}
    event_type = str(event.get("event_type") or DEFAULT_EVENT)
    confidence = event.get("confidence")
    if not isinstance(confidence, (int, float)):
        confidence = None
    ev_id = _append(
        conn,
        task_id=task.get("task_id"),
        command_def_id=command_def_id,
        event_type=event_type,
        confidence=float(confidence) if confidence is not None else None,
        data_json=_response_data(response, request_payload, task) | {
            "ai_event_result": event.get("result"),
            "ai_event_reason_code": event.get("reason_code"),
            "ai_event_data_json": {
                key: data.get(key)
                for key in (
                    "policy_version",
                    "profile_id",
                    "threshold_set_id",
                    "assignment_status",
                )
                if key in data
            },
        },
    )
    binding_errors = _gate_binding_errors(response, request_payload) if gate else []
    return _gate_result(
        evidence_id=ev_id,
        result=str(response.get("result") or event.get("result") or "") or None,
        reason_code=response.get("reason_code") or event.get("reason_code"),
        command_satisfying=bool(data.get("command_satisfying")),
        binding_errors=binding_errors,
    ) if gate else ev_id
