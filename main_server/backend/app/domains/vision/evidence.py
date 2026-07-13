"""Main-side record-only lift/load evidence integration."""

from __future__ import annotations

import logging
from typing import Any

from app.core.config import settings
from app.db.mvp import evidence_repo
from app.domains.vision.client import VisionUpstreamError, post_lift_load_evaluate

logger = logging.getLogger(__name__)

LIFT_LOAD_SOURCE = "vision"
SKIP_EVENT = "LIFT_LOAD_EVIDENCE_SKIPPED"
ERROR_EVENT = "LIFT_LOAD_EVIDENCE_ERROR"
DEFAULT_EVENT = "LIFT_LOAD_EVIDENCE"


class LiftLoadEvidenceSkip(ValueError):
    """Raised when Main does not have enough context to call AI evidence."""


def _truthy_enabled() -> bool:
    return bool(settings.lift_load_evidence_enabled) and settings.lift_load_evidence_mode in {"record", "gate"}


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

    if task_type == "INBOUND" and action == "load":
        return "PICK_UP", "inbound_static_item_zone"
    if task_type == "INBOUND" and action == "unload":
        return "DROP_OFF", _storage_zone_for_floor(task.get("to_floor"))
    if task_type == "OUTBOUND" and action == "load":
        return "PICK_UP", _storage_zone_for_floor(task.get("from_floor"))
    if task_type == "OUTBOUND" and action == "unload":
        return "DROP_OFF", "outbound_static_item_zone"
    raise LiftLoadEvidenceSkip(f"unsupported lift-load context task_type={task_type} action={action or 'none'}")


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


def evaluate_and_record(conn, task: dict[str, Any], leg: dict[str, Any], command_def_id: int | str | None) -> int | None:
    """Call AI lift-load evidence and record the advisory result.

    Returns the created evidence id, or None when disabled. This is record-only:
    callers must not use exceptions here to fail movement progress.
    """

    if not _truthy_enabled():
        return None
    if str(leg.get("kind") or "") != "dock_transfer":
        return None

    try:
        request_payload = build_request(task, leg, command_def_id)
    except LiftLoadEvidenceSkip as exc:
        return record_skip(conn, task=task, command_def_id=command_def_id, reason=str(exc))

    try:
        response = post_lift_load_evaluate(request_payload)
    except VisionUpstreamError as exc:
        return record_error(
            conn,
            task=task,
            command_def_id=command_def_id,
            request_payload=request_payload,
            error=str(exc),
            status_code=exc.status_code,
        )
    except Exception as exc:  # pragma: no cover - defensive boundary for record-only hook
        logger.exception("lift-load evidence call failed")
        return record_error(
            conn,
            task=task,
            command_def_id=command_def_id,
            request_payload=request_payload,
            error=str(exc),
        )

    event = response.get("event") if isinstance(response.get("event"), dict) else {}
    data = event.get("data_json") if isinstance(event.get("data_json"), dict) else {}
    event_type = str(event.get("event_type") or DEFAULT_EVENT)
    confidence = event.get("confidence")
    if not isinstance(confidence, (int, float)):
        confidence = None
    return _append(
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
