"""Shared compact contract for Vision person-hazard advisories."""

from __future__ import annotations

import json
from typing import Any

MAX_PERSON_HAZARD_PAYLOAD_BYTES = 64 * 1024

FORBIDDEN_PAYLOAD_KEYS = frozenset(
    {"bbox", "bbox_xyxy", "mask", "mask_rle", "polygon", "raw_detections", "detections"}
)

FORBIDDEN_MOTION_STRINGS = frozenset({"HOLD", "E_STOP", "STOP_COMMAND", "MOTION_CANCELLED", "BLOCKED"})


def validate_person_hazard_payload(
    payload: dict[str, Any],
    *,
    expected_robot_id: str | None = None,
    expected_source: str | None = None,
    expected_task_id: int | None = None,
) -> None:
    """Reject malformed, oversized, or cross-context advisories before policy evaluation."""

    try:
        encoded_size = len(json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
    except (TypeError, ValueError) as exc:
        raise ValueError("person hazard payload must be JSON serializable") from exc
    if encoded_size > MAX_PERSON_HAZARD_PAYLOAD_BYTES:
        raise ValueError("person hazard payload exceeds size limit")

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for key, val in obj.items():
                if key in FORBIDDEN_PAYLOAD_KEYS:
                    raise ValueError(f"forbidden field: {key}")
                if isinstance(val, str) and val.upper() in FORBIDDEN_MOTION_STRINGS:
                    raise ValueError(f"forbidden motion string: {val}")
                _walk(val)
        elif isinstance(obj, list):
            for item in obj:
                _walk(item)

    _walk(payload)
    event = payload.get("event")
    if not isinstance(event, dict):
        raise ValueError("person hazard event must be an object")
    if event.get("trusted") is not False:
        raise ValueError("person hazard event.trusted must be false")

    robot_id = str(event.get("robot_id") or payload.get("robot_id") or "")
    source = str(event.get("source") or payload.get("source") or "")
    task_id = event.get("task_id")
    if not robot_id or not source or task_id is None:
        raise ValueError("person hazard event requires robot_id, source, and task_id")
    if payload.get("robot_id") and str(payload["robot_id"]) != robot_id:
        raise ValueError("person hazard robot_id mismatch")
    if payload.get("source") and str(payload["source"]) != source:
        raise ValueError("person hazard source mismatch")
    if expected_robot_id is not None and robot_id != str(expected_robot_id):
        raise ValueError("person hazard robot_id does not match active monitor")
    if expected_source is not None and source != str(expected_source):
        raise ValueError("person hazard source does not match active monitor")
    if expected_task_id is not None and str(task_id) != str(expected_task_id):
        raise ValueError("person hazard task_id does not match active monitor")

    confidence = event.get("confidence")
    if not isinstance(confidence, (int, float)) or isinstance(confidence, bool) or not 0 <= float(confidence) <= 1:
        raise ValueError("person hazard confidence must be between 0 and 1")
    data = event.get("data_json") or {}
    source_event_id = data.get("source_event_id") if isinstance(data, dict) else None
    if not source_event_id and not event.get("event_id"):
        raise ValueError("person hazard event requires event_id or source_event_id")
