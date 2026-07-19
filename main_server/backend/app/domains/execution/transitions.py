"""책임: Movement Scenario callback의 계약·순서·완료 gate를 순수하게 판정한다.
비책임: DB 저장, 재고 변경, 복구 실행과 Movement 물리 제어."""

from __future__ import annotations

from typing import Any

from app.domains.execution import steps as scenario_steps
from app.domains.movement.scenario_adapter import CONTRACT_VERSION

SCENARIO_EVENT_NAMES = {
    "COMMAND_ACCEPTED": "ACCEPTED",
    "COMMAND_RUNNING": "RUNNING",
    "COMMAND_DONE": "DONE",
    "COMMAND_FAILED": "FAILED",
    "COMMAND_ABORTED": "ABORTED",
    "COMMAND_STOPPED": "CANCELLED",
    "COMMAND_CANCELLED": "CANCELLED",
}
SCENARIO_PROGRESS_FIELDS = (
    "contract_version",
    "event",
    "execution_id",
    "state",
    "current_step_index",
    "current_step_code",
    "current_step_action",
    "last_completed_step_index",
    "cargo_state",
    "business_completed",
    "authority_owner",
    "authority_released",
    "navigator_status",
    "is_emergency",
    "reason_code",
    "message",
    "reported_at",
    "updated_at",
)


def normalize_movement_event(event: dict[str, Any]) -> str:
    raw = str(event.get("event") or event.get("state") or event.get("status") or "").upper()
    if raw in {"CANCELED", "STOPPED"}:
        return "CANCELLED"
    return SCENARIO_EVENT_NAMES.get(raw, raw)


def update_scenario_progress(
    orchestration: dict[str, Any], step: dict[str, Any], event: dict[str, Any]
) -> dict[str, Any]:
    """계약 필드만 orchestration과 현재 step에 같은 snapshot으로 반영해 반환한다."""
    previous = step.get("scenario_progress") or {}
    progress = dict(previous) if isinstance(previous, dict) else {}
    progress.update({field: event[field] for field in SCENARIO_PROGRESS_FIELDS if field in event})
    step["scenario_progress"] = progress
    orchestration["scenario_progress"] = progress
    return progress


def update_route_timeline(step: dict[str, Any], event: dict[str, Any], event_name: str) -> None:
    """현재 단계와 code가 일치할 때만 step의 9단계 timeline을 전진시킨다."""
    timeline = step.get("route_timeline")
    if not isinstance(timeline, list) or not timeline:
        return
    try:
        current = int(event.get("current_step_index"))
    except (TypeError, ValueError):
        current = -1
    if event_name == "DONE":
        current = len(timeline) - 1
    if current < 0:
        return
    current = min(current, len(timeline) - 1)
    expected_code = str(timeline[current].get("step_code") or timeline[current].get("kind") or "")
    callback_code = str(event.get("current_step_code") or "")
    if callback_code and callback_code != expected_code:
        return
    step["route_timeline_current_index"] = current
    terminal_failure = event_name in {"FAILED", "ABORTED", "REJECTED", "CANCELLED"}
    step_completed = "COMPLETED" in event_name
    for index, item in enumerate(timeline):
        if index < current or event_name == "DONE":
            item["status"] = "DONE"
        elif index == current:
            item["status"] = event_name if terminal_failure else "DONE" if step_completed else "RUNNING"
            if terminal_failure:
                item["failure_reason"] = event.get("message") or event.get("reason")
    step["route_timeline"] = timeline


def scenario_done_gate_errors(progress: dict[str, Any]) -> list[str]:
    checks = {
        "current_step_code": str(progress.get("current_step_code") or "") == "PARK",
        "business_completed": progress.get("business_completed") is True,
        "cargo_state": str(progress.get("cargo_state") or "").upper() == "EMPTY",
        "authority_owner": str(progress.get("authority_owner") or "").upper() == "MAIN",
        "authority_released": progress.get("authority_released") is True,
        "navigator_status": str(progress.get("navigator_status") or "").upper() == "IDLE",
        "is_emergency": progress.get("is_emergency") is False,
    }
    try:
        checks["last_completed_step_index"] = (
            int(progress.get("last_completed_step_index")) >= scenario_steps.PARK_STEP_INDEX
        )
    except (TypeError, ValueError):
        checks["last_completed_step_index"] = False
    return [field for field, valid in checks.items() if not valid]


def scenario_event_contract_errors(step: dict[str, Any], event: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if str(event.get("contract_version") or "") != CONTRACT_VERSION:
        errors.append("contract_version")
    raw_event = str(event.get("event") or event.get("state") or "").upper()
    if raw_event in {"STEP_STARTED", "STEP_COMPLETED"}:
        try:
            index = int(event.get("current_step_index"))
        except (TypeError, ValueError):
            index = -1
        code = str(event.get("current_step_code") or "")
        if scenario_steps.STEP_CODE_TO_INDEX.get(code) != index:
            errors.append("current_step")
    previous = step.get("scenario_progress") or {}
    old_last = previous.get("last_completed_step_index")
    new_last = event.get("last_completed_step_index")
    if old_last is not None and new_last is not None and int(new_last) < int(old_last):
        errors.append("last_completed_step_index")
    return errors
