"""Orchestration state key/phase compatibility (Phase 4c).

Writers use steps / step_index / AWAITING_OPERATOR.
Readers accept legacy legs / cursor / NEEDS_ATTENTION.
"""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any

PHASE_RUNNING = "RUNNING"
PHASE_DONE = "DONE"
PHASE_FAILED = "FAILED"
PHASE_AWAITING_OPERATOR = "AWAITING_OPERATOR"
PHASE_RECOVERY_RUNNING = "RECOVERY_RUNNING"
PHASE_ADVANCING = "ADVANCING"
PHASE_CANCEL_REQUESTED = "CANCEL_REQUESTED"
PHASE_ABORTED = "ABORTED"

# Legacy aliases accepted on read
PHASE_NEEDS_ATTENTION_LEGACY = "NEEDS_ATTENTION"
_LEGACY_AWAITING = PHASE_NEEDS_ATTENTION_LEGACY

HOLD_PHASES = {PHASE_AWAITING_OPERATOR, PHASE_RECOVERY_RUNNING, _LEGACY_AWAITING}

EVENT_AWAITING_OPERATOR = "TASK_AWAITING_OPERATOR"
# Legacy event type still emitted alongside for older UIs/logs
EVENT_NEEDS_ATTENTION_LEGACY = "TASK_NEEDS_ATTENTION"


def normalize_phase(phase: str | None) -> str:
    value = str(phase or "")
    if value == _LEGACY_AWAITING:
        return PHASE_AWAITING_OPERATOR
    return value


def get_steps(orch: dict[str, Any]) -> list[dict[str, Any]]:
    steps = orch.get("steps")
    if isinstance(steps, list):
        return steps
    legs = orch.get("legs")
    if isinstance(legs, list):
        return legs
    return []


def get_step_index(orch: dict[str, Any]) -> int:
    if "step_index" in orch and orch.get("step_index") is not None:
        return int(orch.get("step_index") or 0)
    return int(orch.get("cursor") or 0)


def set_steps(orch: dict[str, Any], steps: list[dict[str, Any]]) -> None:
    orch["steps"] = steps


def set_step_index(orch: dict[str, Any], index: int) -> None:
    orch["step_index"] = int(index)


def set_phase(orch: dict[str, Any], phase: str) -> None:
    normalized = normalize_phase(phase)
    orch["phase"] = normalized
    if normalized == PHASE_AWAITING_OPERATOR:
        # Dual-write legacy for one release window of external consumers.
        pass


def is_hold_phase(phase: str | None) -> bool:
    return normalize_phase(phase) in {PHASE_AWAITING_OPERATOR, PHASE_RECOVERY_RUNNING} or str(phase or "") in HOLD_PHASES


def new_orchestration(steps: list[dict[str, Any]], *, callback_base_url: str | None = None) -> dict[str, Any]:
    return {
        "steps": steps,
        "step_index": 0,
        "phase": PHASE_RUNNING,
        "callback_base_url": callback_base_url,
    }


def is_dispatched_robot_task_step(step: dict[str, Any]) -> bool:
    return str(step.get("status") or "").upper() == "DISPATCHED"


def cargo_state_after_steps(steps: list[dict[str, Any]]) -> str:
    """Derive whether completed transfer steps currently leave cargo loaded."""
    loaded = False
    for step in steps:
        if str(step.get("status") or "").upper() != "DONE":
            continue
        action = str(step.get("transfer_action") or (step.get("params") or {}).get("action") or "").lower()
        if action == "load":
            loaded = True
        elif action == "unload":
            loaded = False
    return "LOADED" if loaded else "EMPTY"


def deterministic_step_command_id(task_id: int, robot_id: str, step: dict[str, Any], step_index: int) -> str:
    """Stable command identity for a task step, including retries after a crash."""
    kind = str(step.get("kind") or "move_to_point")
    seq = int(step.get("seq") or step_index + 1)
    retry_generation = int(step.get("retry_generation") or 0)
    identity: dict[str, Any] = {"kind": kind, "params": step.get("params") or {}}
    if retry_generation > 0:
        identity["retry_generation"] = retry_generation
    fingerprint = sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:12]
    retry_suffix = f"-retry-{retry_generation}" if retry_generation > 0 else ""
    return f"task-{task_id}-{robot_id}-{kind}-step-{seq}{retry_suffix}-{fingerprint}"


def deterministic_evidence_command_id(
    task_id: int,
    operation: str,
    command_sequence_no: int | None,
    attempt: int,
) -> str:
    """Stable Main→AI command identity, separate from ``commands.id``.

    ``commands.id`` identifies the static recipe definition.  This string
    identifies one runtime observation attempt and is echoed by AI Server.
    """
    normalized_operation = str(operation or "evidence").strip().lower().replace("_", "-")
    sequence = int(command_sequence_no or 0)
    return f"task-{task_id}-vision-{normalized_operation}-step-{sequence}-attempt-{int(attempt)}"
