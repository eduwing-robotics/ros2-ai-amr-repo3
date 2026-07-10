from __future__ import annotations

from copy import deepcopy
from typing import Any

from .contracts import (
    VISION_MONITOR_FORBIDDEN_KEYS,
    VISION_MONITOR_FORBIDDEN_VALUES,
    ContractValidationError,
)
from .vision_monitor_profiles import (
    LIFT_EVIDENCE_PROFILE_ID,
    LIFT_EVIDENCE_THRESHOLD_SET_ID,
    POLICY_VERSION,
)

COMMAND_PICKUP = {"PICK_UP", "PICKUP"}
COMMAND_DROPOFF = {"DROP_OFF", "DROPOFF"}
COMMAND_SATISFYING_EVENT_TYPES = {"ITEM_PICKED", "ITEM_PLACED", "ITEM_PLACEMENT_READY"}
SAFETY_EVENT_TYPES = {"HUMAN_DETECTED", "DROPPED_ITEM_CANDIDATE"}


def _assert_compact(value: Any) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in VISION_MONITOR_FORBIDDEN_KEYS:
                raise ContractValidationError(f"Main DB payload contains forbidden key: {key}")
            _assert_compact(child)
        return
    if isinstance(value, list):
        for child in value:
            _assert_compact(child)
        return
    if isinstance(value, str) and value in VISION_MONITOR_FORBIDDEN_VALUES:
        raise ContractValidationError(f"Main DB payload contains forbidden control value: {value}")


def _data_json_from(payload: dict[str, Any]) -> dict[str, Any]:
    data_json = deepcopy(payload.get("data_json") or {})
    for field in ("result", "reason_code", "policy_version", "profile_id", "threshold_set_id"):
        if field in payload:
            data_json.setdefault(field, payload[field])
    if "robot_id" in payload:
        data_json.setdefault("robot_id", payload.get("robot_id"))
    if "related_robot_ids" in payload:
        data_json.setdefault("related_robot_ids", payload.get("related_robot_ids") or [])
    if "assignment_status" in payload:
        data_json.setdefault("assignment_status", payload.get("assignment_status"))
    _assert_compact(data_json)
    return data_json


def evidence_event_row_from_monitor_payload(
    payload: dict[str, Any],
    *,
    task_id: int | str | None = None,
    command_id: int | str | None = None,
    event_type: str | None = None,
) -> dict[str, Any]:
    """Build a compact Main `evidence_events` insert shape.

    This does not write the DB. It only normalizes the row shape that Main can
    insert after applying its own policy/cooldown/trust decisions.
    """

    _assert_compact(payload)
    data_json = _data_json_from(payload)
    row = {
        "task_id": task_id if task_id is not None else payload.get("task_id"),
        "command_id": command_id if command_id is not None else payload.get("command_id"),
        "event_type": event_type or payload.get("event_type"),
        "source": payload.get("source", "ai-server"),
        "confidence": payload.get("confidence"),
        "severity": payload.get("severity", "INFO"),
        "trusted": False,
        "image_url": payload.get("image_url"),
        "data_json": data_json,
        "observed_at": payload.get("observed_at"),
    }
    _assert_compact(row)
    return row


def evidence_event_row_from_lift_evaluation(
    evaluation: dict[str, Any],
    *,
    operation: str,
    source: str = "global_cam_01",
    robot_id: str | None = None,
    task_id: int | str | None = None,
    command_id: int | str | None = None,
    observed_at: str | None = None,
    image_url: str | None = None,
) -> dict[str, Any]:
    operation_key = operation.upper()
    result = evaluation.get("result")
    event_type = evaluation.get("event_type")
    if result == "PASS":
        if operation_key in COMMAND_PICKUP:
            event_type = "ITEM_PICKED"
        elif operation_key in COMMAND_DROPOFF:
            event_type = "ITEM_PLACED"
    elif result == "UNCERTAIN":
        event_type = "LIFT_LOAD_UNCERTAIN"
    else:
        event_type = event_type or "LIFT_LOAD_EVIDENCE"

    payload = {
        "event_type": event_type,
        "source": source,
        "robot_id": robot_id,
        "task_id": task_id,
        "command_id": command_id,
        "result": result,
        "reason_code": evaluation.get("reason_code"),
        "confidence": evaluation.get("confidence"),
        "severity": "INFO" if result == "PASS" else "MEDIUM",
        "trusted": False,
        "image_url": image_url,
        "observed_at": observed_at,
        "policy_version": evaluation.get("policy_version", POLICY_VERSION),
        "profile_id": evaluation.get("profile_id", LIFT_EVIDENCE_PROFILE_ID),
        "threshold_set_id": evaluation.get("threshold_set_id", LIFT_EVIDENCE_THRESHOLD_SET_ID),
        "data_json": {
            **deepcopy(evaluation.get("data_json") or {}),
            "robot_id": robot_id,
            "ai_judgement": {
                "verification_status": result,
                "reason_code": evaluation.get("reason_code"),
                "expected_count": evaluation.get("expected_count"),
                "observed_count": evaluation.get("observed_count"),
                "accepted_frames": evaluation.get("accepted_frames"),
            },
        },
    }
    return evidence_event_row_from_monitor_payload(payload, task_id=task_id, command_id=command_id)


def command_progress_satisfied(row: dict[str, Any]) -> bool:
    return row.get("event_type") in COMMAND_SATISFYING_EVENT_TYPES


def safety_stop_decision_from_evidence_row(row: dict[str, Any]) -> dict[str, Any]:
    """Return whether Main may open `safety_stops` for this evidence row.

    The current Main DB contract represents HOLD only in `safety_stops`; this
    helper intentionally never emits a `tasks.status` update such as BLOCKED.
    """

    data_json = row.get("data_json") or {}
    event_type = row.get("event_type")
    assignment_status = data_json.get("assignment_status")
    robot_id = data_json.get("robot_id")
    robot_resolvable = bool(row.get("task_id") or robot_id)
    should_open = (
        event_type in SAFETY_EVENT_TYPES
        and robot_resolvable
        and assignment_status not in {"AMBIGUOUS", "UNASSIGNED"}
    )
    return {
        "open_safety_stop": should_open,
        "detected_evidence_event_type": event_type,
        "robot_resolvable": robot_resolvable,
        "robot_id": robot_id,
        "status": "OPEN" if should_open else "NO_DECISION",
        "task_status_update": None,
    }


__all__ = [
    "command_progress_satisfied",
    "evidence_event_row_from_lift_evaluation",
    "evidence_event_row_from_monitor_payload",
    "safety_stop_decision_from_evidence_row",
]
